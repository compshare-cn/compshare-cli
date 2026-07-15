from __future__ import annotations

import shlex
import subprocess
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar

import typer

from compshare_cli.api import call, invoke
from compshare_cli.commands.common import confirm, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact, disk_gib, encode_password, memory_mib, timestamp
from compshare_cli.runtime import Runtime

app = typer.Typer(help="Manage GPU instances.", no_args_is_help=True)
ports_app = typer.Typer(help="Manage container port mappings.", no_args_is_help=True)
schedule_app = typer.Typer(help="Manage scheduled shutdowns.", no_args_is_help=True)
software_app = typer.Typer(help="Discover software exposed by instances.", no_args_is_help=True)
app.add_typer(ports_app, name="ports")
app.add_typer(schedule_app, name="schedule")
app.add_typer(software_app, name="software")

INSTANCE_COLUMNS = (
    ("UHostId", "ID"),
    ("Name", "NAME"),
    ("State", "STATE"),
    ("GpuType", "GPU"),
    ("GPU", "COUNT"),
    ("CPU", "CPU"),
    ("MemoryDisplay", "MEMORY"),
    ("Zone", "ZONE"),
    ("ChargeType", "CHARGE"),
    ("InstancePrice", "PRICE/H"),
)

Choice = TypeVar("Choice")


def _instance_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for raw in response.get("UHostSet", []):
        row = dict(raw)
        memory = row.get("Memory")
        row["MemoryDisplay"] = f"{memory // 1024}GiB" if isinstance(memory, int) else memory
        yield row


def _search_rows(
    response: Dict[str, Any],
    inventory: Optional[Dict[str, Dict[tuple, bool]]] = None,
    available_only: bool = False,
) -> Iterable[Dict[str, Any]]:
    inventory = inventory or {}
    for machine in response.get("AvailableInstanceTypes", []):
        gpu_memory = machine.get("GraphicsMemory", {}).get("Value")
        for size in machine.get("MachineSizes", []):
            for collection in size.get("Collection", []):
                for memory in collection.get("Memory", []):
                    stock = inventory.get(machine.get("Name"), {}).get(
                        (size.get("Gpu"), collection.get("Cpu"), memory)
                    )
                    if available_only and stock is not True:
                        continue
                    yield {
                        "GpuType": machine.get("Name"),
                        "GPU": size.get("Gpu"),
                        "CPU": collection.get("Cpu"),
                        "Memory": f"{memory}GiB",
                        "VRAM": f"{gpu_memory}GiB" if gpu_memory else None,
                        "Zone": machine.get("Zone"),
                        "Stock": stock,
                        "Platforms": collection.get("MinimalCpuPlatform", []),
                    }


def _disk_list(
    boot_disk: str,
    boot_type: str,
    data_disks: Optional[List[str]],
) -> List[Dict[str, Any]]:
    disks: List[Dict[str, Any]] = [{"IsBoot": True, "Type": boot_type, "Size": disk_gib(boot_disk)}]
    for specification in data_disks or []:
        parts = specification.split(":", 1)
        size = disk_gib(parts[0])
        disk_type = parts[1] if len(parts) == 2 else boot_type
        disks.append({"IsBoot": False, "Type": disk_type, "Size": size})
    return disks


def _volume_list(volumes: Optional[List[str]]) -> Optional[List[Dict[str, Any]]]:
    if not volumes:
        return None
    result: List[Dict[str, Any]] = []
    for specification in volumes:
        parts = specification.split(":", 1)
        size = disk_gib(parts[0])
        volume_type = parts[1] if len(parts) == 2 else "UDisk"
        result.append({"Type": volume_type, "Size": size})
    return result


def _choose(
    title: str,
    choices: Sequence[Choice],
    label: Callable[[Choice], str],
    *,
    default: int = 1,
) -> Choice:
    if not choices:
        raise UsageError(f"{title}: 没有可选项")
    typer.echo(f"\n{title}")
    for index, choice in enumerate(choices, start=1):
        typer.echo(f"  {index}. {label(choice)}")
    if len(choices) == 1:
        typer.echo("  Automatically selected the only option.")
        return choices[0]
    while True:
        selected = typer.prompt("Select", default=default, type=int)
        if 1 <= selected <= len(choices):
            return choices[selected - 1]
        typer.echo(f"Please enter a number from 1 to {len(choices)}.", err=True)


