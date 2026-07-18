from __future__ import annotations

import sys
from typing import Any, Dict, Optional

import click
import typer

from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime


def runtime(ctx: typer.Context) -> Runtime:
    value = ctx.find_root().obj
    if not isinstance(value, Runtime):
        raise RuntimeError("CLI runtime is not initialized")
    return value


def request(
    ctx: typer.Context,
    *,
    zone: bool = False,
    project_id: Optional[str] = None,
    region_value: Optional[str] = None,
    zone_value: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if region_value is not None:
        payload["Region"] = region_value
    if zone:
        if zone_value is None:
            raise UsageError(tr("Zone is required for this request."))
        payload["Zone"] = zone_value
    if project_id:
        payload["ProjectId"] = project_id
    return payload


def confirm(message: str, yes: bool) -> None:
    if yes:
        return

    context = click.get_current_context(silent=True)
    state = context.find_root().obj if context is not None else None
    if isinstance(state, Runtime) and state.json_output:
        raise UsageError(
            tr("JSON mode cannot prompt for confirmation; pass --yes to confirm the operation.")
        )

    prompt = f"{tr(message)} [y/N]: "
    for attempt in range(3):
        typer.echo(prompt, nl=False)
        raw = sys.stdin.readline()
        if raw == "":
            typer.echo()
        answer = raw.strip().casefold()
        if answer in {"y", "yes"}:
            return
        if answer in {"n", "no"}:
            raise typer.Abort()
        if attempt < 2:
            typer.echo(tr("Please enter y or n."))

    raise typer.Abort()


def confirm_details(
    state: Runtime,
    title: str,
    fields: list[tuple[str, Any]],
    prompt: str,
    yes: bool,
) -> None:
    if not state.json_output:
        Renderer(False, state.show_sensitive).details(title, fields)
    confirm(prompt, yes)
