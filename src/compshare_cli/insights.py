from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict
from urllib import error as urlerror
from urllib import parse, request

from compshare_cli import __version__
from compshare_cli.errors import CLIError
from compshare_cli.i18n import tr

ENDPOINT_ENV = "COMPSHARE_INSIGHTS_URL"
DEFAULT_ENDPOINT = "http://117.50.180.139:27299"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def os_name() -> str:
    value = platform.system().strip().lower()
    return value or sys.platform.lower()


def record_command(command: str) -> None:
    """Report a command in a detached process without delaying or affecting the CLI."""
    if not _base_url():
        return
    payload = {
        "command": command,
        "cli_version": __version__,
        "os": os_name(),
        "time": now(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            [sys.executable, "-m", "compshare_cli.insights", "event", encoded],
            **kwargs,
        )
    except OSError:
        pass


def submit_feedback(category: str, message: str) -> Dict[str, Any]:
    if category not in {"bug", "suggest"}:
        raise CLIError(tr("Feedback category must be bug or suggest."))
    normalized = message.strip()
    if not normalized:
        raise CLIError(tr("Feedback message cannot be empty."))
    if len(normalized) > 2000:
        raise CLIError(tr("Feedback message cannot exceed 2000 characters."))
    if not _base_url():
        raise CLIError(
            tr(
                "Feedback service is not configured; set {variable}.",
                variable=ENDPOINT_ENV,
            )
        )
    return _post(
        "/v1/feedback",
        {
            "category": category,
            "message": normalized,
            "cli_version": __version__,
            "os": os_name(),
            "time": now(),
        },
        timeout=5.0,
    )


def _base_url() -> str:
    value = os.environ.get(ENDPOINT_ENV, DEFAULT_ENDPOINT).strip().rstrip("/")
    if not value:
        return ""
    parsed = parse.urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _post(path: str, payload: Dict[str, Any], *, timeout: float) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = request.Request(
        f"{_base_url()}{path}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"compshare-cli/{__version__}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            content = response.read()
    except urlerror.HTTPError as error:
        raise CLIError(
            tr("Insights service rejected the request with HTTP {status}.", status=error.code)
        ) from error
    except (urlerror.URLError, TimeoutError, OSError) as error:
        raise CLIError(tr("Unable to reach the insights service.")) from error
    if not content:
        return {"ok": True}
    try:
        result = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CLIError(tr("Insights service returned an invalid response.")) from error
    if not isinstance(result, dict):
        raise CLIError(tr("Insights service returned an invalid response."))
    return result


def _send_event(encoded: str) -> None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
        if isinstance(payload, dict) and _base_url():
            _post("/v1/events", payload, timeout=3.0)
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "event":
        _send_event(sys.argv[2])


if __name__ == "__main__":
    main()
