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
    renderer = Renderer(runtime.json_output)
    retries = 3 if action == "DeleteCompshareDisk" else 0
    attempt = 0
    try:
        while True:
            try:
                response = CompShareSDK(runtime.profile, runtime.region).invoke(action, params)
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
        rows = row_builder(response) if row_builder else response.get(list_key or "", [])
        renderer.data(response, rows=rows, columns=columns)
    return response


def call(runtime: Runtime, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke without rendering, for commands that combine multiple API calls."""
    try:
        return CompShareSDK(runtime.profile, runtime.region).invoke(action, params)
    except CLIError as error:
        Renderer(runtime.json_output).error(str(error))
        raise typer.Exit(1) from error
    except ucloud_exc.RetCodeException as error:
        hint = error_hint(error.action or action, error.code)
        Renderer(runtime.json_output).error(
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
        Renderer(runtime.json_output).error(str(error))
        raise typer.Exit(1) from error
    except Exception as error:
        Renderer(runtime.json_output).error(str(error))
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
        ("GetSoftwareURL", 230): (
            "This production endpoint currently rejects its action; "
            "use instance show or the console."
        ),
    }
    return tr(hints[(action, code)]) if (action, code) in hints else None


def _with_hint(message: str, hint: Optional[str]) -> str:
    return f"{message} {tr('Hint')}: {hint}" if hint else message
