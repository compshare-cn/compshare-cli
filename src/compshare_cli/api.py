from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

import typer
from ucloud.core import exc as ucloud_exc

from compshare_cli.errors import CLIError
from compshare_cli.i18n import tr
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime
from compshare_cli.sdk import CompShareSDK


def _sdk(runtime: Runtime, params: Dict[str, Any]) -> CompShareSDK:
    raw_region = params.get("Region")
    region = str(raw_region) if raw_region is not None else None
    return CompShareSDK(runtime.profile, region)


def invoke(
    runtime: Runtime,
    action: str,
    params: Dict[str, Any],
    *,
    list_key: Optional[str] = None,
    row_builder: Optional[Callable[[Dict[str, Any]], Iterable[Dict[str, Any]]]] = None,
    columns: Optional[Sequence[Tuple[str, str]]] = None,
    success: Optional[str] = None,
) -> Dict[str, Any]:
    renderer = Renderer(runtime.json_output, runtime.show_sensitive)
    retries = 3 if action == "DeleteCompshareDisk" else 0
    attempt = 0
    try:
        while True:
            try:
                response = _sdk(runtime, params).invoke(action, params)
                break
            except ucloud_exc.RetCodeException as error:
                if error.code == 8434 and attempt < retries:
                    attempt += 1
                    if not runtime.json_output:
                        renderer.console.print(
                            tr(
                                "Resource is still detaching; retrying ({attempt}/{total})...",
                                attempt=attempt,
                                total=retries,
                            )
                        )
                    time.sleep(2 * attempt)
                    continue
                raise
    except CLIError as error:
        renderer.error(str(error))
        raise typer.Exit(1) from error
    except ucloud_exc.RetCodeException as error:
        hint = error_hint(error.action or action, error.code)
        renderer.error(
            _with_hint(error.message or str(error), hint),
            details={
                "action": error.action,
                "ret_code": error.code,
                "request_uuid": error.request_uuid,
                "hint": hint,
            },
        )
        raise typer.Exit(1) from error
    except ucloud_exc.UCloudException as error:
        renderer.error(str(error))
        raise typer.Exit(1) from error
    except Exception as error:  # SDK transport exceptions are not all UCloudException subclasses.
        renderer.error(str(error))
        raise typer.Exit(1) from error

    if success:
        renderer.success(success, response)
    elif list_key is None and row_builder is None:
        renderer.data(response)
    else:
        rows = row_builder(response) if row_builder else response.get(list_key or "") or []
        renderer.data(response, rows=rows, columns=columns)
    return response


def call(runtime: Runtime, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke without rendering, for commands that combine multiple API calls."""
    try:
        return _sdk(runtime, params).invoke(action, params)
    except CLIError as error:
        Renderer(runtime.json_output, runtime.show_sensitive).error(str(error))
        raise typer.Exit(1) from error
    except ucloud_exc.RetCodeException as error:
        hint = error_hint(error.action or action, error.code)
        Renderer(runtime.json_output, runtime.show_sensitive).error(
            _with_hint(error.message or str(error), hint),
            details={
                "action": error.action,
                "ret_code": error.code,
                "request_uuid": error.request_uuid,
                "hint": hint,
            },
        )
        raise typer.Exit(1) from error
    except ucloud_exc.UCloudException as error:
        Renderer(runtime.json_output, runtime.show_sensitive).error(str(error))
        raise typer.Exit(1) from error
    except Exception as error:
        Renderer(runtime.json_output, runtime.show_sensitive).error(str(error))
        raise typer.Exit(1) from error


def call_captured(
    runtime: Runtime,
    action: str,
    params: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Invoke without rendering and return a structured error for batch operations."""
    try:
        return _sdk(runtime, params).invoke(action, params), None
    except CLIError as error:
        return None, {"message": str(error), "action": action}
    except ucloud_exc.RetCodeException as error:
        hint = error_hint(error.action or action, error.code)
        return None, {
            "message": _with_hint(error.message or str(error), hint),
            "action": error.action or action,
            "ret_code": error.code,
            "request_uuid": error.request_uuid,
            "hint": hint,
        }
    except ucloud_exc.UCloudException as error:
        return None, {"message": str(error), "action": action}
    except Exception as error:  # SDK transport exceptions are not all UCloudException subclasses.
        return None, {"message": str(error), "action": action}


def collect_pages(
    runtime: Runtime,
    action: str,
    params: Dict[str, Any],
    list_key: str,
    *,
    offset: int = 0,
    limit: Optional[int] = None,
    page_size: int = 100,
) -> Dict[str, Any]:
    """Collect an offset range or all pages from an offset-based CompShare API."""
    if page_size < 1:
        raise ValueError("page_size must be positive")

    combined: Optional[Dict[str, Any]] = None
    rows: list[Dict[str, Any]] = []
    current_offset = offset
    remaining = limit

    while remaining is None or remaining > 0:
        current_limit = page_size if remaining is None else min(page_size, remaining)
        response = call(
            runtime,
            action,
            {**params, "Limit": current_limit, "Offset": current_offset},
        )
        if combined is None:
            combined = dict(response)
        page = list(response.get(list_key) or [])
        rows.extend(page)
        current_offset += len(page)
        if remaining is not None:
            remaining -= len(page)

        total = response.get("TotalCount")
        if not isinstance(total, int):
            total = response.get("Total")
        if not page or len(page) < current_limit:
            break
        if isinstance(total, int) and current_offset >= total:
            break

    result = combined or {}
    result[list_key] = rows
    result["ReturnedCount"] = len(rows)
    result["Offset"] = offset
    if limit is not None:
        result["Limit"] = limit
    return result


def download_file(
    runtime: Runtime,
    action: str,
    params: Dict[str, Any],
) -> Tuple[bytes, Dict[str, str]]:
    """Download a non-JSON API response while preserving normal CLI error handling."""
    try:
        return _sdk(runtime, params).download(action, params)
    except CLIError as error:
        Renderer(runtime.json_output, runtime.show_sensitive).error(str(error))
        raise typer.Exit(1) from error
    except ucloud_exc.RetCodeException as error:
        hint = error_hint(error.action or action, error.code)
        Renderer(runtime.json_output, runtime.show_sensitive).error(
            _with_hint(error.message or str(error), hint),
            details={
                "action": error.action or action,
                "ret_code": error.code,
                "request_uuid": error.request_uuid,
                "hint": hint,
            },
        )
        raise typer.Exit(1) from error
    except ucloud_exc.UCloudException as error:
        Renderer(runtime.json_output, runtime.show_sensitive).error(str(error))
        raise typer.Exit(1) from error
    except Exception as error:
        Renderer(runtime.json_output, runtime.show_sensitive).error(str(error))
        raise typer.Exit(1) from error


def error_hint(action: str, code: int) -> Optional[str]:
    hints = {
        ("DeleteCompshareDisk", 8434): "The disk is still detaching. Wait a moment and retry.",
        ("AttachUS3", 8433): "Confirm that US3 is enabled for the selected region and account.",
        ("GetCompShareInstanceMonitor", 210): (
            "This production endpoint currently rejects instance IDs; "
            "use the console for monitoring."
        ),
        ("GetCompShareInstanceMonitor", 230): (
            "This production endpoint is currently incompatible; use the console for monitoring."
        ),
    }
    return tr(hints[(action, code)]) if (action, code) in hints else None


def _with_hint(message: str, hint: Optional[str]) -> str:
    return f"{message} {tr('Hint')}: {hint}" if hint else message
