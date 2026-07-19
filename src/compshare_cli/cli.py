from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import click
import typer
from typer import core as typer_core
from typer.completion import completion_init, install_callback
from typer.main import get_command

from compshare_cli import __version__
from compshare_cli.commands import ask as ask_command
from compshare_cli.commands import doctor as doctor_command
from compshare_cli.commands import feedback as feedback_command
from compshare_cli.commands import image, instance, storage, team
from compshare_cli.commands.common import confirm
from compshare_cli.config import DEFAULT_PROFILE, ConfigStore, Profile
from compshare_cli.errors import CLIError, ConfigError, UsageError
from compshare_cli.i18n import configured_language, localize_command, normalize_language, tr
from compshare_cli.insights import record_command
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime

_TYPER_CLICK = getattr(typer_core, "_click", click)
_TYPER_CLICK_EXCEPTIONS = getattr(_TYPER_CLICK, "exceptions", _TYPER_CLICK)
_CLICK_EXCEPTIONS = (click.ClickException, _TYPER_CLICK_EXCEPTIONS.ClickException)
_ABORT_EXCEPTIONS = (click.Abort, _TYPER_CLICK_EXCEPTIONS.Abort)

completion_init()


class RootGroup(typer_core.TyperGroup):
    def list_commands(self, ctx):
        names = super().list_commands(ctx)
        preferred = ("config", "feedback", "doctor")
        return [
            *(name for name in preferred if name in names),
            *(name for name in names if name not in preferred),
        ]


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
app.add_typer(team.app, name="team")
config_app = typer.Typer(
    help="Manage credential profiles.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(config_app, name="config")


def _version_callback(ctx: typer.Context, value: bool) -> None:
    if value:
        if bool(ctx.params.get("json_output")):
            Renderer(True, bool(ctx.params.get("show_sensitive"))).data({"version": __version__})
        else:
            typer.echo(__version__)
        raise typer.Exit()


def _language_callback(value: Optional[str]) -> Optional[str]:
    if value is not None:
        ConfigStore().save_language(normalize_language(value))
    return value


@app.callback()
def root(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        metavar="NAME",
        help="Credential profile.",
    ),
    language: Optional[str] = typer.Option(
        None,
        "--lang",
        metavar="LANG",
        callback=_language_callback,
        is_eager=True,
        help="Language: zh or en.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        is_eager=True,
        help="Emit machine-readable JSON.",
    ),
    show_sensitive: bool = typer.Option(
        False,
        "--show-sensitive",
        is_eager=True,
        help="Show passwords, IP addresses, access URLs, and login commands.",
    ),
    version_option: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the CLI version and exit.",
    ),
    install_completion: bool = typer.Option(
        None,
        "--install-completion",
        callback=install_callback,
        expose_value=False,
        help="Install completion for the current shell.",
    ),
) -> None:
    """CompShare CLI."""
    ctx.obj = Runtime(
        json_output=json_output,
        show_sensitive=show_sensitive,
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
    state = ctx.find_root().obj
    if state.json_output and (public_key is None or private_key is None):
        raise UsageError(
            tr("JSON mode cannot prompt for credentials; pass --public-key and --private-key.")
        )
    public = public_key or typer.prompt(tr("Public key"))
    private = private_key or typer.prompt(tr("Private key"), hide_input=True)
    ConfigStore().save_profile(
        name,
        Profile(public_key=public, private_key=private),
        activate=activate,
    )
    Renderer(state.json_output, state.show_sensitive).success(
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
    state = ctx.find_root().obj
    if state.json_output and (public_key is None or private_key is None):
        raise UsageError(
            tr("JSON mode cannot prompt for credentials; pass --public-key and --private-key.")
        )
    public = public_key or typer.prompt(tr("Public key"))
    private = private_key or typer.prompt(tr("Private key"), hide_input=True)
    ConfigStore().save_profile(
        name,
        Profile(public_key=public, private_key=private),
        activate=activate,
    )
    Renderer(state.json_output, state.show_sensitive).success(
        tr("Saved credential profile {name}", name=name),
        {"ok": True, "profile": name, "active": activate},
    )


@config_app.command("list")
def config_list(ctx: typer.Context) -> None:
    """List credential profiles."""
    store = ConfigStore()
    state = ctx.find_root().obj
    status = store.credential_status(state.profile_name)
    source = status["credential_source"]
    selected = status["selected_profile"]
    active_profile = selected if source in {"profile", "mixed"} else None
    profiles = [
        {
            "Profile": name,
            "Active": name == active_profile,
            "Source": "mixed" if name == active_profile and source == "mixed" else "profile",
        }
        for name in store.list_profiles()
    ]
    rows = [
        {
            **profile,
            "Source": tr("Profile and environment")
            if profile["Source"] == "mixed"
            else tr("Profile file"),
        }
        for profile in profiles
    ]
    if source == "environment":
        rows.insert(
            0,
            {"Profile": "-", "Active": True, "Source": tr("Environment variables")},
        )
    elif source in {"unconfigured", "incomplete"} and not any(
        profile["Active"] for profile in profiles
    ):
        rows.insert(
            0,
            {
                "Profile": selected,
                "Active": False,
                "Source": tr("Incomplete credentials")
                if source == "incomplete"
                else tr("Not configured"),
            },
        )
    Renderer(state.json_output, state.show_sensitive).data(
        {
            **status,
            "current_profile": active_profile,
            "profiles": profiles,
        },
        rows=rows,
        columns=(("Profile", "PROFILE"), ("Active", "ACTIVE"), ("Source", "SOURCE")),
    )


@config_app.command("use")
def config_use(ctx: typer.Context, name: str) -> None:
    """Set the default credential profile."""
    ConfigStore().use_profile(name)
    state = ctx.find_root().obj
    Renderer(state.json_output, state.show_sensitive).success(
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
    confirm(tr("Delete credential profile {name}?", name=name), yes)
    ConfigStore().delete_profile(name)
    state = ctx.find_root().obj
    Renderer(state.json_output, state.show_sensitive).success(
        tr("Deleted credential profile {name}", name=name),
        {"ok": True, "profile": name},
    )


@config_app.command("path")
def config_path_command(ctx: typer.Context) -> None:
    """Show the configuration file path."""
    path = str(ConfigStore().path)
    state = ctx.find_root().obj
    if state.json_output:
        Renderer(True, state.show_sensitive).data({"path": path})
    else:
        typer.echo(path)


@app.command("version", hidden=True)
def version(ctx: typer.Context) -> None:
    """Print the CLI version."""
    state = ctx.find_root().obj
    if state.json_output:
        Renderer(True, state.show_sensitive).data({"version": __version__})
    else:
        typer.echo(__version__)


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    """Diagnose the CLI configuration and environment."""
    doctor_command.run(ctx.find_root().obj)


@app.command("ask", help="Ask a CompShare product question.")
def ask(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="Question to answer."),
) -> None:
    ask_command.run(ctx.find_root().obj, question)


@app.command("feedback")
def feedback(
    ctx: typer.Context,
    category: feedback_command.FeedbackCategory = typer.Argument(
        ...,
        help="Feedback category: bug or suggest.",
    ),
    message: str = typer.Argument(
        ...,
        help="Feedback message; limited to 2000 characters.",
    ),
) -> None:
    """Send feedback about the CLI."""
    feedback_command.run(ctx.find_root().obj, category, message)


def _global_flag_requested(argv: List[str], option: str) -> bool:
    for token in argv:
        if token == "--":
            break
        if token == option:
            return True
    return False


def _normalize_global_options(argv: List[str]) -> List[str]:
    """Move unambiguous root options before the command without crossing --."""
    global_options: List[str] = []
    remaining: List[str] = []
    profile_seen = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            remaining.extend(argv[index:])
            break
        if token in {"--json", "--show-sensitive"}:
            global_options.append(token)
            index += 1
            continue
        if token == "--profile":
            if profile_seen:
                raise UsageError(tr("Option --profile may only be specified once."))
            profile_seen = True
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                raise UsageError(tr("Option --profile requires a value."))
            global_options.extend((token, argv[index + 1]))
            index += 2
            continue
        if token.startswith("--profile="):
            if profile_seen:
                raise UsageError(tr("Option --profile may only be specified once."))
            profile_seen = True
            if not token.partition("=")[2]:
                raise UsageError(tr("Option --profile requires a value."))
            global_options.append(token)
            index += 1
            continue
        remaining.append(token)
        index += 1
    return [*global_options, *remaining]


def _command_path(command: click.Command, argv: List[str]) -> Optional[str]:
    if not argv or "-h" in argv or "--help" in argv:
        return None
    remaining = list(argv)
    while remaining and remaining[0].startswith("-"):
        option = remaining.pop(0)
        if option in {"--profile", "--lang"} and remaining:
            remaining.pop(0)
        elif option.startswith(("--profile=", "--lang=")) or option in {
            "--json",
            "--show-sensitive",
        }:
            continue
        else:
            return None

    path: List[str] = []
    current = command
    while remaining and isinstance(current, click.Group):
        name = remaining.pop(0)
        child = current.commands.get(name)
        if child is None:
            break
        path.append(name)
        current = child
    return ".".join(path) or None


def _json_help_requested(argv: List[str]) -> bool:
    for token in argv:
        if token == "--":
            return False
        if token in {"-h", "--help"}:
            return True
    return False


def _json_help_payload(command: click.Command, argv: List[str]) -> Dict[str, Any]:
    """Build machine-readable help without invoking Rich's terminal renderer."""
    current = command
    path: List[str] = []
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token in {"-h", "--help", "--"}:
            break
        if token in {"--profile", "--lang"}:
            skip_next = True
            continue
        if token.startswith(("--profile=", "--lang=")) or token in {
            "--json",
            "--show-sensitive",
        }:
            continue
        if isinstance(current, click.Group) and token in current.commands:
            current = current.commands[token]
            path.append(token)

    parameters: List[Dict[str, Any]] = []
    for parameter in current.params:
        if isinstance(parameter, click.Option):
            parameters.append(
                {
                    "kind": "option",
                    "name": parameter.name,
                    "flags": [*parameter.opts, *parameter.secondary_opts],
                    "required": parameter.required,
                    "multiple": parameter.multiple,
                    "help": parameter.help,
                }
            )
        elif isinstance(parameter, click.Argument):
            parameters.append(
                {
                    "kind": "argument",
                    "name": parameter.name,
                    "required": parameter.required,
                    "multiple": parameter.nargs != 1,
                }
            )
    commands = []
    if isinstance(current, click.Group):
        commands = [
            {"name": name, "help": child.get_short_help_str()}
            for name in current.list_commands(click.Context(current))
            if (child := current.get_command(click.Context(current), name)) is not None
            and not child.hidden
        ]
    command_name = " ".join(["compshare", *path])
    return {
        "command_path": command_name,
        "help": current.help,
        "parameters": parameters,
        "commands": commands,
    }


def _requested_language(argv: List[str]) -> Optional[str]:
    """Return the last root --lang value before the command, if present."""
    requested: Optional[str] = None
    index = 0
    while index < len(argv):
        option = argv[index]
        if option == "--lang":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return requested
            requested = argv[index + 1]
            index += 2
            continue
        if option.startswith("--lang="):
            requested = option.split("=", 1)[1]
            index += 1
            continue
        if option == "--profile":
            index += 2
            continue
        if option.startswith("--profile=") or option in {
            "--json",
            "--show-sensitive",
            "--version",
            "-h",
            "--help",
        }:
            index += 1
            continue
        if not option.startswith("-"):
            break
        index += 1
    return requested


def main(args: Optional[List[str]] = None) -> None:
    original_argv = list(sys.argv[1:] if args is None else args)
    argv = list(original_argv)
    if not argv:
        argv = ["-h"]
    telemetry_command: Optional[str] = None
    json_output = _global_flag_requested(argv, "--json")
    show_sensitive = _global_flag_requested(argv, "--show-sensitive")
    try:
        argv = _normalize_global_options(argv)
        requested_language = _requested_language(argv)
        if requested_language is None:
            language = configured_language()
        else:
            language = normalize_language(requested_language)
            ConfigStore().save_language(language)
        command = localize_command(get_command(app), language)
        telemetry_command = _command_path(command, argv)
        if json_output and _json_help_requested(argv):
            Renderer(True, show_sensitive).data(_json_help_payload(command, argv))
            result = None
        else:
            result = command.main(args=argv, prog_name="compshare", standalone_mode=False)
    except ConfigError as error:
        Renderer(json_output, show_sensitive).coded_error("configuration_error", str(error))
        raise SystemExit(2) from error
    except UsageError as error:
        Renderer(json_output, show_sensitive).coded_error("invalid_usage", str(error))
        raise SystemExit(2) from error
    except CLIError as error:
        Renderer(json_output, show_sensitive).coded_error("cli_error", str(error))
        raise SystemExit(2) from error
    except _CLICK_EXCEPTIONS as error:
        message = error.format_message()
        Renderer(json_output, show_sensitive).coded_error("invalid_usage", message)
        raise SystemExit(error.exit_code) from error
    except _ABORT_EXCEPTIONS as error:
        Renderer(json_output, show_sensitive).coded_error("aborted", tr("Aborted"))
        raise SystemExit(1) from error
    finally:
        if telemetry_command:
            record_command(telemetry_command)
    if isinstance(result, int) and result:
        raise SystemExit(result)


if __name__ == "__main__":
    main()
