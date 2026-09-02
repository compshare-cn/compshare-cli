from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional, Sequence
from urllib import error as urlerror
from urllib import parse, request

import typer

from compshare_cli import __version__
from compshare_cli.commands.common import confirm_details, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime

app = typer.Typer(help="Manage MiniMax H3 video tasks.", no_args_is_help=True)

API_BASE_URL = "https://cp.compshare.cn"
API_KEY_ENV = "COMPSHARE_MINIMAX_API_KEY"
CALLBACK_TOKEN_ENV = "COMPSHARE_MINIMAX_CALLBACK_TOKEN"

_RESOLUTIONS = {"768P", "1080P", "2K"}
_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled"}
_TASK_COLUMNS = (
    ("id", "TASK ID"),
    ("status", "STATUS"),
    ("resolution", "RESOLUTION"),
    ("duration", "DURATION"),
    ("ratio", "RATIO"),
    ("estimated_remaining_seconds", "REMAINING (s)"),
)
_PACKAGE_COLUMNS = (
    ("id", "PACKAGE ID"),
    ("name", "NAME"),
    ("status", "STATUS"),
    ("total_points", "TOTAL POINTS"),
    ("reserved_points", "RESERVED POINTS"),
    ("available_points", "AVAILABLE POINTS"),
    ("expires_at", "EXPIRES"),
)


def _fail(
    state: Runtime,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    *,
    exit_code: int = 1,
) -> None:
    Renderer(state.json_output, state.show_sensitive).coded_error(code, message, details=details)
    raise typer.Exit(exit_code)


def _api_key(state: Runtime) -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        _fail(
            state,
            "configuration_error",
            tr("Set {environment} to a MiniMax H3 API key.", environment=API_KEY_ENV),
            exit_code=2,
        )
    if not key.startswith("sk-ml-"):
        _fail(
            state,
            "configuration_error",
            tr("{environment} must contain an sk-ml- API key.", environment=API_KEY_ENV),
            exit_code=2,
        )
    return key


def _try_json(content: bytes) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _api_message(payload: Optional[Dict[str, Any]], fallback: str) -> str:
    if payload:
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
        for key in ("Message", "message"):
            if payload.get(key):
                return str(payload[key])
    return fallback


