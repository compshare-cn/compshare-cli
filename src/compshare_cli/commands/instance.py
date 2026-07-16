from __future__ import annotations

import shlex
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar

import typer

from compshare_cli.api import call, call_captured, collect_pages, invoke
from compshare_cli.commands.common import confirm, confirm_details, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.location import locate_instance, region_from_zone, supported_regions
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact, disk_gib, encode_password, memory_mib, money, timestamp
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
    ("Region", "REGION"),
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
        raise UsageError(f"{tr(title)}: {tr('No selectable options')}")
    typer.echo(f"\n{tr(title)}")
    for index, choice in enumerate(choices, start=1):
        typer.echo(f"  {index}. {label(choice)}")
    if len(choices) == 1:
        typer.echo(f"  {tr('Automatically selected the only option.')}")
        return choices[0]
    while True:
        selected = typer.prompt(tr("Select"), default=default, type=int)
        if 1 <= selected <= len(choices):
            return choices[selected - 1]
        typer.echo(tr("Please enter a number from 1 to {count}.", count=len(choices)), err=True)


def _wait_enabled(state: Runtime, value: Optional[bool]) -> bool:
    if value is not None:
        return value
    return not state.json_output and sys.stdout.isatty()


def _wait_for_instance(
    state: Runtime,
    instance: str,
    *,
    region: str,
    desired: Optional[set[str]] = None,
    absent: bool = False,
    timeout: int = 600,
) -> Dict[str, Any]:
    started = time.monotonic()
    previous: Optional[str] = None
    while True:
        response, error = call_captured(
            state,
            "DescribeCompShareInstance",
            {"Region": region, "UHostIds": [instance]},
        )
        if error:
            raise UsageError(str(error["message"]))
        response = response or {}
        hosts = response.get("UHostSet", [])
        if absent and not hosts:
            return response
        current = str(hosts[0].get("State", "Unknown")) if hosts else "NotFound"
        if hosts and desired and current in desired:
            return response
        if (
            hosts
            and desired is None
            and current
            not in {
                "Initializing",
                "Pending",
                "Starting",
                "Stopping",
                "Rebooting",
                "Reinstalling",
                "Resizing",
            }
        ):
            return response
        if current != previous and not state.json_output:
            typer.echo(tr("Waiting for {instance}: {state}", instance=instance, state=current))
            previous = current
        if time.monotonic() - started >= timeout:
            raise UsageError(
                tr(
                    "Timed out after {timeout}s while waiting for {instance}.",
                    timeout=timeout,
                    instance=instance,
                )
            )
        time.sleep(3)


def _locate_instances(
    state: Runtime,
    instances: Sequence[str],
) -> Tuple[Dict[str, Tuple[str, str, Dict[str, Any]]], List[str]]:
    requested = list(dict.fromkeys(instances))
    if len(requested) == 1:
        try:
            region, zone, host = locate_instance(state, requested[0])
        except UsageError:
            return {}, requested
        return {requested[0]: (region, zone, host)}, []

    remaining = set(requested)
    found: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
    for region in supported_regions(state):
        if not remaining:
            break
        response = collect_pages(
            state,
            "DescribeCompShareInstance",
            {"Region": region, "UHostIds": list(remaining)},
            "UHostSet",
        )
        for raw in response.get("UHostSet", []):
            host = dict(raw)
            instance = str(host.get("UHostId") or "")
            if instance not in remaining:
                continue
            zone = str(host.get("Zone") or state.zone)
            found[instance] = (region, zone, host)
            remaining.remove(instance)
    return found, [instance for instance in requested if instance in remaining]


def _price_total(price: Dict[str, Any], count: int) -> Optional[Decimal]:
    details = price.get("PriceDetails", [])
    if not details:
        return None
    values = [details[0].get(key) for key in ("Instance", "Disks", "SystemDisks", "CompShareImage")]
    total = Decimal("0")
    found = False
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        try:
            total += Decimal(str(value))
            found = True
        except InvalidOperation:
            continue
    return total * count if found else None


