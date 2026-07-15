from __future__ import annotations

from typing import Any, Dict, Optional

import typer

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
    zone_value: Optional[str] = None,
) -> Dict[str, Any]:
    state = runtime(ctx)
    payload: Dict[str, Any] = {"Region": state.region}
    if zone:
        payload["Zone"] = zone_value or state.zone
    if project_id:
        payload["ProjectId"] = project_id
    return payload


def confirm(message: str, yes: bool) -> None:
    if yes:
        return
    if not typer.confirm(message):
        raise typer.Abort()
