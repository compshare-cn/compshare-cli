from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import typer

from compshare_cli.api import invoke
from compshare_cli.commands.common import confirm, request, runtime
from compshare_cli.parsing import compact, disk_gib

app = typer.Typer(help="Manage disks and cloud storage.", no_args_is_help=True)
disk_app = typer.Typer(help="Manage instance disks.", no_args_is_help=True)
us3_app = typer.Typer(help="Manage US3 attachments.", no_args_is_help=True)
app.add_typer(disk_app, name="disk")
app.add_typer(us3_app, name="us3")


def _disk_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for instance in response.get("UHostSet", []):
        for disk in instance.get("DiskSet", []):
            row = dict(disk)
            row["UHostId"] = instance.get("UHostId")
            yield row


@disk_app.command("list")
def list_disks(
    ctx: typer.Context,
    instance: Optional[str] = typer.Option(None, "--instance"),
) -> None:
    """List disks reported by one or all instances."""
    params = request(ctx)
    if instance:
        params["UHostIds"] = [instance]
    invoke(
        runtime(ctx),
        "DescribeCompShareInstance",
        params,
        row_builder=_disk_rows,
        columns=(
            ("UDiskId", "DISK ID"),
            ("Name", "NAME"),
            ("Size", "SIZE"),
            ("Type", "TYPE"),
            ("IsBoot", "BOOT"),
            ("Device", "DEVICE"),
            ("UHostId", "INSTANCE"),
        ),
    )


@disk_app.command("create")
def create_disk(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance"),
    size: str = typer.Option(..., help="Disk size, for example 100GiB."),
    name: str = typer.Option(...),
    disk_type: str = typer.Option("SSDDataDisk", "--type"),
    charge: str = typer.Option("Month"),
    quantity: int = typer.Option(1, min=1),
    coupon: Optional[str] = typer.Option(None),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Create a disk and attach it to an instance."""
    confirm(f"Create {size} disk {name} and attach it to {instance}?", yes)
    params = request(ctx, zone=True)
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
        runtime(ctx),
        "CreateAndAttachCompshareDisk",
        params,
        success=f"Created and attached disk {name}",
    )


@disk_app.command("attach", help="Attach an existing disk to an instance.")
def attach_disk(
    ctx: typer.Context,
    disk: str,
    instance: str = typer.Option(..., "--instance"),
    disk_type: Optional[str] = typer.Option(None, "--type"),
) -> None:
    params = request(ctx, zone=True)
    params.update(compact({"UHostId": instance, "UDiskId": disk, "DataDiskType": disk_type}))
    invoke(runtime(ctx), "AttachCompshareDisk", params, success=f"Attached {disk} to {instance}")


@disk_app.command("detach", help="Detach a disk from an instance.")
def detach_disk(
    ctx: typer.Context,
    disk: str,
    instance: str = typer.Option(..., "--instance"),
    device: str = typer.Option(..., help="Device path, for example /dev/vdb."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Detach disk {disk} from {instance}? Ensure it is unmounted first.", yes)
    params = request(ctx)
    params.update(
        {
            "Zone": runtime(ctx).zone,
            "UHostId": instance,
            "UDiskId": disk,
            "Device": device,
        }
    )
    invoke(runtime(ctx), "DetachCompshareDisk", params, success=f"Detached disk {disk}")


@disk_app.command("price", help="Query a disk expansion price.")
def disk_price(
    ctx: typer.Context,
    disk: str,
    instance: str = typer.Option(..., "--instance"),
    size: str = typer.Option(...),
    backup: Optional[str] = typer.Option(None),
) -> None:
    params = request(ctx, zone=True)
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
    invoke(runtime(ctx), "GetCompShareAttachedDiskUpgradePrice", params)


@disk_app.command("resize", help="Resize a disk.")
def resize_disk(
    ctx: typer.Context,
    disk: str,
    size: str = typer.Option(...),
    instance: Optional[str] = typer.Option(None, "--instance"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Resize disk {disk} to {size}? Disks cannot be shrunk.", yes)
    params = request(ctx, zone=True)
    params.update(compact({"UDiskId": disk, "UHostId": instance, "Size": disk_gib(size)}))
    invoke(runtime(ctx), "ResizeCompShareDisk", params, success=f"Resized disk {disk}")


@disk_app.command("delete", help="Permanently delete a disk.")
def delete_disk(
    ctx: typer.Context,
    disk: str,
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Permanently delete disk {disk} and all its data?", yes)
    params = request(ctx, zone=True)
    params["UDiskId"] = disk
    invoke(runtime(ctx), "DeleteCompshareDisk", params, success=f"Deleted disk {disk}")


@us3_app.command("attach", help="Attach US3 object storage to an instance.")
def attach_us3(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance"),
) -> None:
    params = request(ctx, zone=True)
    params["UHostId"] = instance
    invoke(runtime(ctx), "AttachUS3", params, success=f"Attached US3 to {instance}")