def _project_id(state: Runtime, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    response = call(state, "GetProjectList", {})
    projects = response.get("ProjectSet", [])
    selected = next((item for item in projects if item.get("IsDefault")), None)
    selected = selected or (projects[0] if projects else None)
    if not selected or not selected.get("ProjectId"):
        raise UsageError(
            tr("No project was returned by GetProjectList; pass --project-id explicitly.")
        )
    return str(selected["ProjectId"])


def _create_location(
    state: Runtime,
    zone: Optional[str],
    *,
    interactive: bool,
) -> Tuple[str, str]:
    selected_zone = zone or state.zone
    selected_region = region_from_zone(selected_zone)
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
        raise UsageError(tr("The machine type API returned an unnamed GPU."))
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
        raise UsageError(tr("--image-source must be platform, custom, community, or shared."))
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
            tr("Filter images by name or ID (blank shows all)"),
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
        raise UsageError(tr("More than 50 images matched; use a more specific filter."))

    def label(item: Dict[str, Any]) -> str:
        author = f" · {item.get('Author')}" if item.get("Author") else ""
        return f"{item.get('Name') or tr('Unnamed')}{author} · {item.get('CompShareImageId')}"

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
    disk_type: str = typer.Option(
        "CLOUD_SSD", "--disk-type", help="Boot disk type used for stock checks."
    ),
) -> None:
    """Search legal specifications and, with --image, real inventory."""
    if available and image is None:
        raise UsageError(
            tr("--available requires --image because inventory depends on the image and disks.")
        )
    state = runtime(ctx)
    selected_zone = zone or state.zone
    selected_region = region_from_zone(selected_zone)
    params = request(ctx, region_value=selected_region)
    params.update(
        compact(
            {
                "Zone": selected_zone,
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
            capacity_params = request(ctx, region_value=selected_region)
            capacity_params.update(
                {
                    "Zone": selected_zone,
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
    region: Optional[str] = typer.Option(None, "--region", help="Filter by region."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Filter by availability zone."),
    limit: int = typer.Option(20, min=1, max=100, help="Maximum number of results."),
    offset: int = typer.Option(0, min=0, help="Number of results to skip."),
    all_results: bool = typer.Option(False, "--all", help="Return all results."),
    tag: Optional[str] = typer.Option(None, help="Filter by instance tag."),
    vpc: Optional[str] = typer.Option(None, "--vpc", help="Filter by VPC ID."),
    subnet: Optional[str] = typer.Option(None, "--subnet", help="Filter by subnet ID."),
    disk: Optional[str] = typer.Option(None, "--disk", help="Filter hosts compatible with a disk."),
    project_id: Optional[str] = typer.Option(
        None,
        "--project-id",
        help="Project ID for this request.",
    ),
    without_gpu: bool = typer.Option(False, "--without-gpu", help="List no-GPU instances."),
    name: Optional[str] = typer.Option(None, "--name", help="Filter by instance name."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by instance state."),
    gpu: Optional[str] = typer.Option(None, "--gpu", help="Filter by GPU type."),
    billing: Optional[str] = typer.Option(None, "--billing", help="Filter by billing type."),
) -> None:
    """List instances."""
    state = runtime(ctx)
    selected_region = region_from_zone(zone) if zone else region
    params = request(ctx, region_value=selected_region)
    params.update(
        compact(
            {
                "Zone": zone,
                "ProjectId": project_id,
                "UHostIds": ids,
                "Tag": tag,
                "VPCId": vpc,
                "SubnetId": subnet,
                "UDiskIdForAttachment": disk,
                "WithoutGpu": without_gpu if without_gpu else None,
            }
        )
    )
    regions = [selected_region] if selected_region else supported_regions(state)
    response: Dict[str, Any] = {"UHostSet": [], "RegionSet": regions}
    for current_region in regions:
        current = collect_pages(
            state,
            "DescribeCompShareInstance",
            {**params, "Region": current_region},
            "UHostSet",
        )
        for host in current.get("UHostSet", []):
            item = dict(host)
            item.setdefault("Region", current_region)
            response["UHostSet"].append(item)
    response["TotalCount"] = len(response["UHostSet"])
    filters = {
        "Name": name.casefold() if name else None,
        "State": status.casefold() if status else None,
        "GpuType": gpu.casefold() if gpu else None,
        "ChargeType": billing.casefold() if billing else None,
    }
    filtered = []
    for host in response.get("UHostSet", []):
        if all(
            expected is None or expected in str(host.get(field, "")).casefold()
            for field, expected in filters.items()
        ):
            filtered.append(host)
    page = filtered[offset:] if all_results else filtered[offset : offset + limit]
    result = dict(response)
    result["UHostSet"] = page
    result["FilteredCount"] = len(filtered)
    result["ReturnedCount"] = len(page)
    result["Offset"] = offset
    result["Limit"] = None if all_results else limit
    Renderer(state.json_output).data(
        result,
        rows=_instance_rows(result),
        columns=INSTANCE_COLUMNS,
    )


@app.command("show")
def show(ctx: typer.Context, instance: str = typer.Argument(..., help="Instance ID.")) -> None:
    """Show full instance details."""
    state = runtime(ctx)
    region, zone, host = locate_instance(state, instance)
    response = {"UHostSet": [host], "ResolvedRegion": region, "ResolvedZone": zone}
    Renderer(state.json_output).details(
        "Instance details",
        [
            ("ID", host.get("UHostId")),
            ("NAME", host.get("Name")),
            ("STATE", host.get("State")),
            ("GPU", f"{host.get('GpuType', '-')} × {host.get('GPU', '-')}"),
            ("CPU", host.get("CPU")),
            (
                "MEMORY",
                f"{host.get('Memory', 0) // 1024}GiB"
                if isinstance(host.get("Memory"), int)
                else host.get("Memory"),
            ),
            ("REGION", region),
            ("ZONE", host.get("Zone")),
            ("CHARGE", host.get("ChargeType")),
            ("IMAGE", host.get("CompShareImageId") or host.get("ImageId")),
            ("Password", host.get("Password")),
            ("SSH", host.get("SshLoginCommand")),
            ("DATA DISKS", host.get("DiskSet") or host.get("UDiskSet")),
        ],
        response=response,
    )


@app.command("create")
def create(
    ctx: typer.Context,
    gpu: Optional[str] = typer.Option(None, "--gpu", help="GPU type, for example 4090."),
    count: Optional[int] = typer.Option(None, "--count", min=1, help="GPU count."),
    cpu: Optional[int] = typer.Option(None, "--cpu", min=1, help="CPU core count."),
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
    quantity: int = typer.Option(1, min=1, help="Billing duration for prepaid modes."),
    name: Optional[str] = typer.Option(None, help="Instance name."),
    platform: str = typer.Option("Auto", "--platform", help="Minimum CPU platform."),
    remark: Optional[str] = typer.Option(None, help="Instance remark."),
    firewall: Optional[str] = typer.Option(None, "--firewall", help="Security group ID."),
    max_count: int = typer.Option(1, "--max-count", min=1, help="Number of instances."),
    us3: bool = typer.Option(False, "--us3", help="Attach US3 during container creation."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and show the request without changing resources.",
    ),
    max_price: Optional[str] = typer.Option(
        None,
        "--max-price",
        help="Maximum total quoted price in CNY.",
    ),
    wait: Optional[bool] = typer.Option(
        None,
        "--wait/--no-wait",
        help="Wait for the operation to reach a stable state.",
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Create instances interactively, or use explicit options for automation."""
    state = runtime(ctx)
    interactive = any(value is None for value in (gpu, count, cpu, memory, image))
    if interactive and state.json_output:
        raise UsageError(
            tr(
                "JSON mode cannot start the interactive wizard; pass --gpu, --count, --cpu, "
                "--memory, and --image."
            )
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
            tr("Boot disk size"),
            default="100GiB",
        )
        resolved_boot_type = resolved_boot_type or typer.prompt(
            tr("Boot disk type"),
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
            tr(
                "No inventory is available for the selected GPU, CPU, memory, image, billing, "
                "and disk combination."
            ),
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
    amount = _price_total(price, max_count)
    price_text = "unknown" if amount is None else format(amount.normalize(), "f")
    price_limit = money(max_price) if max_price is not None else None
    if price_limit is not None and amount is None:
        raise UsageError(tr("The API did not return a price, so --max-price cannot be enforced."))
    if price_limit is not None and amount is not None and amount > price_limit:
        raise UsageError(
            tr(
                "Quoted price {price} CNY exceeds --max-price {maximum} CNY; "
                "no instance was created.",
                price=price_text,
                maximum=format(price_limit.normalize(), "f"),
            )
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
    selection = {
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
    }
    plan = {
        "dry_run": dry_run,
        "max_price": str(price_limit) if price_limit is not None else None,
        "selection": selection,
        "capacity": selected_spec,
        "price": price,
        "request": create_params,
    }
    if dry_run:
        Renderer(state.json_output).details(
            "Create plan",
            [
                ("ZONE", selected_zone),
                ("GPU", f"{resolved_gpu} × {resolved_count}"),
                ("CPU", resolved_cpu),
                ("MEMORY", f"{resolved_memory_gib}GiB"),
                ("IMAGE", resolved_image),
                ("SYSTEM DISK", f"{resolved_boot_disk}:{resolved_boot_type}"),
                ("CHARGE", resolved_charge),
                ("COUNT", max_count),
                ("PRICE", price_text),
            ],
            response=plan,
        )
        return
    confirm_details(
        state,
        "Create plan",
        [
            ("ZONE", selected_zone),
            ("GPU", f"{resolved_gpu} × {resolved_count}"),
            ("CPU", resolved_cpu),
            ("MEMORY", f"{resolved_memory_gib}GiB"),
            ("IMAGE", resolved_image),
            ("SYSTEM DISK", f"{resolved_boot_disk}:{resolved_boot_type}"),
            ("CHARGE", resolved_charge),
            ("COUNT", max_count),
            ("PRICE", price_text),
        ],
        "Confirm this operation?",
        yes,
    )
    created = call(state, "CreateCompShareInstance", create_params)
    result = {
        "selection": selection,
        "capacity": selected_spec,
        "price": price,
        "instance": created,
    }
    ids = created.get("UHostIds") or created.get("UHostId") or []
    if isinstance(ids, str):
        ids = [ids]
    if _wait_enabled(state, wait):
        result["final"] = [
            _wait_for_instance(state, item, region=region, timeout=timeout) for item in ids
        ]
    Renderer(state.json_output).details(
        "Operation completed",
        [
            ("INSTANCE", ids),
            ("Password", created.get("Password")),
            ("ZONE", selected_zone),
            ("GPU", f"{resolved_gpu} × {resolved_count}"),
            ("PRICE", price_text),
        ],
        response=result,
    )


def _lifecycle(
    ctx: typer.Context,
    action: str,
    instance: str,
    message: str,
    *,
    yes: bool,
    extra: Optional[Dict[str, Any]] = None,
    wait: Optional[bool] = None,
    timeout: int = 600,
    desired: Optional[set[str]] = None,
    absent: bool = False,
) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    confirm_details(
        state,
        "Operation plan",
        [("INSTANCE", instance), ("ACTION", tr(message.rstrip("?")))],
        "Confirm this operation?",
        yes,
    )
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params["UHostId"] = instance
    params.update(extra or {})
    submitted = call(state, action, params)
    result: Dict[str, Any] = {"operation": submitted}
    if _wait_enabled(state, wait):
        result["final"] = _wait_for_instance(
            state,
            instance,
            region=region,
            desired=desired,
            absent=absent,
            timeout=timeout,
        )
    Renderer(state.json_output).success(tr("Operation completed"), result)


def _render_batch(
    state: Runtime,
    action: str,
    succeeded: List[Dict[str, Any]],
    failed: List[Dict[str, Any]],
) -> None:
    payload = {
        "ok": not failed,
        "action": action,
        "succeeded": succeeded,
        "failed": failed,
    }
    rows = [
        {"UHostId": item["instance"], "Status": "Succeeded", "Message": ""} for item in succeeded
    ]
    rows.extend(
        {
            "UHostId": item["instance"],
            "Status": "Failed",
            "Message": item["error"].get("message"),
        }
        for item in failed
    )
    Renderer(state.json_output).data(
        payload,
        rows=rows,
        columns=(("UHostId", "INSTANCE"), ("Status", "STATUS"), ("Message", "MESSAGE")),
    )
    if failed:
        raise typer.Exit(1)


def _batch_lifecycle(
    ctx: typer.Context,
    action: str,
    instances: Sequence[str],
    message: str,
    *,
    yes: bool = True,
    confirm_operation: bool = False,
    extra: Optional[Dict[str, Any]] = None,
    wait: Optional[bool] = None,
    timeout: int = 600,
    desired: Optional[set[str]] = None,
    absent: bool = False,
) -> None:
    state = runtime(ctx)
    requested = list(dict.fromkeys(instances))
    locations, missing = _locate_instances(state, requested)
    if confirm_operation:
        confirm_details(
            state,
            "Operation plan",
            [("INSTANCE", requested), ("ACTION", tr(message.rstrip("?")))],
            "Confirm this operation?",
            yes,
        )

    succeeded: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = [
        {
            "instance": instance,
            "error": {
                "message": tr(
                    "Instance {instance} was not found in any supported region.",
                    instance=instance,
                )
            },
        }
        for instance in missing
    ]
    for instance in requested:
        location = locations.get(instance)
        if location is None:
            continue
        region, zone, _ = location
        params = request(ctx, zone=True, region_value=region, zone_value=zone)
        params.update({"UHostId": instance, **(extra or {})})
        submitted, error = call_captured(state, action, params)
        if error:
            failed.append({"instance": instance, "region": region, "zone": zone, "error": error})
            continue
        result: Dict[str, Any] = {
            "instance": instance,
            "region": region,
            "zone": zone,
            "operation": submitted or {},
        }
        if _wait_enabled(state, wait):
            try:
                result["final"] = _wait_for_instance(
                    state,
                    instance,
                    region=region,
                    desired=desired,
                    absent=absent,
                    timeout=timeout,
                )
            except UsageError as error:
                failed.append(
                    {
                        "instance": instance,
                        "region": region,
                        "zone": zone,
                        "operation": submitted or {},
                        "error": {"message": str(error), "phase": "wait"},
                    }
                )
                continue
        succeeded.append(result)
    _render_batch(state, action, succeeded, failed)


@app.command("start", help="Start one or more instances.")
def start(
    ctx: typer.Context,
    instances: List[str] = typer.Argument(..., help="Instance IDs."),
    without_gpu: Optional[str] = typer.Option(
        None, "--without-gpu", help="No-GPU specification: A or B."
    ),
    wait: Optional[bool] = typer.Option(
        None, "--wait/--no-wait", help="Wait for the operation to reach a stable state."
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
) -> None:
    _batch_lifecycle(
        ctx,
        "StartCompShareInstance",
        instances,
        "Start instance",
        extra=compact({"WithoutGpuSpec": without_gpu}),
        wait=wait,
        timeout=timeout,
        desired={"Running"},
    )


@app.command("stop", help="Stop one or more instances.")
def stop(
    ctx: typer.Context,
    instances: List[str] = typer.Argument(..., help="Instance IDs."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    wait: Optional[bool] = typer.Option(
        None, "--wait/--no-wait", help="Wait for the operation to reach a stable state."
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
) -> None:
    _batch_lifecycle(
        ctx,
        "StopCompShareInstance",
        instances,
        "Stop instance",
        yes=yes,
        confirm_operation=True,
        wait=wait,
        timeout=timeout,
        desired={"Stopped"},
    )


@app.command("reboot", help="Reboot one or more instances.")
def reboot(
    ctx: typer.Context,
    instances: List[str] = typer.Argument(..., help="Instance IDs."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    wait: Optional[bool] = typer.Option(
        None, "--wait/--no-wait", help="Wait for the operation to reach a stable state."
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
) -> None:
    _batch_lifecycle(
        ctx,
        "RebootCompShareInstance",
        instances,
        "Reboot instance",
        yes=yes,
        confirm_operation=True,
        wait=wait,
        timeout=timeout,
        desired={"Running"},
    )


@app.command("delete", help="Permanently delete one or more instances.")
def delete(
    ctx: typer.Context,
    instances: List[str] = typer.Argument(..., help="Instance IDs."),
    release_disk: bool = typer.Option(
        False, "--release-disk", help="Delete attached data disks with the instance."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    wait: Optional[bool] = typer.Option(
        None, "--wait/--no-wait", help="Wait for the operation to reach a stable state."
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
) -> None:
    _batch_lifecycle(
        ctx,
        "TerminateCompShareInstance",
        instances,
        "Permanently delete instance and attached data disks"
        if release_disk
        else "Permanently delete instance",
        yes=yes,
        confirm_operation=True,
        extra={"ReleaseUDisk": release_disk},
        wait=wait,
        timeout=timeout,
        absent=True,
    )


@app.command("wait", help="Wait for instances to reach a state.")
def wait_for_instances(
    ctx: typer.Context,
    instances: List[str] = typer.Argument(..., help="Instance IDs."),
    state: str = typer.Option("Running", "--state", help="Target instance state."),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
) -> None:
    runtime_state = runtime(ctx)
    requested = list(dict.fromkeys(instances))
    locations, missing = _locate_instances(runtime_state, requested)
    succeeded: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = [
        {
            "instance": instance,
            "error": {
                "message": tr(
                    "Instance {instance} was not found in any supported region.",
                    instance=instance,
                )
            },
        }
        for instance in missing
    ]
    for instance in requested:
        location = locations.get(instance)
        if location is None:
            continue
        region, zone, _ = location
        try:
            final = _wait_for_instance(
                runtime_state,
                instance,
                region=region,
                desired={state},
                timeout=timeout,
            )
        except UsageError as error:
            failed.append(
                {
                    "instance": instance,
                    "region": region,
                    "zone": zone,
                    "error": {"message": str(error)},
                }
            )
            continue
        succeeded.append({"instance": instance, "region": region, "zone": zone, "final": final})
    _render_batch(runtime_state, "wait", succeeded, failed)


@app.command("rename", help="Rename an instance.")
def rename(ctx: typer.Context, instance: str, name: str) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update({"UHostId": instance, "Name": name})
    invoke(
        state,
        "ModifyCompShareInstanceName",
        params,
        success=tr("Renamed {instance}", instance=instance),
    )


@app.command("password")
def password(
    ctx: typer.Context,
    instance: str,
    value: Optional[str] = typer.Option(None, "--password", hidden=True),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Reset an instance password."""
    secret = value or typer.prompt(tr("New password"), hide_input=True, confirmation_prompt=True)
    _lifecycle(
        ctx,
        "ResetCompShareInstancePassword",
        instance,
        "Reset instance password",
        yes=yes,
        extra={"Password": encode_password(secret)},
    )


@app.command("reinstall", help="Reinstall an instance from an image.")
def reinstall(
    ctx: typer.Context,
    instance: str,
    image: str = typer.Option(..., "--image", help="Replacement image ID."),
    password: Optional[str] = typer.Option(None, "--password", hidden=True),
    coupon: Optional[str] = typer.Option(None, "--coupon", help="Coupon ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    wait: Optional[bool] = typer.Option(
        None, "--wait/--no-wait", help="Wait for the operation to reach a stable state."
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
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
        "Reinstall instance; all system disk data will be lost",
        yes=yes,
        extra=extra,
        wait=wait,
        timeout=timeout,
    )


@app.command("resize", help="Change instance CPU, memory, GPU or disk size.")
def resize(
    ctx: typer.Context,
    instance: str,
    cpu: Optional[int] = typer.Option(None, min=1, help="Target CPU core count."),
    memory: Optional[str] = typer.Option(None, help="Target memory, for example 64GiB."),
    gpu: Optional[int] = typer.Option(None, min=0, help="Target GPU count."),
    without_gpu: Optional[str] = typer.Option(
        None, "--without-gpu", help="Target no-GPU specification: A or B."
    ),
    disk: Optional[str] = typer.Option(None, "--disk", help="Disk ID to resize."),
    disk_size: Optional[str] = typer.Option(
        None, "--disk-size", help="Target disk size, for example 200GiB."
    ),
    coupon: Optional[str] = typer.Option(None, "--coupon", help="Coupon ID."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and show the request without changing resources.",
    ),
    wait: Optional[bool] = typer.Option(
        None, "--wait/--no-wait", help="Wait for the operation to reach a stable state."
    ),
    timeout: int = typer.Option(600, "--timeout", min=1, help="Maximum wait time in seconds."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    compute_values = (cpu, memory, gpu)
    compute_resize = any(value is not None for value in compute_values) or without_gpu is not None
    disk_resize = disk is not None or disk_size is not None
    if not compute_resize and not disk_resize:
        raise UsageError(tr("Specify a compute target or both --disk and --disk-size."))
    if (disk is None) != (disk_size is None):
        raise UsageError(tr("--disk and --disk-size must be used together."))
    if compute_resize and disk_resize:
        raise UsageError(tr("Compute resizing and disk resizing must be separate operations."))
    if without_gpu is not None and any(value is not None for value in compute_values):
        raise UsageError(tr("--without-gpu cannot be combined with --cpu, --memory, or --gpu."))
    if (
        without_gpu is None
        and compute_resize
        and not all(value is not None for value in compute_values)
    ):
        raise UsageError(tr("Compute resizing requires --cpu, --memory, and --gpu together."))
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
    if dry_run:
        quote: Dict[str, Any] = {}
        if compute_resize and without_gpu is None:
            state = runtime(ctx)
            region, zone, _ = locate_instance(state, instance)
            quote_params = request(
                ctx,
                zone=True,
                region_value=region,
                zone_value=zone,
            )
            quote_params.update(
                {"UHostId": instance, "CPU": cpu, "Memory": memory_mib(memory or ""), "GPU": gpu}
            )
            quote = call(runtime(ctx), "GetCompShareInstanceUpgradePrice", quote_params)
        Renderer(runtime(ctx).json_output).details(
            "Operation plan",
            [("INSTANCE", instance), ("ACTION", "Resize"), ("REQUEST", params), ("PRICE", quote)],
            response={"dry_run": True, "instance": instance, "request": params, "price": quote},
        )
        return
    _lifecycle(
        ctx,
        "ResizeCompShareInstance",
        instance,
        "Resize instance",
        yes=yes,
        extra=params,
        wait=wait,
        timeout=timeout,
    )


@app.command("price", help="Query a new instance price.")
def price(
    ctx: typer.Context,
    gpu: str = typer.Option(..., "--gpu", help="GPU type."),
    count: int = typer.Option(1, "--count", min=1, help="GPU count."),
    cpu: int = typer.Option(..., min=1, help="CPU core count."),
    memory: str = typer.Option(..., help="Memory, for example 64GiB."),
    charge: Optional[str] = typer.Option(None, help="Billing type."),
    disk: str = typer.Option("100GiB", help="Boot disk size."),
    disk_type: str = typer.Option("CLOUD_SSD", "--disk-type", help="Boot disk type."),
    volume: Optional[List[str]] = typer.Option(
        None,
        "--volume",
        help="Shared storage as SIZE[:TYPE]; repeatable.",
    ),
    image: Optional[str] = typer.Option(None, help="Image ID for image pricing."),
    quantity: int = typer.Option(1, min=1, help="Billing duration for prepaid modes."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
) -> None:
    selected_zone = zone or runtime(ctx).zone
    params = request(ctx, zone=True, zone_value=selected_zone)
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


@app.command("upgrade-price", help="Query the price of an instance upgrade.", hidden=True)
@app.command("resize-price", help="Query the price of an instance upgrade.")
def upgrade_price(
    ctx: typer.Context,
    instance: str,
    cpu: Optional[int] = typer.Option(None, help="Target CPU core count."),
    memory: Optional[str] = typer.Option(None, help="Target memory, for example 64GiB."),
    gpu: Optional[int] = typer.Option(None, help="Target GPU count."),
) -> None:
    if cpu is None and memory is None and gpu is None:
        raise UsageError(tr("Specify at least one of --cpu, --memory, or --gpu."))
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
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
    invoke(state, "GetCompShareInstanceUpgradePrice", params)


@app.command("billing", help="Query current instance pricing.")
def billing(
    ctx: typer.Context,
    gpu: str = typer.Option(..., "--gpu", help="GPU type."),
    count: int = typer.Option(1, "--count", help="GPU count."),
    cpu: int = typer.Option(..., help="CPU core count."),
    memory: str = typer.Option(..., help="Memory, for example 64GiB."),
    charge: Optional[str] = typer.Option(None, help="Billing type."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
) -> None:
    selected_zone = zone or runtime(ctx).zone
    params = request(ctx, zone=True, zone_value=selected_zone)
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
    state = runtime(ctx)
    groups: Dict[Tuple[str, str], List[str]] = {}
    for instance in instances:
        region, zone, _ = locate_instance(state, instance)
        groups.setdefault((region, zone), []).append(instance)
    response: Dict[str, Any] = {"RefundPriceSet": []}
    for (region, zone), ids in groups.items():
        current = call(
            state,
            "GetCompShareRefundPrice",
            {"Region": region, "Zone": zone, "UHostIds": ids},
        )
        response["RefundPriceSet"].extend(current.get("RefundPriceSet", []))
    Renderer(state.json_output).data(
        response,
        rows=response["RefundPriceSet"],
        columns=(
            ("UHostId", "INSTANCE"),
            ("Code", "CODE"),
            ("RefundPrice", "REFUND"),
            ("Message", "MESSAGE"),
        ),
    )


@app.command(
    "monitor",
    help="Get instance monitoring data (currently unavailable in production).",
)
def monitor(
    ctx: typer.Context,
    instances: Optional[List[str]] = typer.Argument(None),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    state = runtime(ctx)
    if not region and instances:
        region, _, _ = locate_instance(state, instances[0])
    params = request(ctx, region_value=region)
    params.update(compact({"UHostIds": instances}))
    invoke(state, "GetCompShareInstanceMonitor", params)


@app.command("charge", help="Change an instance billing type.")
def charge(
    ctx: typer.Context,
    instance: str,
    destination: str = typer.Option(..., "--to", help="Month, Day, Dynamic or Postpay."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and show the request without changing resources.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if dry_run:
        Renderer(runtime(ctx).json_output).details(
            "Operation plan",
            [("INSTANCE", instance), ("CHARGE", destination)],
            response={"dry_run": True, "instance": instance, "destination": destination},
        )
        return
    _lifecycle(
        ctx,
        "SwitchChargeType",
        instance,
        "Change instance billing type",
        yes=yes,
        extra={"DestChargeType": destination},
    )


@app.command("network", help="Check network accelerator status.")
def network(
    ctx: typer.Context,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    invoke(
        runtime(ctx),
        "CheckCompShareNetOptimizer",
        request(ctx, region_value=region),
    )


@app.command("models", help="List models in the model repository.")
def models(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, help="Filter by model name."),
    tags: Optional[str] = typer.Option(None, help="Filter by model tags."),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    params = request(ctx, region_value=region)
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
def list_ports(
    ctx: typer.Context,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    invoke(
        runtime(ctx),
        "DescribeCompShareSoftwarePort",
        request(ctx, region_value=region),
        list_key="SoftwarePort",
        columns=(("Software", "SOFTWARE"), ("Port", "PORT")),
    )


@ports_app.command("update", help="Replace an instance's container port mappings.")
def update_ports(
    ctx: typer.Context,
    instance: str,
    http: Optional[List[int]] = typer.Option(
        None, "--http", help="Complete HTTP port list; repeatable."
    ),
    tcp: Optional[List[int]] = typer.Option(
        None, "--tcp", help="Complete TCP port list; repeatable."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if http is None and tcp is None:
        raise UsageError(tr("Specify at least one --http or --tcp port."))
    confirm(tr("Replace port mappings for {instance}?", instance=instance), yes)
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(compact({"UHostId": instance, "HttpPorts": http, "TcpPorts": tcp}))
    invoke(
        state,
        "UpdateCompShareInstancePorts",
        params,
        success=tr("Updated port mappings"),
    )


@schedule_app.command("set", help="Schedule an instance shutdown.")
def set_schedule(
    ctx: typer.Context,
    instance: str,
    at: str = typer.Option(..., "--at", help="Unix timestamp, ISO 8601, or relative time."),
    project_id: Optional[str] = typer.Option(
        None, "--project-id", help="Override the automatically detected project ID."
    ),
) -> None:
    stop_time = timestamp(at)
    if stop_time < int(time.time()) + 300:
        raise UsageError(tr("Scheduled shutdown must be at least five minutes from now."))
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(
        ctx,
        zone=True,
        project_id=_project_id(state, project_id),
        region_value=region,
        zone_value=zone,
    )
    params.update({"UHostId": instance, "SchedulerStopTime": stop_time})
    invoke(state, "UpdateCompShareStopScheduler", params, success=tr("Scheduled shutdown"))


@schedule_app.command("cancel", help="Cancel an instance scheduled shutdown.")
def cancel_schedule(
    ctx: typer.Context,
    instance: str,
    project_id: Optional[str] = typer.Option(
        None, "--project-id", help="Override the automatically detected project ID."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(tr("Cancel scheduled shutdown for {instance}?", instance=instance), yes)
    state = runtime(ctx)
    region, _, _ = locate_instance(state, instance)
    params = request(
        ctx,
        project_id=_project_id(state, project_id),
        region_value=region,
    )
    params["UHostId"] = instance
    invoke(state, "DeleteCompShareStopScheduler", params, success=tr("Cancelled shutdown"))


@software_app.command("list", help="List supported instance software.")
def list_software(
    ctx: typer.Context,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    invoke(
        runtime(ctx),
        "DescribeCompShareSoftwarePort",
        request(ctx, region_value=region),
        list_key="SoftwarePort",
        columns=(("Software", "SOFTWARE"), ("Port", "PORT")),
    )


@software_app.command(
    "url",
    help="Get an instance software access URL (currently unavailable in production).",
)
def software_url(ctx: typer.Context, instance: str, software: str) -> None:
    state = runtime(ctx)
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update({"UHostId": instance, "Software": software})
    invoke(state, "GetSoftwareURL", params)


@app.command("ssh", help="Open or print an instance SSH command.")
def ssh(
    ctx: typer.Context,
    instance: str,
    print_only: bool = typer.Option(False, "--print", help="Print instead of executing SSH."),
) -> None:
    state = runtime(ctx)
    region, zone, host = locate_instance(state, instance)
    command = host.get("SshLoginCommand")
    password = host.get("Password")
    if not command:
        raise UsageError(tr("Instance {instance} has no SSH login command.", instance=instance))
    if print_only or state.json_output:
        Renderer(state.json_output).data(
            {
                "instance": instance,
                "command": command,
                "password": password,
            }
        )
        return
    if password:
        typer.echo(f"Password: {password}")
    else:
        typer.echo(
            tr(
                "The API did not return a password. Run `compshare instance password {instance}` "
                "to set one.",
                instance=instance,
            )
        )
    argv = shlex.split(command)
    raise typer.Exit(subprocess.call(argv))
