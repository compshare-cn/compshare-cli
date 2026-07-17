from __future__ import annotations

import os
import shutil
import stat
import sys
from importlib import metadata
from typing import Any, Dict, List

import typer

from compshare_cli.api import call_captured
from compshare_cli.config import ConfigStore
from compshare_cli.i18n import tr
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime


def _check(name: str, status: str, detail: str) -> Dict[str, Any]:
    return {"Check": name, "Status": status, "Detail": detail}


def run(state: Runtime) -> None:
    """Run read-only installation, credential, API and OpenSSH diagnostics."""
    checks: List[Dict[str, Any]] = []
    version = ".".join(str(part) for part in sys.version_info[:3])
    python_ok = sys.version_info >= (3, 9)
    checks.append(
        _check(
            "Python",
            "Success" if python_ok else "Failed",
            tr("Version {version}; Python 3.9 or newer is required.", version=version),
        )
    )

    try:
        sdk_version = metadata.version("ucloud-sdk-python3")
    except metadata.PackageNotFoundError:
        sdk_version = tr("not installed")
    checks.append(
        _check(
            "SDK",
            "Success" if sdk_version != tr("not installed") else "Failed",
            sdk_version,
        )
    )

    store = ConfigStore()
    profile, profile_error = None, None
    try:
        profile = state.profile
    except Exception as error:
        profile_error = str(error)
    checks.append(
        _check(
            "Credentials",
            "Success" if profile is not None else "Failed",
            tr("Credential profile loaded")
            if profile is not None
            else profile_error or tr("Unknown error"),
        )
    )

    if store.path.exists():
        file_mode = stat.S_IMODE(store.path.stat().st_mode)
        directory_mode = stat.S_IMODE(store.path.parent.stat().st_mode)
        permissions_ok = file_mode & 0o077 == 0 and directory_mode & 0o077 == 0
        detail = tr(
            "Config {path}: file {file_mode}, directory {directory_mode}",
            path=store.path,
            file_mode=oct(file_mode),
            directory_mode=oct(directory_mode),
        )
        checks.append(_check("Permissions", "Success" if permissions_ok else "Failed", detail))
    elif os.environ.get("COMPSHARE_PUBLIC_KEY") and os.environ.get("COMPSHARE_PRIVATE_KEY"):
        checks.append(_check("Permissions", "Success", tr("Using environment credentials")))
    else:
        checks.append(
            _check(
                "Permissions",
                "Failed",
                tr("Config file does not exist: {path}", path=store.path),
            )
        )

    if profile is not None:
        response, error = call_captured(
            state,
            "DescribeCompShareSupportZone",
            {},
        )
        if error:
            checks.append(_check("API", "Failed", str(error.get("message"))))
        else:
            zone_count = len((response or {}).get("ZoneInfo") or [])
            checks.append(
                _check(
                    "API",
                    "Success",
                    tr("Connected; {count} availability zones returned.", count=zone_count),
                )
            )
    else:
        checks.append(_check("API", "Failed", tr("Skipped because credentials are unavailable")))

    for executable in ("ssh", "scp"):
        path = shutil.which(executable)
        checks.append(
            _check(
                executable,
                "Success" if path else "Warning",
                path or tr("not installed; remote access commands may be unavailable"),
            )
        )

    ok = not any(item["Status"] == "Failed" for item in checks)
    payload = {"ok": ok, "checks": checks}
    Renderer(state.json_output, state.show_sensitive).data(
        payload,
        rows=checks,
        columns=(("Check", "CHECK"), ("Status", "STATUS"), ("Detail", "DETAIL")),
    )
    if not ok:
        raise typer.Exit(1)
