from __future__ import annotations

import sys
from typing import List, Optional

import click
import typer
from typer import core as typer_core
from typer.main import get_command

from compshare_cli import __version__
from compshare_cli.commands import image, instance, storage
from compshare_cli.config import DEFAULT_PROFILE, ConfigStore, Profile
from compshare_cli.errors import CLIError
from compshare_cli.i18n import configured_language, localize_command, normalize_language, tr
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime

_TYPER_CLICK = getattr(typer_core, "_click", click)
_TYPER_CLICK_EXCEPTIONS = getattr(_TYPER_CLICK, "exceptions", _TYPER_CLICK)
_CLICK_EXCEPTIONS = (click.ClickException, _TYPER_CLICK_EXCEPTIONS.ClickException)
_ABORT_EXCEPTIONS = (click.Abort, _TYPER_CLICK_EXCEPTIONS.Abort)


class RootGroup(typer_core.TyperGroup):
    def list_commands(self, ctx):
        names = super().list_commands(ctx)
        if "config" not in names:
            return names
        return ["config", *(name for name in names if name != "config")]


app = typer.Typer(
    name="compshare",
    help="Manage CompShare GPU compute from the terminal.",
    cls=RootGroup,
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(instance.app, name="instance")
app.add_typer(image.app, name="image")
app.add_typer(storage.app, name="storage")
config_app = typer.Typer(
    help="Manage credential profiles.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(config_app, name="config")


@app.callback()
def root(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        metavar="NAME",
        help="Credential profile.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    """CompShare CLI."""
    ctx.obj = Runtime(
        json_output=json_output,
        profile_name=profile,
    )


@config_app.callback()
def config(
    ctx: typer.Context,
    name: str = typer.Option(
        DEFAULT_PROFILE,
        "--name",
        help="Credential profile name.",
    ),
    public_key: Optional[str] = typer.Option(None, "--public-key", help="API public key."),
    private_key: Optional[str] = typer.Option(None, "--private-key", hidden=True),
    activate: bool = typer.Option(
        True,
        "--activate/--no-activate",
        help="Make this profile the default.",
    ),
) -> None:
    """Save a CompShare API credential profile."""
    if ctx.invoked_subcommand is not None:
        return
    public = public_key or typer.prompt(tr("Public key"))
    private = private_key or typer.prompt(tr("Private key"), hide_input=True)
    ConfigStore().save_profile(
        name,
        Profile(public_key=public, private_key=private),
        activate=activate,
    )
    Renderer(ctx.find_root().obj.json_output).success(
        tr("Saved credential profile {name}", name=name),
        {"ok": True, "profile": name, "active": activate},
    )


@config_app.command("set")
def config_set(
    ctx: typer.Context,
    name: str = typer.Option(DEFAULT_PROFILE, "--name", help="Credential profile name."),
    public_key: Optional[str] = typer.Option(None, "--public-key", help="API public key."),
    private_key: Optional[str] = typer.Option(None, "--private-key", hidden=True),
    activate: bool = typer.Option(
        True, "--activate/--no-activate", help="Make this profile the default."
    ),
) -> None:
    """Create or update a credential profile."""
    public = public_key or typer.prompt(tr("Public key"))
    private = private_key or typer.prompt(tr("Private key"), hide_input=True)
    ConfigStore().save_profile(
        name,
        Profile(public_key=public, private_key=private),
        activate=activate,
    )
    Renderer(ctx.find_root().obj.json_output).success(
        tr("Saved credential profile {name}", name=name),
        {"ok": True, "profile": name, "active": activate},
    )


@config_app.command("list")
def config_list(ctx: typer.Context) -> None:
    """List credential profiles."""
    store = ConfigStore()
    current = store.current_profile()
    profiles = [{"Profile": name, "Active": name == current} for name in store.list_profiles()]
    Renderer(ctx.find_root().obj.json_output).data(
        {"current_profile": current, "profiles": profiles},
        rows=profiles,
        columns=(("Profile", "PROFILE"), ("Active", "ACTIVE")),
    )


@config_app.command("use")
def config_use(ctx: typer.Context, name: str) -> None:
    """Set the default credential profile."""
    ConfigStore().use_profile(name)
    Renderer(ctx.find_root().obj.json_output).success(
        tr("Using credential profile {name}", name=name),
        {"ok": True, "profile": name},
    )


@config_app.command("delete")
def config_delete(
    ctx: typer.Context,
    name: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a credential profile."""
    if not yes and not typer.confirm(tr("Delete credential profile {name}?", name=name)):
        raise typer.Abort()
    ConfigStore().delete_profile(name)
    Renderer(ctx.find_root().obj.json_output).success(
        tr("Deleted credential profile {name}", name=name),
        {"ok": True, "profile": name},
    )


@config_app.command("path")
def config_path_command(ctx: typer.Context) -> None:
    """Show the configuration file path."""
    path = str(ConfigStore().path)
    if ctx.find_root().obj.json_output:
        Renderer(True).data({"path": path})
    else:
        typer.echo(path)


@app.command("version")
def version(ctx: typer.Context) -> None:
    """Print the CLI version."""
    if ctx.find_root().obj.json_output:
        Renderer(True).data({"version": __version__})
    else:
        typer.echo(__version__)


@app.command("lang")
def lang(
    ctx: typer.Context,
    language: Optional[str] = typer.Argument(None, help="Language: zh or en."),
) -> None:
    """Set or show the default help language."""
    renderer = Renderer(ctx.find_root().obj.json_output)
    if language is None:
        current = configured_language()
        message = (
            f"当前默认帮助语言：{current}"
            if current == "zh"
            else f"Default help language: {current}"
        )
        renderer.success(message, {"language": current})
        return

    selected = normalize_language(language)
    ConfigStore().save_language(selected)
    message = (
        "默认帮助语言已切换为中文（zh）"
        if selected == "zh"
        else "Default help language set to English (en)"
    )
    renderer.success(message, {"ok": True, "language": selected})


def main(args: Optional[List[str]] = None) -> None:
    argv = list(sys.argv[1:] if args is None else args)
    if not argv:
        argv = ["-h"]
    try:
        language = configured_language()
        command = localize_command(get_command(app), language)
        result = command.main(args=argv, prog_name="compshare", standalone_mode=False)
    except CLIError as error:
        Renderer("--json" in argv).error(str(error))
        raise SystemExit(2) from error
    except _CLICK_EXCEPTIONS as error:
        Renderer("--json" in argv).error(error.format_message())
        raise SystemExit(error.exit_code) from error
    except _ABORT_EXCEPTIONS as error:
        Renderer("--json" in argv).error(tr("Aborted"))
        raise SystemExit(1) from error
    if isinstance(result, int) and result:
        raise SystemExit(result)


if __name__ == "__main__":
    main()
