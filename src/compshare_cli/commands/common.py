from __future__ import annotations

from typing import Any, Dict, Optional

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
    if not typer.confirm(tr(message)):
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
