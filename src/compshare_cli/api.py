from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

import typer
from ucloud.core import exc as ucloud_exc

from compshare_cli.errors import CLIError
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
    try:
        response = CompShareSDK(runtime.profile, runtime.region).invoke(action, params)
    except CLIError as error:
        renderer.error(str(error))
        raise typer.Exit(1) from error
    except ucloud_exc.RetCodeException as error:
        renderer.error(
            error.message or str(error),
            details={"action": error.action, "ret_code": error.code},
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
        Renderer(runtime.json_output).error(
            error.message or str(error),
            details={"action": error.action, "ret_code": error.code},
        )
        raise typer.Exit(1) from error
    except ucloud_exc.UCloudException as error:
        Renderer(runtime.json_output).error(str(error))
        raise typer.Exit(1) from error
    except Exception as error:
        Renderer(runtime.json_output).error(str(error))
        raise typer.Exit(1) from error
