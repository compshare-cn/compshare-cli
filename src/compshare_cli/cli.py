from __future__ import annotations

import sys
from typing import List, Optional

import click
import typer
from typer.main import get_command

from compshare_cli import __version__
from compshare_cli.commands import image, instance, storage
from compshare_cli.config import DEFAULT_PROFILE, ConfigStore, Profile
from compshare_cli.errors import CLIError
from compshare_cli.i18n import configured_language, localize_command, normalize_language
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime

app = typer.Typer(
    name="compshare",
    help="Manage CompShare GPU compute from the terminal.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(instance.app, name="instance")
app.add_typer(image.app, name="image")
app.add_typer(storage.app, name="storage")


@app.callback()
def root(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(None, "--profile", help="Credential profile."),
    region: Optional[str] = typer.Option(
        None,
        "--region",
        help="Region for this request; not part of the credential profile.",
    ),
    zone: Optional[str] = typer.Option(
        None,
        "--zone",
        help="Availability zone for this request; not part of the credential profile.",
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
        region_override=region,
        zone_override=zone,
    )


@app.command("config")
def config(
    ctx: typer.Context,
    name: str = typer.Option(
        DEFAULT_PROFILE,
        "--name",
        "--profile",
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
    public = public_key or typer.prompt("Public key")
    private = private_key or typer.prompt("Private key", hide_input=True)
    ConfigStore().save_profile(
        name,
        Profile(public_key=public, private_key=private),
        activate=activate,
    )
    Renderer(ctx.find_root().obj.json_output).success(
        f"Saved credential profile {name}",
        {"ok": True, "profile": name, "active": activate},
    )


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


def _normalize_global_options(args: List[str]) -> List[str]:
    """Allow the global --json option before or after subcommands."""
    prefix: List[str] = []
    remaining: List[str] = []
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--json":
            prefix.append(argument)
        else:
            remaining.append(argument)
        index += 1
    return [*prefix, *remaining]


def main(args: Optional[List[str]] = None) -> None:
    argv = _normalize_global_options(list(sys.argv[1:] if args is None else args))
    try:
        language = configured_language()
        command = localize_command(get_command(app), language)
        result = command.main(args=argv, prog_name="compshare", standalone_mode=False)
    except CLIError as error:
        Renderer("--json" in argv).error(str(error))
        raise SystemExit(2) from error
    except click.ClickException as error:
        Renderer("--json" in argv).error(error.format_message())
        raise SystemExit(error.exit_code) from error
    except click.Abort as error:
        Renderer("--json" in argv).error("Aborted")
        raise SystemExit(1) from error
    if isinstance(result, int) and result:
        raise SystemExit(result)


if __name__ == "__main__":
    main()