def _create_location(
    state: Runtime,
    zone: Optional[str],
    *,
    interactive: bool,
) -> Tuple[str, str]:
    selected_zone = zone or state.zone
    selected_region = state.region
    if not interactive or zone is not None:
        return selected_region, selected_zone

    response = call(
        state,
        "DescribeCompShareSupportZone",
        {"Region": state.region},
    )
    zones = response.get("ZoneInfo", [])
    if not zones:
        return selected_region, selected_zone
    default = next(
        (index for index, item in enumerate(zones, start=1) if item.get("Zone") == selected_zone),
        1,
    )
    selected = _choose(
        "Availability zone",
        zones,
        lambda item: (
            f"{item.get('Describe') or item.get('Zone')} "
            f"({item.get('Region')} / {item.get('Zone')})"
        ),
        default=default,
    )
    return selected.get("Region") or selected_region, selected.get("Zone") or selected_zone


def _create_gpu(
    state: Runtime,
    region: str,
    zone: str,
    gpu: Optional[str],
) -> str:
    if gpu is not None:
        return gpu
    response = call(
        state,
        "DescribeAvailableCompShareInstanceTypes",
        {"Region": region, "Zone": zone, "InstanceType": "uhost"},
    )
    machines = response.get("AvailableInstanceTypes", [])

    def label(machine: Dict[str, Any]) -> str:
        memory = machine.get("GraphicsMemory", {}).get("Value")
        suffix = f" · {memory}GiB VRAM" if memory else ""
        return f"{machine.get('Name')}{suffix}"

    selected = _choose("GPU type", machines, label)
    value = selected.get("Name")
    if not value:
        raise UsageError("机型接口返回了无名称的 GPU")
    return str(value)


def _create_images(
    state: Runtime,
    region: str,
    zone: str,
    source: Optional[str],
) -> List[Dict[str, Any]]:
    sources = ["platform", "custom", "community", "shared"]
    selected_source = (
        source.lower()
        if source
        else _choose(
            "Image source",
            sources,
            lambda value: value,
        )
    )
    mapping = {
        "platform": "DescribeCompShareImages",
        "custom": "DescribeCompShareCustomImages",
        "community": "DescribeCommunityImages",
        "shared": "DescribeCompShareSharingImages",
    }
    if selected_source not in mapping:
        raise UsageError("--image-source 必须是 platform、custom、community 或 shared")
    params: Dict[str, Any] = {"Region": region, "Limit": 100, "Offset": 0}
    if selected_source == "platform":
        params["Zone"] = zone
    response = call(state, mapping[selected_source], params)
    if selected_source == "community":
        images = []
        for group in response.get("CompshareImageGroup", []):
            for raw in group.get("Data", []):
                image = dict(raw)
                image.setdefault("Name", group.get("ImageName"))
                images.append(image)
    else:
        images = list(response.get("ImageSet", []))
    return [
        image
        for image in images
        if image.get("CompShareImageId") and image.get("Status", "Available") == "Available"
    ]


def _create_image(
    state: Runtime,
    region: str,
    zone: str,
    image: Optional[str],
    source: Optional[str],
) -> str:
    if image is not None:
        return image
    images = _create_images(state, region, zone, source)
    if len(images) > 1:
        query = typer.prompt(
            "Filter images by name or ID (blank shows all)",
            default="",
            show_default=False,
        ).strip()
        if query:
            normalized = query.casefold()
            images = [
                item
                for item in images
                if normalized in str(item.get("Name", "")).casefold()
                or normalized in str(item.get("CompShareImageId", "")).casefold()
            ]
    if len(images) > 50:
        raise UsageError("匹配到超过 50 个镜像，请输入更具体的筛选词")

    def label(item: Dict[str, Any]) -> str:
        author = f" · {item.get('Author')}" if item.get("Author") else ""
        return f"{item.get('Name') or 'Unnamed'}{author} · {item.get('CompShareImageId')}"

    selected = _choose("Image", images, label)
    return str(selected["CompShareImageId"])


def _create_charge(charge: Optional[str]) -> str:
    if charge is not None:
        return charge
    return _choose(
        "Billing type",
        ["Postpay", "Spot", "Day", "Month"],
        lambda value: value,
    )


