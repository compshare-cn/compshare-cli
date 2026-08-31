from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

import typer

from compshare_cli.api import call, call_captured, collect_pages
from compshare_cli.commands.common import confirm_details, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.location import locate_instances, supported_locations
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact

app = typer.Typer(help="Manage dedicated bandwidth.", no_args_is_help=True)

_BANDWIDTH_COLUMNS = (
    ("ShareBandwidthId", "BANDWIDTH ID"),
    ("Region", "REGION"),
    ("Zone", "ZONE"),
    ("Bandwidth", "BANDWIDTH (Mbps)"),
    ("Status", "STATUS"),
    ("ChargeType", "CHARGE"),
    ("BindEIPCount", "EIPS"),
    ("PurchaseValue", "EXPIRES"),
)
_BANDWIDTH_JSON_FIELDS = (
    "ShareBandwidthId",
    "ResourceId",
    "Region",
    "Zone",
    "Bandwidth",
    "Status",
    "ChargeType",
    "Quantity",
    "PurchaseValue",
    "BindEIPCount",
    "BindEIPInfo",
    "CreateTime",
    "UpdateTime",
)
_EIP_COLUMNS = (
    ("UHostId", "INSTANCE"),
    ("Name", "NAME"),
    ("Zone", "ZONE"),
    ("IP", "PUBLIC IP"),
    ("EIPId", "EIP ID"),
    ("Scope", "BANDWIDTH SCOPE"),
    ("Bandwidth", "BANDWIDTH (Mbps)"),
    ("CanSwitch", "CAN SWITCH"),
)
_EIP_JSON_FIELDS = tuple(key for key, _ in _EIP_COLUMNS) + (
    "Region",
    "ShareBandwidthId",
    "TargetScope",
)


def _charge_type(value: str) -> str:
    charge = {"month": "Month", "year": "Year"}.get(value.casefold())
    if charge is None:
        raise UsageError(tr("--charge must be Month or Year."))
    return charge


def _target_scope(value: str) -> Tuple[str, str]:
    target = {
        "company": ("Company", "dedicated"),
        "dedicated": ("Company", "dedicated"),
        "public": ("Public", "shared"),
        "shared": ("Public", "shared"),
    }.get(value.casefold())
    if target is None:
        raise UsageError(tr("--to must be dedicated or shared."))
    return target


def _cny(cents: Any, *, signed: bool = False) -> Optional[str]:
    if isinstance(cents, bool) or not isinstance(cents, (int, float)):
        return None
    amount = Decimal(str(cents)) / 100
    if signed and amount < 0:
        return tr("Refund {amount} CNY", amount=f"{abs(amount):.2f}")
    if signed and amount > 0:
        return tr("Payment {amount} CNY", amount=f"{amount:.2f}")
    return f"{amount:.2f} CNY"


