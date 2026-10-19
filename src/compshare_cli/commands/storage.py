from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterable, Optional

import typer

from compshare_cli.api import call, invoke
from compshare_cli.commands.common import confirm, confirm_details, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.location import locate_disk, locate_instance, supported_locations
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact, disk_gib

app = typer.Typer(help="Manage disks and cloud storage.", no_args_is_help=True)
disk_app = typer.Typer(help="Manage instance disks.", no_args_is_help=True)
us3_app = typer.Typer(help="Manage US3 attachments.", no_args_is_help=True)
cfs_app = typer.Typer(help="Manage CFS file storage for container instances.", no_args_is_help=True)
app.add_typer(disk_app, name="disk")
app.add_typer(us3_app, name="us3")
app.add_typer(cfs_app, name="cfs")


def _disk_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for disk in response.get("DiskSet") or []:
        yield dict(disk)


@disk_app.command("list")
def list_disks(
    ctx: typer.Context,
    instance: Optional[str] = typer.Option(None, "--instance", help="Filter by instance ID."),
    region: Optional[str] = typer.Option(None, "--region", help="Filter by region."),
) -> None:
    """List attached and detached disks from the disk inventory."""
    state = runtime(ctx)
    params = compact({"HostId": instance, "Region": region})
    response = call(state, "DescribeCompshareDisk", params)
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=_disk_rows(response),
        columns=(
            ("ResourceId", "DISK ID"),
            ("Name", "NAME"),
            ("Configuration", "SIZE"),
            ("DiskType", "TYPE"),
            ("Status", "STATUS"),
            ("MountInstance", "INSTANCE"),
            ("Zone", "ZONE"),
        ),
        json_list=True,
    )


