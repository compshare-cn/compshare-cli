from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib import parse

from ucloud.core import exc as ucloud_exc

from compshare_cli import __version__
from compshare_cli.config import ConfigStore, Profile
from compshare_cli.errors import CLIError
from compshare_cli.i18n import tr
from compshare_cli.sdk import CompShareSDK

ENDPOINT_ENV = "COMPSHARE_INSIGHTS_URL"
DEFAULT_ENDPOINT = "https://api.compshare.cn"
EVENT_ACTION = "CreateCSCLIEvent"
FEEDBACK_ACTION = "CreateCSCLIFeedback"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def os_name() -> str:
    value = platform.system().strip().lower()
    return value or sys.platform.lower()


def record_command(command: str, profile_name: Optional[str] = None) -> None:
    """Report a command in a detached process without delaying or affecting the CLI."""
    if not _base_url():
        return
    document = {
        "profile_name": profile_name,
        "payload": {
            "Command": command,
            "CLIVersion": __version__,
            "OS": os_name(),
            "OccurredAt": now(),
        },
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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


def submit_feedback(
    profile: Profile,
    category: str,
    message: str,
) -> Dict[str, Any]:
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
    try:
        response = _invoke(
            profile,
            FEEDBACK_ACTION,
            {
                "Category": category,
                "Content": normalized,
                "CLIVersion": __version__,
                "OS": os_name(),
                "OccurredAt": now(),
            },
        )
        feedback_id = response.get("Id") if isinstance(response, dict) else None
        if not feedback_id:
            raise ValueError("missing feedback ID")
        return {"ok": True, "id": feedback_id}
    except ucloud_exc.RetCodeException as error:
        raise CLIError(
            tr(
                "Insights service rejected the request: {detail}",
                detail=error.message or str(error.code),
            )
        ) from error
    except (ucloud_exc.UCloudException, TimeoutError, OSError) as error:
        raise CLIError(tr("Unable to reach the insights service.")) from error
    except Exception as error:
        raise CLIError(tr("Insights service returned an invalid response.")) from error


def _base_url() -> str:
    value = os.environ.get(ENDPOINT_ENV, DEFAULT_ENDPOINT).strip().rstrip("/")
    if not value:
        return ""
    parsed = parse.urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _invoke(profile: Profile, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return CompShareSDK(profile, base_url=_base_url()).invoke(action, payload)


def _send_event(encoded: str) -> None:
    try:
        document = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
        if not isinstance(document, dict) or not _base_url():
            return
        payload = document.get("payload")
        if not isinstance(payload, dict):
            return
        raw_profile_name = document.get("profile_name")
        profile_name = str(raw_profile_name) if raw_profile_name else None
        profile = ConfigStore().load_profile(profile_name)
        _invoke(profile, EVENT_ACTION, payload)
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "event":
        _send_event(sys.argv[2])


if __name__ == "__main__":
    main()
