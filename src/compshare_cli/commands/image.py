from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import typer

from compshare_cli.api import invoke
from compshare_cli.commands.common import confirm, request, runtime
from compshare_cli.errors import UsageError
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
            "--source 必须是 platform、custom、community、shared、published 或 user"
        ) from exc


@app.command("list")
def list_images(
    ctx: typer.Context,
    source: str = typer.Option("platform", "--source"),
    image: Optional[str] = typer.Option(None, "--id"),
    group: Optional[str] = typer.Option(None, "--group"),
    name: Optional[str] = typer.Option(None),
    author: Optional[str] = typer.Option(None),
    query: Optional[str] = typer.Option(None, "--query", help="Fuzzy name or author search."),
    tag: Optional[List[str]] = typer.Option(None, "--tag"),
    image_type: Optional[str] = typer.Option(None, "--type"),
    free: Optional[bool] = typer.Option(None, "--free/--paid"),
    official: Optional[bool] = typer.Option(None, "--official/--unofficial"),
    autostart: Optional[bool] = typer.Option(None, "--autostart/--no-autostart"),
    sort: Optional[str] = typer.Option(None, "--sort", help="Community sort field."),
    ascending: bool = typer.Option(False, "--ascending"),
    user: Optional[int] = typer.Option(None, "--user", help="Organization ID for source=user."),
    limit: int = typer.Option(20, min=1, max=100),
    offset: int = typer.Option(0, min=0),
) -> None:
    """List platform, custom, community, shared or published images."""
    source = source.lower()
    action, list_key, grouped = _source(source)
    tags = split_csv(tag or [])
    if source == "platform" and len(tags) > 1:
        raise UsageError("platform 镜像查询只支持一个 --tag")
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
        raise UsageError(f"{source} 镜像查询不支持参数: {', '.join(unsupported)}")
    params = request(ctx)
    params.update({"Limit": limit, "Offset": offset, **filters})
    if source == "platform":
        params["Zone"] = runtime(ctx).zone
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
    source: str = typer.Option("platform", "--source"),
) -> None:
    source = source.lower()
    if source not in {"platform", "custom", "community", "shared", "published"}:
        raise UsageError(f"{source} 镜像接口不支持按 ID 查询")
    action, _, _ = _source(source)
    params = request(ctx)
    params["CompShareImageId"] = image
    if source == "platform":
        params["Zone"] = runtime(ctx).zone
    invoke(runtime(ctx), action, params)