@app.command("search")
def search(
    ctx: typer.Context,
    gpu: Optional[List[str]] = typer.Option(None, "--gpu", help="GPU type; repeatable."),
    spot: bool = typer.Option(False, "--spot", help="Search interruptible instances."),
    image: Optional[str] = typer.Option(
        None,
        "--image",
        help="Image ID. When set, check real inventory for every matched GPU type.",
    ),
    available: bool = typer.Option(False, "--available", help="Show only in-stock specs."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
    platform: str = typer.Option("Auto", "--platform", help="CPU platform for stock checks."),
    charge: Optional[str] = typer.Option(None, "--charge", help="Billing type for stock checks."),
    disk: str = typer.Option("100GiB", "--disk", help="Boot disk size for stock checks."),
    disk_type: str = typer.Option("CLOUD_SSD", "--disk-type"),
) -> None:
    """Search legal specifications and, with --image, real inventory."""
    if available and image is None:
        raise UsageError("--available 需要同时指定 --image，库存必须按镜像和磁盘组合检查")
    state = runtime(ctx)
    params = request(ctx)
    params.update(
        compact(
            {
                "Zone": zone or state.zone,
                "MachineTypes": gpu,
                "InstanceType": "spot" if spot else "uhost",
            }
        )
    )
    legal = call(state, "DescribeAvailableCompShareInstanceTypes", params)
    inventory: Dict[str, Dict[tuple, bool]] = {}
    inventory_response: Dict[str, List[Dict[str, Any]]] = {}
    if image is not None:
        machine_types = {
            machine.get("Name")
            for machine in legal.get("AvailableInstanceTypes", [])
            if machine.get("Name")
        }
        for machine_type in sorted(machine_types):
            capacity_params = request(ctx)
            capacity_params.update(
                {
                    "Zone": zone or state.zone,
                    "GpuType": machine_type,
                    "MachineType": "G",
                    "MinimalCpuPlatform": platform,
                    "CompShareImageId": image,
                    "ChargeType": charge or ("Spot" if spot else "Postpay"),
                    "Disks": [{"IsBoot": True, "Type": disk_type, "Size": disk_gib(disk)}],
                }
            )
            capacity = call(state, "CheckCompShareResourceCapacity", capacity_params)
            inventory_response[machine_type] = capacity.get("Specs", [])
            inventory[machine_type] = {
                (spec.get("Gpu"), spec.get("Cpu"), spec.get("Mem")): bool(
                    spec.get("ResourceEnough")
                )
                for spec in capacity.get("Specs", [])
            }

    response = dict(legal)
    if image is not None:
        response["Inventory"] = inventory_response
    Renderer(state.json_output).data(
        response,
        rows=_search_rows(legal, inventory, available),
        columns=(
            ("GpuType", "GPU"),
            ("GPU", "COUNT"),
            ("VRAM", "VRAM"),
            ("CPU", "CPU"),
            ("Memory", "MEMORY"),
            ("Zone", "ZONE"),
            ("Stock", "IN STOCK"),
            ("Platforms", "CPU PLATFORM"),
        ),
    )


@app.command("zones")
def zones(ctx: typer.Context) -> None:
    """List supported regions and availability zones."""
    invoke(
        runtime(ctx),
        "DescribeCompShareSupportZone",
        request(ctx),
        list_key="ZoneInfo",
        columns=(("Region", "REGION"), ("Zone", "ZONE"), ("Describe", "NAME")),
    )


@app.command("families")
def families(ctx: typer.Context) -> None:
    """List GPU machine families."""
    invoke(
        runtime(ctx),
        "DescribeCompShareMachineTypeFamilies",
        request(ctx),
        list_key="MachineTypes",
        columns=(("Name", "NAME"), ("Description", "DESCRIPTION")),
    )


@app.command("list")
def list_instances(
    ctx: typer.Context,
    ids: Optional[List[str]] = typer.Option(None, "--id", help="Instance ID; repeatable."),
    zone: Optional[str] = typer.Option(None, "--zone"),
    limit: int = typer.Option(20, min=1, max=100),
    offset: int = typer.Option(0, min=0),
    tag: Optional[str] = typer.Option(None),
    vpc: Optional[str] = typer.Option(None, "--vpc"),
    subnet: Optional[str] = typer.Option(None, "--subnet"),
    disk: Optional[str] = typer.Option(None, "--disk", help="Filter hosts compatible with a disk."),
    project_id: Optional[str] = typer.Option(
        None,
        "--project-id",
        help="Project ID for this request.",
    ),
    without_gpu: bool = typer.Option(False, "--without-gpu"),
) -> None:
    """List instances."""
    params = request(ctx)
    params.update(
        compact(
            {
                "Zone": zone,
                "ProjectId": project_id,
                "UHostIds": ids,
                "Limit": limit,
                "Offset": offset,
                "Tag": tag,
                "VPCId": vpc,
                "SubnetId": subnet,
                "UDiskIdForAttachment": disk,
                "WithoutGpu": without_gpu if without_gpu else None,
            }
        )
    )
    invoke(
        runtime(ctx),
        "DescribeCompShareInstance",
        params,
        row_builder=_instance_rows,
        columns=INSTANCE_COLUMNS,
    )


@app.command("show")
def show(ctx: typer.Context, instance: str = typer.Argument(..., help="Instance ID.")) -> None:
    """Show full instance details."""
    params = request(ctx)
    params["UHostIds"] = [instance]
    invoke(runtime(ctx), "DescribeCompShareInstance", params)


@app.command("create")
def create(
    ctx: typer.Context,
    gpu: Optional[str] = typer.Option(None, "--gpu", help="GPU type, for example 4090."),
    count: Optional[int] = typer.Option(None, "--count", min=1, help="GPU count."),
    cpu: Optional[int] = typer.Option(None, "--cpu", min=1),
    memory: Optional[str] = typer.Option(None, "--memory", help="Memory, for example 64GiB."),
    image: Optional[str] = typer.Option(None, "--image", help="CompShare image ID."),
    image_source: Optional[str] = typer.Option(
        None,
        "--image-source",
        help="Image source: platform, custom, community or shared.",
    ),
    zone: Optional[str] = typer.Option(
        None,
        "--zone",
        help="Availability zone for this request.",
    ),
    boot_disk: Optional[str] = typer.Option(None, "--disk", help="Boot disk size."),
    boot_type: Optional[str] = typer.Option(None, "--disk-type", help="Boot disk type."),
    data_disk: Optional[List[str]] = typer.Option(
        None,
        "--data-disk",
        help="Data disk as SIZE[:TYPE]; repeatable.",
    ),
    charge: Optional[str] = typer.Option(None, "--charge", help="Billing type."),
    quantity: int = typer.Option(1, min=1),
    name: Optional[str] = typer.Option(None),
    platform: str = typer.Option("Auto", "--platform"),
    remark: Optional[str] = typer.Option(None),
    firewall: Optional[str] = typer.Option(None, "--firewall"),
    max_count: int = typer.Option(1, "--max-count", min=1),
    us3: bool = typer.Option(False, "--us3"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Create instances interactively, or use explicit options for automation."""
    state = runtime(ctx)
    interactive = any(value is None for value in (gpu, count, cpu, memory, image))
    if interactive and state.json_output:
        raise UsageError(
            "--json 模式不会启动交互向导，请同时指定 --gpu、--count、--cpu、--memory 和 --image"
        )

    region, selected_zone = _create_location(state, zone, interactive=interactive)
    resolved_gpu = _create_gpu(state, region, selected_zone, gpu)
    resolved_image = _create_image(
        state,
        region,
        selected_zone,
        image,
        image_source,
    )
    resolved_charge = _create_charge(charge) if interactive else charge or "Postpay"
    resolved_boot_disk = boot_disk
    resolved_boot_type = boot_type
    if interactive:
        resolved_boot_disk = resolved_boot_disk or typer.prompt(
            "Boot disk size",
            default="100GiB",
        )
        resolved_boot_type = resolved_boot_type or typer.prompt(
            "Boot disk type",
            default="CLOUD_SSD",
        )
    else:
        resolved_boot_disk = resolved_boot_disk or "100GiB"
        resolved_boot_type = resolved_boot_type or "CLOUD_SSD"

    disks = _disk_list(resolved_boot_disk, resolved_boot_type, data_disk)
    common = {"Region": region, "Zone": selected_zone}
    capacity_params = dict(common)
    capacity_params.update(
        {
            "GpuType": resolved_gpu,
            "MachineType": "G",
            "MinimalCpuPlatform": platform,
            "CompShareImageId": resolved_image,
            "ChargeType": resolved_charge,
            "Disks": disks,
        }
    )
    capacity = call(state, "CheckCompShareResourceCapacity", capacity_params)
    requested_memory = memory_mib(memory) // 1024 if memory is not None else None
    matching = [
        spec
        for spec in capacity.get("Specs", [])
        if spec.get("ResourceEnough")
        and (count is None or spec.get("Gpu") == count)
        and (cpu is None or spec.get("Cpu") == cpu)
        and (requested_memory is None or spec.get("Mem") == requested_memory)
    ]
    if not matching:
        Renderer(state.json_output).error(
            "所选 GPU、CPU、内存、镜像、计费方式和磁盘组合当前无可用资源",
            details={"capacity": capacity},
        )
        raise typer.Exit(2)

    selected_spec = matching[0]
    if interactive and any(value is None for value in (count, cpu, memory)):
        selected_spec = _choose(
            "Available specification",
            matching,
            lambda spec: (
                f"GPU ×{spec.get('Gpu')} · {spec.get('Cpu')} CPU · {spec.get('Mem')}GiB memory"
            ),
        )
    resolved_count = int(count if count is not None else selected_spec["Gpu"])
    resolved_cpu = int(cpu if cpu is not None else selected_spec["Cpu"])
    resolved_memory_gib = int(
        requested_memory if requested_memory is not None else selected_spec["Mem"]
    )
    memory_mb = resolved_memory_gib * 1024

    price_params = dict(common)
    price_params.update(
        {
            "GpuType": resolved_gpu,
            "Gpu": resolved_count,
            "Cpu": resolved_cpu,
            "Memory": memory_mb,
            "ChargeType": resolved_charge,
            "Disks": disks,
            "CompShareImageId": resolved_image,
            "Quantity": quantity,
        }
    )
    price = call(state, "GetCompShareInstancePrice", price_params)
    price_details = price.get("PriceDetails", [])
    amount = None
    if price_details:
        values = [
            price_details[0].get(key)
            for key in ("Instance", "Disks", "SystemDisks", "CompShareImage")
        ]
        numbers = [value for value in values if isinstance(value, (int, float))]
        amount = sum(numbers) if numbers else None
    price_text = "unknown" if amount is None else str(round(amount * max_count, 4))
    confirm(
        f"Create {max_count} instance(s) in {selected_zone}: {resolved_gpu}×{resolved_count}, "
        f"{resolved_cpu} CPU, {resolved_memory_gib}GiB memory, image={resolved_image}, "
        f"disk={resolved_boot_disk}:{resolved_boot_type}, charge={resolved_charge}, "
        f"API quote={price_text}?",
        yes,
    )

    create_params = dict(common)
    create_params.update(
        compact(
            {
                "GpuType": resolved_gpu,
                "GPU": resolved_count,
                "CPU": resolved_cpu,
                "Memory": memory_mb,
                "MachineType": "G",
                "MinimalCpuPlatform": platform,
                "CompShareImageId": resolved_image,
                "Disks": disks,
                "ChargeType": resolved_charge,
                "Quantity": quantity,
                "Name": name,
                "Remark": remark,
                "SecurityGroupId": firewall,
                "MaxCount": max_count,
                "EnableUS3": us3 if us3 else None,
            }
        )
    )
    created = call(state, "CreateCompShareInstance", create_params)
    result = {
        "selection": {
            "Region": region,
            "Zone": selected_zone,
            "GpuType": resolved_gpu,
            "GPU": resolved_count,
            "CPU": resolved_cpu,
            "Memory": memory_mb,
            "CompShareImageId": resolved_image,
            "Disks": disks,
            "ChargeType": resolved_charge,
            "MaxCount": max_count,
        },
        "capacity": selected_spec,
        "price": price,
        "instance": created,
    }
    Renderer(state.json_output).data(result)


def _lifecycle(
    ctx: typer.Context,
    action: str,
    instance: str,
    message: str,
    *,
    yes: bool,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    confirm(message, yes)
    params = request(ctx, zone=True)
    params["UHostId"] = instance
    params.update(extra or {})
    invoke(runtime(ctx), action, params, success=message.rstrip("?"))


@app.command("start", help="Start an instance.")
def start(
    ctx: typer.Context,
    instance: str,
    without_gpu: Optional[str] = typer.Option(None, "--without-gpu", help="A or B."),
) -> None:
    params = request(ctx, zone=True)
    params.update(compact({"UHostId": instance, "WithoutGpuSpec": without_gpu}))
    invoke(runtime(ctx), "StartCompShareInstance", params, success=f"Started {instance}")


@app.command("stop", help="Stop an instance.")
def stop(ctx: typer.Context, instance: str, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    _lifecycle(ctx, "StopCompShareInstance", instance, f"Stop instance {instance}?", yes=yes)


@app.command("reboot", help="Reboot an instance.")
def reboot(
    ctx: typer.Context,
    instance: str,
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _lifecycle(ctx, "RebootCompShareInstance", instance, f"Reboot instance {instance}?", yes=yes)


@app.command("delete", help="Permanently delete an instance.")
def delete(
    ctx: typer.Context,
    instance: str,
    release_disk: bool = typer.Option(False, "--release-disk"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    suffix = " and its data disks" if release_disk else ""
    _lifecycle(
        ctx,
        "TerminateCompShareInstance",
        instance,
        f"Permanently delete instance {instance}{suffix}?",
        yes=yes,
        extra={"ReleaseUDisk": release_disk},
    )


@app.command("rename", help="Rename an instance.")
def rename(ctx: typer.Context, instance: str, name: str) -> None:
    params = request(ctx)
    params.update({"Zone": runtime(ctx).zone, "UHostId": instance, "Name": name})
    invoke(runtime(ctx), "ModifyCompShareInstanceName", params, success=f"Renamed {instance}")


@app.command("password")
def password(
    ctx: typer.Context,
    instance: str,
    value: Optional[str] = typer.Option(None, "--password", hidden=True),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Reset an instance password."""
    secret = value or typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    _lifecycle(
        ctx,
        "ResetCompShareInstancePassword",
        instance,
        f"Reset password for instance {instance}?",
        yes=yes,
        extra={"Password": encode_password(secret)},
    )


@app.command("reinstall", help="Reinstall an instance from an image.")
def reinstall(
    ctx: typer.Context,
    instance: str,
    image: str = typer.Option(..., "--image"),
    password: Optional[str] = typer.Option(None, "--password", hidden=True),
    coupon: Optional[str] = typer.Option(None, "--coupon"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    extra = compact(
        {
            "CompShareImageId": image,
            "Password": encode_password(password) if password else None,
            "CouponId": coupon,
        }
    )
    _lifecycle(
        ctx,
        "ReinstallCompShareInstance",
        instance,
        f"Reinstall instance {instance} from image {image}? All system disk data will be lost.",
        yes=yes,
        extra=extra,
    )


@app.command("resize", help="Change instance CPU, memory, GPU or disk size.")
def resize(
    ctx: typer.Context,
    instance: str,
    cpu: Optional[int] = typer.Option(None, min=1),
    memory: Optional[str] = typer.Option(None),
    gpu: Optional[int] = typer.Option(None, min=0),
    without_gpu: Optional[str] = typer.Option(None, "--without-gpu"),
    disk: Optional[str] = typer.Option(None, "--disk"),
    disk_size: Optional[str] = typer.Option(None, "--disk-size"),
    coupon: Optional[str] = typer.Option(None, "--coupon"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    compute_values = (cpu, memory, gpu)
    compute_resize = any(value is not None for value in compute_values) or without_gpu is not None
    disk_resize = disk is not None or disk_size is not None
    if not compute_resize and not disk_resize:
        raise UsageError("至少指定 CPU、memory、GPU、without-gpu 或 disk-size 中的一项")
    if (disk is None) != (disk_size is None):
        raise UsageError("--disk 和 --disk-size 必须同时使用")
    if compute_resize and disk_resize:
        raise UsageError("计算规格调整和磁盘扩容不能在同一次请求中进行")
    if without_gpu is not None and any(value is not None for value in compute_values):
        raise UsageError("--without-gpu 不能与 --cpu、--memory 或 --gpu 同时使用")
    if (
        without_gpu is None
        and compute_resize
        and not all(value is not None for value in compute_values)
    ):
        raise UsageError("调整计算规格时必须同时指定 --cpu、--memory 和 --gpu")
    params = compact(
        {
            "Cpu": cpu,
            "Memory": memory_mib(memory) if memory else None,
            "Gpu": gpu,
            "WithoutGpuSpec": without_gpu,
            "DiskId": disk,
            "DiskSpace": disk_gib(disk_size) if disk_size else None,
            "CouponId": coupon,
        }
    )
    _lifecycle(
        ctx,
        "ResizeCompShareInstance",
        instance,
        f"Resize instance {instance}?",
        yes=yes,
        extra=params,
    )


@app.command("price", help="Query a new instance price.")
def price(
    ctx: typer.Context,
    gpu: str = typer.Option(..., "--gpu"),
    count: int = typer.Option(1, "--count", min=1),
    cpu: int = typer.Option(..., min=1),
    memory: str = typer.Option(...),
    charge: Optional[str] = typer.Option(None),
    disk: str = typer.Option("100GiB"),
    disk_type: str = typer.Option("CLOUD_SSD", "--disk-type"),
    volume: Optional[List[str]] = typer.Option(
        None,
        "--volume",
        help="Shared storage as SIZE[:TYPE]; repeatable.",
    ),
    image: Optional[str] = typer.Option(None),
    quantity: int = typer.Option(1, min=1),
) -> None:
    params = request(ctx, zone=True)
    params.update(
        compact(
            {
                "GpuType": gpu,
                "Gpu": count,
                "Cpu": cpu,
                "Memory": memory_mib(memory),
                "ChargeType": charge,
                "Disks": [{"IsBoot": True, "Type": disk_type, "Size": disk_gib(disk)}],
                "Volumes": _volume_list(volume),
                "CompShareImageId": image,
                "Quantity": quantity,
            }
        )
    )
    invoke(
        runtime(ctx),
        "GetCompShareInstancePrice",
        params,
        list_key="PriceDetails",
        columns=(
            ("ChargeType", "CHARGE"),
            ("Instance", "INSTANCE"),
            ("SystemDisks", "SYSTEM DISK"),
            ("Disks", "DATA DISKS"),
            ("CompShareImage", "IMAGE"),
        ),
    )


@app.command("upgrade-price", help="Query the price of an instance upgrade.")
def upgrade_price(
    ctx: typer.Context,
    instance: str,
    cpu: Optional[int] = typer.Option(None),
    memory: Optional[str] = typer.Option(None),
    gpu: Optional[int] = typer.Option(None),
) -> None:
    if cpu is None and memory is None and gpu is None:
        raise UsageError("至少指定 --cpu、--memory 或 --gpu 中的一项")
    params = request(ctx, zone=True)
    params.update(
        compact(
            {
                "UHostId": instance,
                "CPU": cpu,
                "Memory": memory_mib(memory) if memory else None,
                "GPU": gpu,
            }
        )
    )
    invoke(runtime(ctx), "GetCompShareInstanceUpgradePrice", params)


@app.command("billing", help="Query current instance pricing.")
def billing(
    ctx: typer.Context,
    gpu: str = typer.Option(..., "--gpu"),
    count: int = typer.Option(1, "--count"),
    cpu: int = typer.Option(...),
    memory: str = typer.Option(...),
    charge: Optional[str] = typer.Option(None),
) -> None:
    params = request(ctx, zone=True)
    params.update(
        compact(
            {
                "GpuType": gpu,
                "GPU": count,
                "CPU": cpu,
                "Memory": memory_mib(memory),
                "ChargeType": charge,
            }
        )
    )
    invoke(
        runtime(ctx),
        "GetCompShareInstanceUserPrice",
        params,
        list_key="PriceDetails",
        columns=(
            ("ChargeType", "CHARGE"),
            ("Instance", "INSTANCE"),
            ("SystemDisks", "SYSTEM DISK"),
            ("Disks", "DATA DISKS"),
            ("CompShareImage", "IMAGE"),
        ),
    )


@app.command("refund", help="Query instance refund amounts.")
def refund(ctx: typer.Context, instances: List[str] = typer.Argument(...)) -> None:
    params = request(ctx, zone=True)
    params["UHostIds"] = instances
    invoke(
        runtime(ctx),
        "GetCompShareRefundPrice",
        params,
        list_key="RefundPriceSet",
        columns=(
            ("UHostId", "INSTANCE"),
            ("Code", "CODE"),
            ("RefundPrice", "REFUND"),
            ("Message", "MESSAGE"),
        ),
    )


@app.command("monitor", help="Get instance monitoring data.")
def monitor(
    ctx: typer.Context,
    instances: Optional[List[str]] = typer.Argument(None),
) -> None:
    params = request(ctx)
    params.update(compact({"UHostIds": instances}))
    invoke(runtime(ctx), "GetCompShareInstanceMonitor", params)


@app.command("charge", help="Change an instance billing type.")
def charge(
    ctx: typer.Context,
    instance: str,
    destination: str = typer.Option(..., "--to", help="Month, Day, Dynamic or Postpay."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _lifecycle(
        ctx,
        "SwitchChargeType",
        instance,
        f"Change billing for {instance} to {destination}?",
        yes=yes,
        extra={"DestChargeType": destination},
    )


@app.command("network", help="Check network accelerator status.")
def network(ctx: typer.Context) -> None:
    invoke(runtime(ctx), "CheckCompShareNetOptimizer", request(ctx))


@app.command("models", help="List models in the model repository.")
def models(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None),
    tags: Optional[str] = typer.Option(None),
) -> None:
    params = request(ctx)
    params.update(compact({"name": name, "tags": tags}))
    invoke(
        runtime(ctx),
        "DescribeModelRepositoryModels",
        params,
        list_key="Models",
        columns=(
            ("Name", "NAME"),
            ("Path", "PATH"),
            ("Tag", "TAG"),
            ("Size", "SIZE"),
            ("CreateTime", "CREATED"),
        ),
    )


@ports_app.command("list", help="List supported software ports.")
def list_ports(ctx: typer.Context) -> None:
    invoke(
        runtime(ctx),
        "DescribeCompShareSoftwarePort",
        request(ctx),
        list_key="SoftwarePort",
        columns=(("Software", "SOFTWARE"), ("Port", "PORT")),
    )


@ports_app.command("update", help="Replace an instance's container port mappings.")
def update_ports(
    ctx: typer.Context,
    instance: str,
    http: Optional[List[int]] = typer.Option(None, "--http"),
    tcp: Optional[List[int]] = typer.Option(None, "--tcp"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    if http is None and tcp is None:
        raise UsageError("至少指定一个 --http 或 --tcp；传空列表表示清除需使用 API JSON")
    confirm(f"Replace port mappings for {instance}?", yes)
    params = request(ctx, zone=True)
    params.update(compact({"UHostId": instance, "HttpPorts": http, "TcpPorts": tcp}))
    invoke(runtime(ctx), "UpdateCompShareInstancePorts", params, success="Updated port mappings")


@schedule_app.command("set", help="Schedule an instance shutdown.")
def set_schedule(
    ctx: typer.Context,
    instance: str,
    at: str = typer.Option(..., "--at", help="Unix timestamp or ISO 8601 time."),
    project_id: str = typer.Option(..., "--project-id", help="Project ID for this request."),
) -> None:
    stop_time = timestamp(at)
    if stop_time < int(time.time()) + 300:
        raise UsageError("定时关机时间必须至少晚于当前时间 5 分钟")
    params = request(ctx, zone=True, project_id=project_id)
    params.update({"UHostId": instance, "SchedulerStopTime": stop_time})
    invoke(runtime(ctx), "UpdateCompShareStopScheduler", params, success="Scheduled shutdown")


@schedule_app.command("cancel", help="Cancel an instance scheduled shutdown.")
def cancel_schedule(
    ctx: typer.Context,
    instance: str,
    project_id: str = typer.Option(..., "--project-id", help="Project ID for this request."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Cancel scheduled shutdown for {instance}?", yes)
    params = request(ctx, project_id=project_id)
    params["UHostId"] = instance
    invoke(runtime(ctx), "DeleteCompShareStopScheduler", params, success="Cancelled shutdown")


@software_app.command("list", help="List supported instance software.")
def list_software(ctx: typer.Context) -> None:
    invoke(
        runtime(ctx),
        "DescribeCompShareSoftwarePort",
        request(ctx),
        list_key="SoftwarePort",
        columns=(("Software", "SOFTWARE"), ("Port", "PORT")),
    )


@software_app.command("url", help="Get an instance software access URL.")
def software_url(ctx: typer.Context, instance: str, software: str) -> None:
    params = request(ctx, zone=True)
    params.update({"UHostId": instance, "Software": software})
    invoke(runtime(ctx), "GetSoftwareURL", params)


@app.command("ssh", help="Open or print an instance SSH command.")
def ssh(
    ctx: typer.Context,
    instance: str,
    print_only: bool = typer.Option(False, "--print", help="Print instead of executing SSH."),
) -> None:
    params = request(ctx)
    params["UHostIds"] = [instance]
    response = call(runtime(ctx), "DescribeCompShareInstance", params)
    hosts = response.get("UHostSet", [])
    host = hosts[0] if hosts else {}
    command = host.get("SshLoginCommand")
    password = host.get("Password")
    if not command:
        raise UsageError(f"实例 {instance} 没有可用的 SSH 登录命令")
    if print_only or runtime(ctx).json_output:
        Renderer(runtime(ctx).json_output).data(
            {"instance": instance, "command": command, "password": password}
        )
        return
    if password:
        typer.echo(f"Password: {password}")
    else:
        typer.echo(
            f"Password was not returned by the API. Run `compshare instance password {instance}` "
            "to set one."
        )
    argv = shlex.split(command)
    raise typer.Exit(subprocess.call(argv))