@disk_app.command("create")
def create_disk(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance", help="Target instance ID."),
    size: str = typer.Option(..., help="Disk size, for example 100GiB."),
    name: str = typer.Option(..., help="Disk name."),
    disk_type: str = typer.Option("SSDDataDisk", "--type", help="Disk type."),
    charge: str = typer.Option("Month", help="Billing type."),
    quantity: int = typer.Option(1, min=1, help="Billing duration for prepaid modes."),
    coupon: Optional[str] = typer.Option(None, help="Coupon ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Create a disk and attach it to an instance."""
    confirm(
        tr(
            "Create {size} disk {name} and attach it to {instance}?",
            size=size,
            name=name,
            instance=instance,
        ),
        yes,
    )
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(
        compact(
            {
                "UHostId": instance,
                "Size": disk_gib(size),
                "DiskType": disk_type,
                "Name": name,
                "ChargeType": charge,
                "Quantity": quantity,
                "CouponId": coupon,
            }
        )
    )
    invoke(
        state,
        "CreateAndAttachCompshareDisk",
        params,
        success=tr("Created and attached disk {name}", name=name),
    )


@disk_app.command("attach", help="Attach an existing disk to an instance.")
def attach_disk(
    ctx: typer.Context,
    disk: str,
    instance: str = typer.Option(..., "--instance", help="Target instance ID."),
    disk_type: Optional[str] = typer.Option(None, "--type", help="Data disk type."),
) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(compact({"UHostId": instance, "UDiskId": disk, "DataDiskType": disk_type}))
    invoke(
        state,
        "AttachCompshareDisk",
        params,
        success=tr("Attached {disk} to {instance}", disk=disk, instance=instance),
    )


@disk_app.command("detach", help="Detach a disk from an instance.")
def detach_disk(
    ctx: typer.Context,
    disk: str,
    instance: str = typer.Option(..., "--instance", help="Attached instance ID."),
    device: str = typer.Option(..., help="Device path, for example /dev/vdb."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(
        tr(
            "Detach disk {disk} from {instance}? Ensure it is unmounted first.",
            disk=disk,
            instance=instance,
        ),
        yes,
    )
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(
        {
            "UHostId": instance,
            "UDiskId": disk,
            "Device": device,
        }
    )
    invoke(
        state,
        "DetachCompshareDisk",
        params,
        success=tr("Detached disk {disk}", disk=disk),
    )


@disk_app.command("price", help="Query a disk expansion price.")
def disk_price(
    ctx: typer.Context,
    disk: str,
    instance: str = typer.Option(..., "--instance", help="Attached instance ID."),
    size: str = typer.Option(..., help="Target disk size, for example 200GiB."),
    backup: Optional[str] = typer.Option(None, help="Backup mode: NONE, DATAARK or SNAPSHOT."),
) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(
        compact(
            {
                "UHostId": instance,
                "DiskId": disk,
                "DiskSpace": disk_gib(size),
                "BackupMode": backup,
            }
        )
    )
    invoke(state, "GetCompShareAttachedDiskUpgradePrice", params)


@disk_app.command("resize", help="Resize a disk.")
def resize_disk(
    ctx: typer.Context,
    disk: str,
    size: str = typer.Option(..., help="Target disk size, for example 200GiB."),
    instance: Optional[str] = typer.Option(None, "--instance", help="Attached instance ID."),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(tr("Resize disk {disk} to {size}? Disks cannot be shrunk.", disk=disk, size=size), yes)
    state = runtime(ctx)
    if (region is None) != (zone is None):
        raise UsageError(tr("--region and --zone must be provided together."))
    if instance:
        region, resolved_zone, _ = locate_instance(state, instance)
    elif region is not None and zone is not None:
        resolved_zone = zone
    else:
        region, resolved_zone, host, _ = locate_disk(state, disk)
        instance = str(host.get("UHostId")) if host else None
    params = request(
        ctx,
        zone=True,
        region_value=region,
        zone_value=resolved_zone,
    )
    params.update(compact({"UDiskId": disk, "UHostId": instance, "Size": disk_gib(size)}))
    invoke(
        state,
        "ResizeCompShareDisk",
        params,
        success=tr("Resized disk {disk}", disk=disk),
    )


@disk_app.command("delete", help="Permanently delete a disk.")
def delete_disk(
    ctx: typer.Context,
    disk: str,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(tr("Permanently delete disk {disk} and all its data?", disk=disk), yes)
    state = runtime(ctx)
    if (region is None) != (zone is None):
        raise UsageError(tr("--region and --zone must be provided together."))
    if region is not None and zone is not None:
        resolved_zone = zone
    else:
        region, resolved_zone, _, _ = locate_disk(state, disk)
    params = request(
        ctx,
        zone=True,
        region_value=region,
        zone_value=resolved_zone,
    )
    params["UDiskId"] = disk
    invoke(
        state,
        "DeleteCompshareDisk",
        params,
        success=tr("Deleted disk {disk}", disk=disk),
    )


@us3_app.command("attach", help="Attach US3 object storage to an instance.")
def attach_us3(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance", help="Target running instance ID."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params["UHostId"] = instance
    container = instance.startswith("cpod-")
    notice = (
        tr(
            "Attach CFS to {instance}? If none exists in this zone, this purchases 50 GiB "
            "for one month. Running instances may restart; save your work first.",
            instance=instance,
        )
        if container
        else tr("Attach US3 object storage to an instance.")
    )
    fields = [("INSTANCE", instance), ("ACTION", notice)]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Operation plan",
            fields,
            response={"dry_run": True, "action": "AttachUS3", "request": params, "notice": notice},
        )
        return
    if container:
        confirm_details(state, "Operation plan", fields, notice, yes)
    invoke(
        state,
        "AttachUS3",
        params,
        success=tr(
            "Submitted CFS attachment for {instance}"
            if container
            else "Attached US3 to {instance}",
            instance=instance,
        ),
    )


class CFSCharge(str, Enum):
    month = "Month"
    year = "Year"
    day = "Day"
    dynamic = "Dynamic"


def _cfs_size(size: str) -> int:
    value = disk_gib(size)
    if not 50 <= value <= 2048:
        raise UsageError(tr("CFS size must be between 50 and 2048 GiB."))
    return value


def _cfs_request(
    ctx: typer.Context,
    region: Optional[str],
    zone: Optional[str],
    project: Optional[str],
) -> Dict[str, Any]:
    if zone is not None:
        if region is None:
            raise UsageError(tr("--zone requires --region."))
        if not any(
            item.get("Region") == region and item.get("Zone") == zone and item.get("IsPod")
            for item in supported_locations(runtime(ctx), request_region=region)
        ):
            raise UsageError(tr("CFS requires a container availability zone."))
    return request(
        ctx, region_value=region, zone=zone is not None, zone_value=zone, project_id=project
    )


@cfs_app.command("list", help="List CFS file storage without pagination.")
def list_cfs(
    ctx: typer.Context,
    region: Optional[str] = typer.Option(None, help="Region for this request."),
    zone: Optional[str] = typer.Option(None, help="Filter by availability zone."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
) -> None:
    invoke(
        runtime(ctx),
        "DescribeCFS",
        _cfs_request(ctx, region, zone, project),
        list_key="CFSSet",
        columns=(
            ("CfsId", "CFS ID"),
            ("Name", "NAME"),
            ("ZoneId", "ZONE ID"),
            ("Size", "SIZE (GiB)"),
            ("ChargeType", "CHARGE"),
            ("PurchaseValue", "EXPIRES"),
            ("MountStatus", "MOUNT STATUS"),
            ("MountedUHostIds", "INSTANCES"),
        ),
    )


@cfs_app.command("show", help="Show a CFS resource and its mounted instances.")
def show_cfs(
    ctx: typer.Context,
    cfs: str = typer.Argument(..., help="CFS ID."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
) -> None:
    params = request(ctx, project_id=project)
    params["CfsId"] = cfs
    invoke(runtime(ctx), "DescribeCFS", params)


@cfs_app.command("price", help="Query the CFS purchase price in CNY.")
def cfs_price(
    ctx: typer.Context,
    size: str = typer.Option(..., help="CFS capacity, for example 100GiB (50-2048 GiB)."),
    region: str = typer.Option(..., help="Region for this request."),
    zone: str = typer.Option(..., help="Availability zone."),
    charge: CFSCharge = typer.Option(CFSCharge.month, help="Billing type."),
    quantity: int = typer.Option(1, min=1, help="Billing duration for prepaid modes."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
) -> None:
    values = {"Size": _cfs_size(size), "ChargeType": charge.value, "Quantity": quantity}
    params = {**_cfs_request(ctx, region, zone, project), **values}
    invoke(runtime(ctx), "GetCompShareCFSPrice", params)


@cfs_app.command("create", help="Purchase CFS storage after quoting the price.")
def create_cfs(
    ctx: typer.Context,
    name: str = typer.Option(..., help="CFS name."),
    size: str = typer.Option(..., help="CFS capacity, for example 100GiB (50-2048 GiB)."),
    region: str = typer.Option(..., help="Region for this request."),
    zone: str = typer.Option(..., help="Availability zone."),
    charge: CFSCharge = typer.Option(CFSCharge.month, help="Billing type."),
    quantity: int = typer.Option(1, min=1, help="Billing duration for prepaid modes."),
    coupon: Optional[str] = typer.Option(None, help="Coupon ID."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Quote and show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not name.strip():
        raise UsageError(tr("CFS name cannot be empty."))
    values = {"Size": _cfs_size(size), "ChargeType": charge.value, "Quantity": quantity}
    state = runtime(ctx)
    params = {**_cfs_request(ctx, region, zone, project), **values}
    quote = call(state, "GetCompShareCFSPrice", params)
    params.update(compact({"Name": name, "CouponId": coupon}))
    fields = [
        ("NAME", name),
        ("ZONE", zone),
        ("SIZE (GiB)", values["Size"]),
        ("CHARGE", charge.value),
        ("QUANTITY", quantity),
        ("COUPON", coupon),
        ("PRICE (CNY)", quote.get("PriceDetails")),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Create plan", fields, response={"dry_run": True, "request": params, "price": quote}
        )
        return
    confirm_details(state, "Create plan", fields, "Confirm this operation?", yes)
    invoke(state, "CreateCFS", params)


@cfs_app.command("resize-price", help="Query the CFS expansion price in CNY.")
def cfs_resize_price(
    ctx: typer.Context,
    cfs: str = typer.Argument(..., help="CFS ID."),
    size: str = typer.Option(..., help="Target CFS capacity, not an increment (50-2048 GiB)."),
    region: str = typer.Option(..., help="Region for this request."),
    zone: str = typer.Option(..., help="Availability zone."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
) -> None:
    values = {"CfsId": cfs, "Size": _cfs_size(size)}
    params = {**_cfs_request(ctx, region, zone, project), **values}
    invoke(runtime(ctx), "GetCompShareCFSUpgradePrice", params)


@cfs_app.command("resize", help="Expand CFS storage after quoting the price.")
def resize_cfs(
    ctx: typer.Context,
    cfs: str = typer.Argument(..., help="CFS ID."),
    size: str = typer.Option(..., help="Target CFS capacity, not an increment (50-2048 GiB)."),
    region: str = typer.Option(..., help="Region for this request."),
    zone: str = typer.Option(..., help="Availability zone."),
    coupon: Optional[str] = typer.Option(None, help="Coupon ID."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Quote and show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    values = {"CfsId": cfs, "Size": _cfs_size(size)}
    state = runtime(ctx)
    params = {**_cfs_request(ctx, region, zone, project), **values}
    quote = call(state, "GetCompShareCFSUpgradePrice", params)
    params.update(compact({"CouponId": coupon}))
    fields = [
        ("CFS ID", cfs),
        ("SIZE (GiB)", values["Size"]),
        ("COUPON", coupon),
        ("PRICE (CNY)", quote.get("Price")),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Operation plan", fields, response={"dry_run": True, "request": params, "price": quote}
        )
        return
    confirm_details(state, "Operation plan", fields, "Confirm this operation?", yes)
    invoke(state, "ResizeCFS", params)


@cfs_app.command("refund", help="Query the estimated CFS refund in CNY.")
def cfs_refund(
    ctx: typer.Context,
    cfs: str = typer.Argument(..., help="CFS ID."),
    region: str = typer.Option(..., help="Region for this request."),
    zone: str = typer.Option(..., help="Availability zone."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
) -> None:
    params = _cfs_request(ctx, region, zone, project)
    params["CFSId"] = cfs
    invoke(runtime(ctx), "GetCompShareCFSRefundPrice", params)


@cfs_app.command("delete", help="Permanently delete CFS storage after quoting the refund.")
def delete_cfs(
    ctx: typer.Context,
    cfs: str = typer.Argument(..., help="CFS ID."),
    region: str = typer.Option(..., help="Region for this request."),
    zone: str = typer.Option(..., help="Availability zone."),
    recycle: bool = typer.Option(False, help="Detach stopped instances before deleting CFS."),
    project: Optional[str] = typer.Option(None, help="Project ID."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Quote and show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    params = _cfs_request(ctx, region, zone, project)
    quote = call(state, "GetCompShareCFSRefundPrice", {**params, "CFSId": cfs})
    params.update({"CfsId": cfs, "Recycle": recycle})
    notice = tr("Permanently delete CFS {cfs} and all its data? Back up your data first.", cfs=cfs)
    fields = [
        ("CFS ID", cfs),
        ("REFUND (CNY)", quote.get("RefundPrice")),
        ("RECYCLE", recycle),
        ("ACTION", notice),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Operation plan", fields, response={"dry_run": True, "request": params, "refund": quote}
        )
        return
    confirm_details(state, "Operation plan", fields, notice, yes)
    invoke(state, "DeleteCFS", params)


@cfs_app.command("attach", help="Attach CFS; may purchase storage and restart the instance.")
def attach_cfs(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance", help="Target instance ID."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not instance.startswith("cpod-"):
        raise UsageError(tr("CFS attachments require a cpod- instance ID."))
    attach_us3(ctx, instance, dry_run, yes)


@cfs_app.command("detach", help="Detach CFS; running instances will restart.")
def detach_cfs(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance", help="Attached instance ID."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not instance.startswith("cpod-"):
        raise UsageError(tr("CFS attachments require a cpod- instance ID."))
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params["UHostId"] = instance
    notice = tr(
        "Detach CFS from {instance}? Running instances will restart; save your work first.",
        instance=instance,
    )
    fields = [("INSTANCE", instance), ("ACTION", notice)]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Operation plan",
            fields,
            response={"dry_run": True, "action": "DetachCFS", "request": params, "notice": notice},
        )
        return
    confirm_details(state, "Operation plan", fields, notice, yes)
    invoke(state, "DetachCFS", params)
