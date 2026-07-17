from __future__ import annotations

import json
from typing import Any, Dict
from urllib import error as urlerror
from urllib import request

from compshare_cli import __version__
from compshare_cli.errors import CLIError
from compshare_cli.i18n import tr

ANSWER_URL = "http://117.50.180.139:55089/v1/answer"


def ask_question(question: str) -> Dict[str, Any]:
    normalized = question.strip()
    if not normalized:
        raise CLIError(tr("Question cannot be empty."))

    body = json.dumps(
        {"question": normalized},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    req = request.Request(
        ANSWER_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"compshare-cli/{__version__}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60.0) as response:
            content = response.read()
    except urlerror.HTTPError as error:
        raise CLIError(
            tr("Question service rejected the request with HTTP {status}.", status=error.code)
        ) from error
    except (urlerror.URLError, TimeoutError, OSError) as error:
        raise CLIError(tr("Unable to reach the question service.")) from error

    try:
        result = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CLIError(tr("Question service returned an invalid response.")) from error
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
        raise CLIError(tr("Question service returned an invalid response."))
    return result