@app.command("create")
def create(
    ctx: typer.Context,
    instance: str = typer.Option(..., "--instance"),
    name: str = typer.Option(...),
    description: Optional[str] = typer.Option(None),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Create a custom image from an instance."""
    confirm(f"Create custom image {name} from instance {instance}?", yes)
    params = request(ctx, zone=True)
    params.update(compact({"UHostId": instance, "Name": name, "Description": description}))
    invoke(runtime(ctx), "CreateCompShareCustomImage", params, success=f"Creating image {name}")


@app.command("progress", help="Get custom image creation progress.")
def progress(ctx: typer.Context, image: str) -> None:
    params = request(ctx, zone=True)
    params["CompShareImageId"] = image
    invoke(runtime(ctx), "GetCompShareImageCreateProgress", params)


@app.command("update", help="Update image metadata.")
def update(
    ctx: typer.Context,
    image: str,
    group: Optional[str] = typer.Option(None),
    name: Optional[str] = typer.Option(None),
    description: Optional[str] = typer.Option(None),
    visibility: Optional[int] = typer.Option(None, min=0, max=1),
    price: Optional[float] = typer.Option(None, min=0),
    cover: Optional[Path] = typer.Option(None, exists=True, dir_okay=False),
    readme: Optional[Path] = typer.Option(None, exists=True, dir_okay=False),
    tag: Optional[List[str]] = typer.Option(None, "--tag"),
    version: Optional[str] = typer.Option(None),
    version_description: Optional[str] = typer.Option(None, "--version-description"),
    gpu: Optional[List[str]] = typer.Option(None, "--gpu"),
    autostart: Optional[bool] = typer.Option(None, "--autostart/--no-autostart"),
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
        raise UsageError("至少指定一个要更新的字段")
    params = request(ctx)
    params.update({"CompShareImageId": image, **values})
    invoke(runtime(ctx), "UpdateCompShareImage", params, success=f"Updated image {image}")


@app.command("delete", help="Permanently delete a custom image.")
def delete(
    ctx: typer.Context,
    image: str,
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Permanently delete custom image {image}?", yes)
    params = request(ctx, zone=True)
    params["CompShareImageId"] = image
    invoke(
        runtime(ctx),
        "TerminateCompShareCustomImage",
        params,
        success=f"Deleted image {image}",
    )


@app.command("shares", help="List accounts an image is shared with.")
def shares(ctx: typer.Context, image: str) -> None:
    params = request(ctx)
    params["CompShareImageId"] = image
    invoke(
        runtime(ctx),
        "DescribeCompShareImageShareAccounts",
        params,
        list_key="AccountSet",
        columns=(("AccountId", "ACCOUNT ID"), ("AccountName", "ACCOUNT")),
    )


def _share(ctx: typer.Context, image: str, accounts: List[int], *, remove: bool) -> None:
    params = request(ctx)
    params["CompShareImageId"] = image
    params["RemoveAccounts" if remove else "AddAccounts"] = accounts
    invoke(
        runtime(ctx),
        "ModifyCompShareImageShareAccount",
        params,
        success=("Unshared" if remove else "Shared") + f" image {image}",
    )


@app.command("share", help="Share an image with accounts.")
def share(ctx: typer.Context, image: str, accounts: List[int] = typer.Argument(...)) -> None:
    _share(ctx, image, accounts, remove=False)


@app.command("unshare", help="Remove image sharing from accounts.")
def unshare(
    ctx: typer.Context,
    image: str,
    accounts: List[int] = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Remove {len(accounts)} share(s) from image {image}?", yes)
    _share(ctx, image, accounts, remove=True)


@app.command("publish", help="Publish an image to the community.")
def publish(
    ctx: typer.Context,
    image: str,
    version: str = typer.Option(...),
    group: Optional[str] = typer.Option(None),
    name: Optional[str] = typer.Option(None),
    version_description: Optional[str] = typer.Option(None, "--version-description"),
    price: float = typer.Option(0, min=0),
    cover: Optional[Path] = typer.Option(None, exists=True, dir_okay=False),
    tag: Optional[List[str]] = typer.Option(None, "--tag"),
    description: Optional[str] = typer.Option(None),
    readme: Optional[Path] = typer.Option(None, exists=True, dir_okay=False),
    gpu: Optional[List[str]] = typer.Option(None, "--gpu"),
    autostart: Optional[bool] = typer.Option(None, "--autostart/--no-autostart"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    confirm(f"Publish image {image} as community version {version}?", yes)
    params = request(ctx)
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
    invoke(runtime(ctx), "PublishCompShareImage", params, success=f"Published image {image}")


@app.command("favorite", help="Add an image to favorites.")
def favorite(ctx: typer.Context, image: str) -> None:
    params = request(ctx)
    params["CompShareImageId"] = image
    invoke(runtime(ctx), "AddFavoriteImage", params, success=f"Favorited image {image}")


@app.command("unfavorite", help="Remove an image from favorites.")
def unfavorite(ctx: typer.Context, image: str) -> None:
    params = request(ctx)
    params["CompShareImageId"] = image
    invoke(runtime(ctx), "RemoveFavoriteImage", params, success=f"Unfavorited image {image}")


@app.command("tags", help="List available image tags.")
def tags(ctx: typer.Context) -> None:
    invoke(runtime(ctx), "DescribeCompShareImageTags", request(ctx))