def _request(
    ctx: typer.Context,
    region: str,
    zone: str,
    values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(values or {})
    return params


def _bandwidth_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    return response.get("CompanyShareBandwidthSet") or []


def _eip_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for host in response.get("UHostSet") or []:
        for ip in host.get("IPSet") or []:
            if not ip.get("IPId") or ip.get("Type") in {"Private", "Proxy"}:
                continue
            assignment = ip.get("ShareBandwidth") or {}
            yield {
                "UHostId": host.get("UHostId"),
                "Name": host.get("Name"),
                "Region": host.get("Region"),
                "Zone": host.get("Zone"),
                "IP": ip.get("IP"),
                "EIPId": ip.get("IPId"),
                "Scope": assignment.get("Scope", "Unknown"),
                "ShareBandwidthId": assignment.get("ShareBandwidthId"),
                "Bandwidth": assignment.get("Bandwidth"),
                "CanSwitch": bool(assignment.get("CanSwitch")),
                "TargetScope": assignment.get("TargetScope"),
            }


@app.command("list", help="List dedicated bandwidth resources.")
def list_bandwidths(
    ctx: typer.Context,
    region: Optional[str] = typer.Option(None, "--region", help="Filter by region."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Filter by availability zone."),
) -> None:
    if zone is not None and region is None:
        raise UsageError(tr("--zone requires --region."))
    state = runtime(ctx)
    locations = [
        item
        for item in supported_locations(state, request_region=region)
        if not item.get("IsPod") and (zone is None or item.get("Zone") == zone)
    ]
    rows: List[Dict[str, Any]] = []
    for location in locations:
        location_region = str(location["Region"])
        location_zone = str(location["Zone"])
        response = call(
            state,
            "DescribeCompShareShareBandwidth",
            _request(ctx, location_region, location_zone),
        )
        bandwidth = response.get("CompanyShareBandwidth")
        if bandwidth:
            rows.append(
                {
                    **dict(bandwidth),
                    "Region": location_region,
                    "Zone": location_zone,
                }
            )
    response = {
        "CompanyShareBandwidthSet": rows,
        "TotalCount": len(rows),
        "ReturnedCount": len(rows),
    }
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=_bandwidth_rows(response),
        columns=_BANDWIDTH_COLUMNS,
        json_list=True,
        json_fields=_BANDWIDTH_JSON_FIELDS,
    )


@app.command("instances", help="List instance EIP bandwidth assignments.")
def instances(
    ctx: typer.Context,
    ids: Optional[List[str]] = typer.Option(None, "--id", help="Instance ID; repeatable."),
    region: Optional[str] = typer.Option(None, "--region", help="Filter by region."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Filter by availability zone."),
) -> None:
    if (region is None) != (zone is None):
        raise UsageError(tr("--region and --zone must be provided together."))
    state = runtime(ctx)
    params = request(ctx, region_value=region)
    params.update(
        compact(
            {
                "Zone": zone,
                "UHostIds": ids,
                "SkipBill": True,
                "IncludeShareBandwidth": True,
            }
        )
    )
    response = collect_pages(state, "DescribeCompShareInstance", params, "UHostSet")
    rows = list(_eip_rows(response))
    result = {
        "EIPSet": rows,
        "TotalCount": len(rows),
        "ReturnedCount": len(rows),
    }
    Renderer(state.json_output, state.show_sensitive).data(
        result,
        rows=rows,
        columns=_EIP_COLUMNS,
        json_list=True,
        json_fields=_EIP_JSON_FIELDS,
    )


@app.command("create", help="Purchase dedicated bandwidth after quoting the price.")
def create(
    ctx: typer.Context,
    bandwidth: int = typer.Option(
        ...,
        "--bandwidth",
        min=20,
        max=10000,
        help="Bandwidth limit in Mbps (20-10000).",
    ),
    charge: str = typer.Option("Month", help="Billing type: Month or Year."),
    quantity: int = typer.Option(1, min=1, help="Billing duration for prepaid modes."),
    region: str = typer.Option(..., "--region", help="Region for this request."),
    zone: str = typer.Option(..., "--zone", help="Availability zone."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Quote and show the request without purchasing bandwidth.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    params = _request(
        ctx,
        region,
        zone,
        {
            "ShareBandwidth": bandwidth,
            "ChargeType": _charge_type(charge),
            "Quantity": quantity,
        },
    )
    quote = call(state, "GetCompShareShareBandwidthPrice", params)
    plan = {"dry_run": dry_run, "request": params, "price": quote}
    fields = [
        ("ZONE", zone),
        ("BANDWIDTH", f"{bandwidth} Mbps"),
        ("CHARGE", params["ChargeType"]),
        ("QUANTITY", quantity),
        ("PRICE", _cny(quote.get("TotalPrice"))),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Create plan", fields, response=plan
        )
        return
    confirm_details(state, "Create plan", fields, "Confirm this operation?", yes)
    created = call(state, "CreateCompShareShareBandwidth", params)
    result = {"price": quote, "created": created}
    resource = created.get("CompanyShareBandwidth") or {}
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation completed",
        [
            ("BANDWIDTH ID", resource.get("ShareBandwidthId")),
            ("BANDWIDTH", f"{resource.get('Bandwidth', bandwidth)} Mbps"),
            ("ORDER", created.get("OrderNo")),
        ],
        response=result,
    )


@app.command("resize", help="Change a dedicated bandwidth limit after quoting the price.")
def resize(
    ctx: typer.Context,
    bandwidth_id: str = typer.Argument(..., help="Dedicated bandwidth ID."),
    bandwidth: int = typer.Option(
        ...,
        "--bandwidth",
        min=20,
        max=10000,
        help="Target bandwidth limit in Mbps (20-10000).",
    ),
    region: str = typer.Option(..., "--region", help="Region for this request."),
    zone: str = typer.Option(..., "--zone", help="Availability zone."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Quote and show the request without changing bandwidth.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    params = _request(
        ctx,
        region,
        zone,
        {"ShareBandwidthId": bandwidth_id, "ShareBandwidth": bandwidth},
    )
    quote = call(state, "GetCompShareShareBandwidthUpgradePrice", params)
    plan = {"dry_run": dry_run, "request": params, "price": quote}
    fields = [
        ("BANDWIDTH ID", bandwidth_id),
        ("ZONE", zone),
        ("TARGET BANDWIDTH", f"{bandwidth} Mbps"),
        ("PRICE", _cny(quote.get("TotalPrice"), signed=True)),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Operation plan", fields, response=plan
        )
        return
    confirm_details(state, "Operation plan", fields, "Confirm this operation?", yes)
    modified = call(state, "ModifyCompShareShareBandwidth", params)
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation completed",
        [("BANDWIDTH ID", bandwidth_id), ("BANDWIDTH", f"{bandwidth} Mbps")],
        response={"price": quote, "modified": modified},
    )


@app.command("delete", help="Delete dedicated bandwidth after quoting the refund.")
def delete(
    ctx: typer.Context,
    bandwidth_id: str = typer.Argument(..., help="Dedicated bandwidth ID."),
    region: str = typer.Option(..., "--region", help="Region for this request."),
    zone: str = typer.Option(..., "--zone", help="Availability zone."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Quote and show the request without deleting bandwidth.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    params = _request(ctx, region, zone, {"ShareBandwidthId": bandwidth_id})
    quote = call(state, "GetCompShareShareBandwidthRefundPrice", params)
    plan = {"dry_run": dry_run, "request": params, "refund": quote}
    fields = [
        ("BANDWIDTH ID", bandwidth_id),
        ("ZONE", zone),
        ("REFUND", _cny(quote.get("RefundPrice"), signed=True)),
        ("ACTION", tr("Migrate bound EIPs to shared bandwidth, then delete")),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Operation plan", fields, response=plan
        )
        return
    confirm_details(state, "Operation plan", fields, "Confirm this operation?", yes)
    deleted = call(state, "DeleteCompShareShareBandwidth", params)
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation completed",
        [
            ("BANDWIDTH ID", bandwidth_id),
            ("MIGRATED EIPS", deleted.get("MigratedEIPCount", 0)),
        ],
        response={"refund": quote, "deleted": deleted},
    )


@app.command("switch", help="Switch instance EIPs between dedicated and shared bandwidth.")
def switch(
    ctx: typer.Context,
    instances: List[str] = typer.Argument(..., help="Instance IDs."),
    target: str = typer.Option(..., "--to", help="Target bandwidth: dedicated or shared."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    target_scope, target_name = _target_scope(target)
    requested = list(dict.fromkeys(instances))
    locations, missing = locate_instances(state, requested)
    confirm_details(
        state,
        "Operation plan",
        [("INSTANCE", requested), ("TARGET", tr(target_name))],
        "Confirm this operation?",
        yes,
    )

    results: List[Dict[str, Any]] = [
        {
            "UHostId": instance,
            "Success": False,
            "Message": tr("Instance {instance} was not found.", instance=instance),
        }
        for instance in missing
    ]
    groups: Dict[Tuple[str, str], List[str]] = {}
    for instance in requested:
        location = locations.get(instance)
        if location is not None:
            groups.setdefault((location[0], location[1]), []).append(instance)

    for (region, zone), ids in groups.items():
        response, error = call_captured(
            state,
            "SwitchCompShareEIPShareBandwidth",
            _request(
                ctx,
                region,
                zone,
                {"UHostIds": ids, "TargetScope": target_scope},
            ),
        )
        if error:
            results.extend(
                {
                    "UHostId": instance,
                    "Region": region,
                    "Zone": zone,
                    "Success": False,
                    "Message": error.get("message"),
                }
                for instance in ids
            )
            continue
        returned = {
            str(item.get("UHostId")): item for item in (response or {}).get("Results") or []
        }
        for instance in ids:
            item = returned.get(instance) or {
                "UHostId": instance,
                "Success": False,
                "Message": tr(
                    "The API returned no result for instance {instance}.", instance=instance
                ),
            }
            results.append({**item, "Region": region, "Zone": zone})

    failed = [item for item in results if not item.get("Success")]
    payload: Dict[str, Any] = {"Results": results}
    if failed:
        payload.update(
            {
                "ok": False,
                "error": {
                    "code": "partial_failure",
                    "message": tr("Some bandwidth switches failed."),
                },
            }
        )
    Renderer(state.json_output, state.show_sensitive).data(
        payload,
        rows=results,
        columns=(
            ("UHostId", "INSTANCE"),
            ("Zone", "ZONE"),
            ("Success", "SUCCESS"),
            ("CurrentScope", "BANDWIDTH SCOPE"),
            ("Message", "MESSAGE"),
        ),
    )
    if failed:
        raise typer.Exit(1)
