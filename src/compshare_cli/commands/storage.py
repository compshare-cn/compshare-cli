from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import typer

from compshare_cli.api import call, invoke
from compshare_cli.commands.common import confirm, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.location import locate_disk, locate_instance
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact, disk_gib

app = typer.Typer(help="Manage disks and cloud storage.", no_args_is_help=True)
disk_app = typer.Typer(help="Manage instance disks.", no_args_is_help=True)
us3_app = typer.Typer(help="Manage US3 attachments.", no_args_is_help=True)
app.add_typer(disk_app, name="disk")
app.add_typer(us3_app, name="us3")


def _disk_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for instance in response.get("UHostSet") or []:
        for disk in instance.get("DiskSet") or []:
            row = dict(disk)
            row["UHostId"] = instance.get("UHostId")
            row["Region"] = instance.get("Region")
            size = row.get("Size")
            row["SizeDisplay"] = f"{size}GiB" if isinstance(size, int) else size
            yield row


@disk_app.command("list")
def list_disks(
    ctx: typer.Context,
    instance: Optional[str] = typer.Option(None, "--instance", help="Filter by instance ID."),
    region: Optional[str] = typer.Option(None, "--region", help="Filter by region."),
) -> None:
    """List disks reported by one or all instances."""
    state = runtime(ctx)
    if instance:
        resolved_region, _, host = locate_instance(
            state,
            instance,
            request_region=region,
        )
        response: Dict[str, Any] = {
            "UHostSet": [host],
            "RegionSet": [resolved_region],
        }
    else:
        params: Dict[str, Any] = {"Limit": 100, "Offset": 0}
        if region is not None:
            params["Region"] = region
        response = call(state, "DescribeCompShareInstance", params)
        response["RegionSet"] = list(
            dict.fromkeys(
                str(host["Region"]) for host in response.get("UHostSet") or [] if host.get("Region")
            )
        )
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=_disk_rows(response),
        columns=(
            ("UDiskId", "DISK ID"),
            ("Name", "NAME"),
            ("SizeDisplay", "SIZE"),
            ("Type", "TYPE"),
            ("IsBoot", "BOOT"),
            ("Device", "DEVICE"),
            ("UHostId", "INSTANCE"),
            ("Region", "REGION"),
        ),
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
) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params["UHostId"] = instance
    invoke(
        state,
        "AttachUS3",
        params,
        success=tr("Attached US3 to {instance}", instance=instance),
    )