def _request(
    state: Runtime,
    method: str,
    path: str,
    *,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    url = f"{API_BASE_URL}{path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"
    headers = {
        "Accept": "application/json",
        "User-Agent": f"compshare-cli/{__version__}",
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = request.Request(url, data=data, headers=headers, method=method)
    # urllib copies regular headers across redirects; keep the bearer key on the original host.
    req.add_unredirected_header("Authorization", f"Bearer {_api_key(state)}")
    try:
        with request.urlopen(req, timeout=60.0) as response:
            content = response.read()
    except urlerror.HTTPError as error:
        payload = _try_json(error.read())
        details: Dict[str, Any] = {"http_status": error.code}
        if payload is not None:
            details["response"] = payload
        if idempotency_key:
            details["idempotency_key"] = idempotency_key
        _fail(
            state,
            "api_error",
            _api_message(
                payload,
                tr("MiniMax H3 API rejected the request with HTTP {status}.", status=error.code),
            ),
            details,
        )
    except (urlerror.URLError, TimeoutError, OSError) as error:
        details = {"path": path}
        if idempotency_key:
            details["idempotency_key"] = idempotency_key
        _fail(
            state,
            "transport_error",
            tr("Unable to reach the MiniMax H3 API."),
            {**details, "reason": str(error)},
        )

    if not content:
        return {}
    payload = _try_json(content)
    if payload is None:
        _fail(state, "invalid_response", tr("MiniMax H3 API returned an invalid response."))
    if payload.get("type") == "error" or (
        isinstance(payload.get("RetCode"), int) and payload["RetCode"] != 0
    ):
        _fail(
            state,
            "api_error",
            _api_message(payload, tr("MiniMax H3 API rejected the request.")),
            {"response": payload},
        )
    return payload


def _content(
    prompt: str,
    first_frame: Optional[str],
    last_frame: Optional[str],
    reference_images: Sequence[str],
    reference_videos: Sequence[str],
    reference_audio: Sequence[str],
) -> List[Dict[str, Any]]:
    text = prompt.strip()
    if not text:
        raise UsageError(tr("Prompt cannot be empty."))
    if len(text) > 7000:
        raise UsageError(tr("Prompt cannot exceed 7000 characters."))
    if last_frame and not first_frame:
        raise UsageError(tr("--last-frame requires --first-frame."))
    if (first_frame or last_frame) and (reference_images or reference_videos or reference_audio):
        raise UsageError(tr("Frame inputs cannot be combined with reference inputs."))
    limits = (
        (reference_images, 9, "--reference-image"),
        (reference_videos, 3, "--reference-video"),
        (reference_audio, 3, "--reference-audio"),
    )
    for values, maximum, option in limits:
        if len(values) > maximum:
            raise UsageError(
                tr(
                    "{option} may be specified at most {maximum} times.",
                    option=option,
                    maximum=maximum,
                )
            )

    items: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    if first_frame:
        items.append(
            {
                "type": "image_url",
                "image_url": {"url": first_frame},
                "role": "first_frame",
            }
        )
    if last_frame:
        items.append(
            {
                "type": "image_url",
                "image_url": {"url": last_frame},
                "role": "last_frame",
            }
        )
    for url in reference_images:
        items.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
    for url in reference_videos:
        items.append({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"})
    for url in reference_audio:
        items.append({"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"})
    return items


def _task_path(task_id: str, *, query: bool) -> str:
    prefix = "/minimax/v2/query/video_generation" if query else "/minimax/v2/video_generation"
    return f"{prefix}/{parse.quote(task_id, safe='')}"


@app.command("create", help="Create a MiniMax H3 video task.")
def create(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Video prompt; at most 7000 characters."),
    resolution: str = typer.Option("768P", help="Output resolution: 768P, 1080P, or 2K."),
    duration: int = typer.Option(5, min=4, max=15, help="Video duration in seconds (4-15)."),
    ratio: str = typer.Option("16:9", help="Output ratio or adaptive for media input."),
    first_frame: Optional[str] = typer.Option(None, help="Public first-frame image URL."),
    last_frame: Optional[str] = typer.Option(None, help="Public last-frame image URL."),
    reference_images: Optional[List[str]] = typer.Option(
        None, "--reference-image", help="Public reference image URL; repeatable."
    ),
    reference_videos: Optional[List[str]] = typer.Option(
        None, "--reference-video", help="Public reference video URL; repeatable."
    ),
    reference_audio: Optional[List[str]] = typer.Option(
        None, "--reference-audio", help="Public reference audio URL; repeatable."
    ),
    context_ir: bool = typer.Option(
        False,
        "--context-ir/--no-context-ir",
        help="Enable Context-IR prompt optimization.",
    ),
    callback_url: Optional[str] = typer.Option(None, help="Public task callback URL."),
    idempotency_key: Optional[str] = typer.Option(
        None,
        help="Idempotency key; generated automatically when omitted.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the request without creating a video task.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    if resolution not in _RESOLUTIONS:
        raise UsageError(tr("--resolution must be 768P, 1080P, or 2K."))
    if ratio not in _RATIOS:
        raise UsageError(tr("Unsupported video ratio: {ratio}.", ratio=ratio))
    references = (
        reference_images or [],
        reference_videos or [],
        reference_audio or [],
    )
    content = _content(prompt, first_frame, last_frame, *references)
    if len(content) == 1 and ratio == "adaptive":
        raise UsageError(tr("Pure text video generation requires a non-adaptive ratio."))
    key = (idempotency_key or str(uuid.uuid4())).strip()
    if not key:
        raise UsageError(tr("Idempotency key cannot be empty."))
    payload: Dict[str, Any] = {
        "model": "MiniMax-H3",
        "content": content,
        "resolution": resolution,
        "duration": duration,
        "ratio": ratio,
        "aigc_watermark": False,
    }
    if context_ir:
        payload["use_context_ir"] = True
    if callback_url:
        payload["callback_url"] = callback_url
        callback_token = os.environ.get(CALLBACK_TOKEN_ENV, "").strip()
        if callback_token:
            payload["callback_token"] = callback_token

    plan = {"dry_run": dry_run, "idempotency_key": key, "request": payload}
    fields = [
        ("MODEL", "MiniMax-H3"),
        ("RESOLUTION", resolution),
        ("DURATION", f"{duration}s"),
        ("RATIO", ratio),
        ("IDEMPOTENCY KEY", key),
    ]
    if dry_run:
        Renderer(state.json_output, state.show_sensitive).details(
            "Create plan", fields, response=plan
        )
        return
    confirm_details(state, "Create plan", fields, "Confirm this operation?", yes)
    response = _request(
        state,
        "POST",
        "/minimax/v2/video_generation",
        body=payload,
        idempotency_key=key,
    )
    result = {**response, "idempotency_key": key}
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation submitted",
        [("TASK ID", response.get("task_id")), ("IDEMPOTENCY KEY", key)],
        response=result,
    )


@app.command("show", help="Show a MiniMax H3 video task.")
def show(ctx: typer.Context, task_id: str = typer.Argument(..., help="Video task ID.")) -> None:
    state = runtime(ctx)
    response = _request(state, "GET", _task_path(task_id, query=True))
    task = response.get("task") if isinstance(response.get("task"), dict) else {}
    content = task.get("content") if isinstance(task.get("content"), dict) else {}
    Renderer(state.json_output, state.show_sensitive).details(
        "Video task",
        [
            ("TASK ID", task.get("id", task_id)),
            ("STATUS", task.get("status")),
            ("RESOLUTION", task.get("resolution")),
            ("DURATION", task.get("duration")),
            ("RATIO", task.get("ratio")),
            ("PROMPT", content.get("prompt")),
            ("URL", content.get("url")),
            ("ERROR", task.get("error")),
        ],
        response=response,
    )


@app.command("list", help="List MiniMax H3 video tasks.")
def list_tasks(
    ctx: typer.Context,
    page: int = typer.Option(1, "--page", min=1, help="Page number starting at 1."),
    page_size: int = typer.Option(20, min=1, max=100, help="Results per page (1-100)."),
    status: Optional[str] = typer.Option(None, help="Filter by task status."),
) -> None:
    state = runtime(ctx)
    normalized_status = status.casefold() if status else None
    if normalized_status and normalized_status not in _STATUSES:
        raise UsageError(tr("Unsupported task status: {status}.", status=status))
    query: Dict[str, Any] = {"page_num": page, "page_size": page_size}
    if normalized_status:
        query["filter.status"] = normalized_status
    response = _request(
        state,
        "GET",
        "/minimax/v2/query/video_generation",
        query=query,
    )
    rows = response.get("items") if isinstance(response.get("items"), list) else []
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=rows,
        columns=_TASK_COLUMNS,
    )


@app.command("packages", help="List MiniMax H3 point packages.")
def packages(ctx: typer.Context) -> None:
    state = runtime(ctx)
    response = _request(state, "GET", "/minimax/v2/query/point_packages")
    rows = response.get("items") if isinstance(response.get("items"), list) else []
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=rows,
        columns=_PACKAGE_COLUMNS,
    )


@app.command("points", help="Show the MiniMax H3 point balance.")
def points(ctx: typer.Context) -> None:
    state = runtime(ctx)
    response = _request(state, "GET", "/minimax/v2/query/point_usage_summary")
    Renderer(state.json_output, state.show_sensitive).details(
        "Point balance",
        [
            ("TOTAL POINTS", response.get("total_points")),
            ("RESERVED POINTS", response.get("reserved_points")),
            ("AVAILABLE POINTS", response.get("available_points")),
        ],
        response=response,
    )


@app.command("cancel", help="Cancel an unfinished MiniMax H3 video task.")
def cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Video task ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    current = _request(state, "GET", _task_path(task_id, query=True))
    task = current.get("task") if isinstance(current.get("task"), dict) else {}
    confirm_details(
        state,
        "Operation plan",
        [("TASK ID", task_id), ("STATUS", task.get("status"))],
        "Confirm this operation?",
        yes,
    )
    response = _request(state, "DELETE", _task_path(task_id, query=False))
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation submitted",
        [("TASK ID", response.get("task_id", task_id)), ("STATUS", response.get("status"))],
        response=response,
    )
