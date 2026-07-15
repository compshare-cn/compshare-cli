from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import typer

from compshare_cli.api import call, invoke
from compshare_cli.commands.common import confirm, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.location import locate_instance, region_from_zone
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact, read_base64, read_text, split_csv

app = typer.Typer(help="Manage instance images.", no_args_is_help=True)

IMAGE_COLUMNS = (
    ("CompShareImageId", "ID"),
    ("Name", "NAME"),
    ("ImageType", "TYPE"),
    ("Author", "AUTHOR"),
    ("Status", "STATUS"),
    ("Price", "PRICE/H"),
    ("VersionName", "VERSION"),
    ("Tags", "TAGS"),
)


def _community_rows(response: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for group in response.get("CompshareImageGroup", []):
        for raw in group.get("Data", []):
            row = dict(raw)
            row.setdefault("Name", group.get("ImageName"))
            row.setdefault("Status", group.get("Status"))
            row["GroupId"] = group.get("GroupId")
            yield row


def _source(source: str) -> Tuple[str, str, bool]:
    mapping = {
        "platform": ("DescribeCompShareImages", "ImageSet", False),
        "custom": ("DescribeCompShareCustomImages", "ImageSet", False),
        "community": ("DescribeCommunityImages", "CompshareImageGroup", True),
        "shared": ("DescribeCompShareSharingImages", "ImageSet", False),
        "published": ("DescribeSelfCommunityImages", "CompshareImageGroup", True),
        "user": ("DescribeUserCommunityImages", "CompshareImageGroup", True),
    }
    try:
        return mapping[source.lower()]
    except KeyError as exc:
        raise UsageError(
            tr("--source must be platform, custom, community, shared, published, or user.")
        ) from exc


@app.command("list")
def list_images(
    ctx: typer.Context,
    source: str = typer.Option(
        "platform",
        "--source",
        help="Image source: platform, custom, community, shared, published or user.",
    ),
    image: Optional[str] = typer.Option(None, "--id", help="Filter by image ID."),
    group: Optional[str] = typer.Option(None, "--group", help="Filter by version group ID."),
    name: Optional[str] = typer.Option(None, help="Filter by exact image name."),
    author: Optional[str] = typer.Option(None, help="Filter by image author."),
    query: Optional[str] = typer.Option(None, "--query", help="Fuzzy name or author search."),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Filter by tag; repeatable."),
    image_type: Optional[str] = typer.Option(None, "--type", help="Filter by image type."),
    free: Optional[bool] = typer.Option(
        None, "--free/--paid", help="Filter free or paid community images."
    ),
    official: Optional[bool] = typer.Option(
        None, "--official/--unofficial", help="Filter official or community-authored images."
    ),
    autostart: Optional[bool] = typer.Option(
        None, "--autostart/--no-autostart", help="Filter by automatic startup support."
    ),
    sort: Optional[str] = typer.Option(None, "--sort", help="Community sort field."),
    ascending: bool = typer.Option(False, "--ascending", help="Sort in ascending order."),
    user: Optional[int] = typer.Option(None, "--user", help="Organization ID for source=user."),
    limit: int = typer.Option(20, min=1, max=100, help="Maximum number of results."),
    offset: int = typer.Option(0, min=0, help="Number of results to skip."),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
) -> None:
    """List platform, custom, community, shared or published images."""
    source = source.lower()
    action, list_key, grouped = _source(source)
    tags = split_csv(tag or [])
    if source == "platform" and len(tags) > 1:
        raise UsageError(tr("Platform image search supports only one --tag."))
    filters = compact(
        {
            "CompShareImageId": image,
            "GroupId": group,
            "Name": name,
            "Author": author,
            "FuzzySearch": query,
            "Tag": (tags[0] if source == "platform" and tags else tags or None),
            "ImageType": image_type,
            "IsFree": free,
            "IsOfficial": official,
            "IfAutoStart": autostart,
            "SortCondition": {"Field": sort, "ASC": ascending} if sort else None,
            "TargetTopOrganizationId": user,
        }
    )
    allowed = {
        "platform": {"CompShareImageId", "Name", "Author", "Tag", "ImageType"},
        "custom": {"CompShareImageId"},
        "community": {
            "CompShareImageId",
            "GroupId",
            "Name",
            "Author",
            "FuzzySearch",
            "Tag",
            "IsFree",
            "IsOfficial",
            "IfAutoStart",
            "SortCondition",
        },
        "shared": {"CompShareImageId"},
        "published": {
            "CompShareImageId",
            "GroupId",
            "Name",
            "Author",
            "FuzzySearch",
            "Tag",
            "IsFree",
            "IsOfficial",
            "IfAutoStart",
            "SortCondition",
        },
        "user": {"TargetTopOrganizationId"},
    }[source]
    unsupported = sorted(set(filters) - allowed)
    if unsupported:
        raise UsageError(
            tr(
                "Image source {source} does not support: {options}",
                source=source,
                options=", ".join(unsupported),
            )
        )
    selected_zone = zone or runtime(ctx).zone
    selected_region = region_from_zone(selected_zone) if source == "platform" else region
    params = request(ctx, region_value=selected_region)
    params.update({"Limit": limit, "Offset": offset, **filters})
    if source == "platform":
        params["Zone"] = selected_zone
    invoke(
        runtime(ctx),
        action,
        params,
        list_key=None if grouped else list_key,
        row_builder=_community_rows if grouped else None,
        columns=IMAGE_COLUMNS,
    )


@app.command("show", help="Show image details.")
def show(
    ctx: typer.Context,
    image: str,
    source: str = typer.Option("platform", "--source", help="Image source."),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
) -> None:
    source = source.lower()
    if source not in {"platform", "custom", "community", "shared", "published"}:
        raise UsageError(tr("Image source {source} cannot be queried by ID.", source=source))
    action, _, _ = _source(source)
    selected_zone = zone or runtime(ctx).zone
    selected_region = region_from_zone(selected_zone) if source == "platform" else region
    params = request(ctx, region_value=selected_region)
    params["CompShareImageId"] = image
    if source == "platform":
        params["Zone"] = selected_zone
    state = runtime(ctx)
    response = call(state, action, params)
    rows = (
        list(_community_rows(response))
        if source in {"community", "published"}
        else response.get("ImageSet", [])
    )
    item = next(
        (row for row in rows if row.get("CompShareImageId") == image),
        rows[0] if rows else None,
    )
    if not item:
        raise UsageError(tr("Image {image} was not found.", image=image))
    Renderer(state.json_output).details(
        "Image details",
        [
            ("ID", item.get("CompShareImageId")),
            ("NAME", item.get("Name")),
            ("TYPE", item.get("ImageType")),
            ("STATUS", item.get("Status")),
            ("AUTHOR", item.get("Author")),
            ("VERSION", item.get("VersionName")),
            ("TAGS", item.get("Tags")),
            ("PRICE/H", item.get("Price")),
            ("DESCRIPTION", item.get("Description")),
        ],
        response=response,
    )


@app.command("create")
def create(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance", help="Source instance ID."),
    name: str = typer.Option(..., help="Custom image name."),
    description: Optional[str] = typer.Option(None, help="Custom image description."),
    wait: Optional[bool] = typer.Option(
        None,
        "--wait/--no-wait",
        help="Wait for the operation to reach a stable state.",
    ),
    timeout: int = typer.Option(1800, "--timeout", min=1, help="Maximum wait time in seconds."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Create a custom image from an instance."""
    state = runtime(ctx)
    confirm(
        tr(
            "Create custom image {name} from instance {instance}?",
            name=name,
            instance=instance,
        ),
        yes,
    )
    region, zone, _ = locate_instance(state, instance)
    params = request(ctx, zone=True, region_value=region, zone_value=zone)
    params.update(compact({"UHostId": instance, "Name": name, "Description": description}))
    created = call(state, "CreateCompShareCustomImage", params)
    result: Dict[str, Any] = {"operation": created}
    image_id = created.get("CompShareImageId") or created.get("ImageId")
    wait_enabled = wait if wait is not None else not state.json_output and sys.stdout.isatty()
    if wait_enabled and image_id:
        started = time.monotonic()
        previous: Optional[str] = None
        while True:
            progress_params = request(
                ctx,
                zone=True,
                region_value=region,
                zone_value=zone,
            )
            progress_params["CompShareImageId"] = image_id
            current = call(state, "GetCompShareImageCreateProgress", progress_params)
            status = str(current.get("Status") or current.get("State") or "Creating")
            percent = current.get("Progress") or current.get("Percent")
            display = f"{status} ({percent}%)" if percent is not None else status
            if display != previous and not state.json_output:
                typer.echo(tr("Waiting for image {image}: {state}", image=image_id, state=display))
                previous = display
            if status.casefold() in {"available", "success", "succeeded", "done"} or percent == 100:
                result["final"] = current
                break
            if status.casefold() in {"failed", "error"}:
                raise UsageError(tr("Image creation failed: {status}", status=status))
            if time.monotonic() - started >= timeout:
                raise UsageError(
                    tr(
                        "Timed out after {timeout}s while waiting for image {image}.",
                        timeout=timeout,
                        image=image_id,
                    )
                )
            time.sleep(5)
    Renderer(state.json_output).success(tr("Creating image {name}", name=name), result)


@app.command("progress", help="Get custom image creation progress.")
def progress(
    ctx: typer.Context,
    image: str,
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
) -> None:
    selected_zone = zone or runtime(ctx).zone
    params = request(ctx, zone=True, zone_value=selected_zone)
    params["CompShareImageId"] = image
    invoke(runtime(ctx), "GetCompShareImageCreateProgress", params)


@app.command("update", help="Update image metadata.")
def update(
    ctx: typer.Context,
    image: str,
    group: Optional[str] = typer.Option(None, help="Community version group ID."),
    name: Optional[str] = typer.Option(None, help="New image name."),
    description: Optional[str] = typer.Option(None, help="New image description."),
    visibility: Optional[int] = typer.Option(
        None, min=0, max=1, help="Visibility: 0 private, 1 public."
    ),
    price: Optional[float] = typer.Option(None, min=0, help="Hourly image price."),
    cover: Optional[Path] = typer.Option(
        None, exists=True, dir_okay=False, help="Cover image file encoded as Base64."
    ),
    readme: Optional[Path] = typer.Option(
        None, exists=True, dir_okay=False, help="UTF-8 README file."
    ),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Image tag; repeatable."),
    version: Optional[str] = typer.Option(None, help="Version name."),
    version_description: Optional[str] = typer.Option(
        None, "--version-description", help="Version description."
    ),
    gpu: Optional[List[str]] = typer.Option(None, "--gpu", help="Supported GPU type; repeatable."),
    autostart: Optional[bool] = typer.Option(
        None, "--autostart/--no-autostart", help="Whether the image supports automatic startup."
    ),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    values = compact(
        {
            "GroupId": group,
            "Name": name,
            "Description": description,
            "Visibility": visibility,
            "Price": price,
            "Cover": read_base64(cover),
            "Readme": read_text(readme),
            "Tags": split_csv(tag or []) or None,
            "VersionName": version,
            "VersionDesc": version_description,
            "SupportedGpuTypes": split_csv(gpu or []) or None,
            "AutoStart": autostart,
        }
    )
    if not values:
        raise UsageError(tr("Specify at least one field to update."))
    params = request(ctx, region_value=region)
    params.update({"CompShareImageId": image, **values})
    invoke(
        runtime(ctx),
        "UpdateCompShareImage",
        params,
        success=tr("Updated image {image}", image=image),
    )


@app.command("delete", help="Permanently delete a custom image.")
def delete(
    ctx: typer.Context,
    image: str,
    zone: Optional[str] = typer.Option(None, "--zone", help="Availability zone."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(tr("Permanently delete custom image {image}?", image=image), yes)
    selected_zone = zone or runtime(ctx).zone
    params = request(ctx, zone=True, zone_value=selected_zone)
    params["CompShareImageId"] = image
    invoke(
        runtime(ctx),
        "TerminateCompShareCustomImage",
        params,
        success=tr("Deleted image {image}", image=image),
    )


@app.command("shares", help="List accounts an image is shared with.")
def shares(
    ctx: typer.Context,
    image: str,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    params = request(ctx, region_value=region)
    params["CompShareImageId"] = image
    invoke(
        runtime(ctx),
        "DescribeCompShareImageShareAccounts",
        params,
        list_key="AccountSet",
        columns=(("AccountId", "ACCOUNT ID"), ("AccountName", "ACCOUNT")),
    )


def _share(
    ctx: typer.Context,
    image: str,
    accounts: List[int],
    *,
    remove: bool,
    region: Optional[str],
) -> None:
    params = request(ctx, region_value=region)
    params["CompShareImageId"] = image
    params["RemoveAccounts" if remove else "AddAccounts"] = accounts
    invoke(
        runtime(ctx),
        "ModifyCompShareImageShareAccount",
        params,
        success=tr("Unshared image {image}" if remove else "Shared image {image}", image=image),
    )


@app.command("share", help="Share an image with accounts.")
def share(
    ctx: typer.Context,
    image: str,
    accounts: List[int] = typer.Argument(...),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    _share(ctx, image, accounts, remove=False, region=region)


@app.command("unshare", help="Remove image sharing from accounts.")
def unshare(
    ctx: typer.Context,
    image: str,
    accounts: List[int] = typer.Argument(...),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(
        tr("Remove {count} share(s) from image {image}?", count=len(accounts), image=image),
        yes,
    )
    _share(ctx, image, accounts, remove=True, region=region)


@app.command("publish", help="Publish an image to the community.")
def publish(
    ctx: typer.Context,
    image: str,
    version: str = typer.Option(..., help="Community version name."),
    group: Optional[str] = typer.Option(None, help="Existing community version group ID."),
    name: Optional[str] = typer.Option(None, help="Community image name."),
    version_description: Optional[str] = typer.Option(
        None, "--version-description", help="Version description."
    ),
    price: float = typer.Option(0, min=0, help="Hourly image price; 0 means free."),
    cover: Optional[Path] = typer.Option(
        None, exists=True, dir_okay=False, help="Cover image file encoded as Base64."
    ),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Image tag; repeatable."),
    description: Optional[str] = typer.Option(None, help="Community image description."),
    readme: Optional[Path] = typer.Option(
        None, exists=True, dir_okay=False, help="UTF-8 README file."
    ),
    gpu: Optional[List[str]] = typer.Option(None, "--gpu", help="Supported GPU type; repeatable."),
    autostart: Optional[bool] = typer.Option(
        None, "--autostart/--no-autostart", help="Whether the image supports automatic startup."
    ),
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    confirm(
        tr("Publish image {image} as community version {version}?", image=image, version=version),
        yes,
    )
    params = request(ctx, region_value=region)
    params.update(
        compact(
            {
                "CompShareImageId": image,
                "GroupId": group,
                "CommunityImageName": name,
                "VersionName": version,
                "VersionDesc": version_description,
                "Price": price,
                "Cover": read_base64(cover),
                "Tags": split_csv(tag or []) or None,
                "Description": description,
                "Readme": read_text(readme),
                "SupportedGpuTypes": split_csv(gpu or []) or None,
                "AutoStart": autostart,
            }
        )
    )
    invoke(
        runtime(ctx),
        "PublishCompShareImage",
        params,
        success=tr("Published image {image}", image=image),
    )


@app.command("favorite", help="Add an image to favorites.")
def favorite(
    ctx: typer.Context,
    image: str,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    params = request(ctx, region_value=region)
    params["CompShareImageId"] = image
    invoke(
        runtime(ctx),
        "AddFavoriteImage",
        params,
        success=tr("Favorited image {image}", image=image),
    )


@app.command("unfavorite", help="Remove an image from favorites.")
def unfavorite(
    ctx: typer.Context,
    image: str,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    params = request(ctx, region_value=region)
    params["CompShareImageId"] = image
    invoke(
        runtime(ctx),
        "RemoveFavoriteImage",
        params,
        success=tr("Unfavorited image {image}", image=image),
    )


@app.command("tags", help="List available image tags.")
def tags(
    ctx: typer.Context,
    region: Optional[str] = typer.Option(None, "--region", help="Region for this request."),
) -> None:
    invoke(
        runtime(ctx),
        "DescribeCompShareImageTags",
        request(ctx, region_value=region),
    )
