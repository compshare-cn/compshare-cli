from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
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

app = typer.Typer(help="Manage MiniMax H3 video, image, and audio tasks.", no_args_is_help=True)

API_BASE_URL = "https://cp.compshare.cn"
API_KEY_ENV = "COMPSHARE_MINIMAX_API_KEY"
CALLBACK_TOKEN_ENV = "COMPSHARE_MINIMAX_CALLBACK_TOKEN"

_RESOLUTIONS = {"480P", "768P", "1080P", "2K", "4K"}
_MODELS = {"MiniMax-H3", "minimax-h3-lite"}
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
        url = f"{url}?{parse.urlencode(query, doseq=True)}"
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
    if len(text) > 7000:
        raise UsageError(tr("Prompt cannot exceed 7000 characters."))
    if (first_frame or last_frame) and (reference_images or reference_videos or reference_audio):
        raise UsageError(tr("Frame inputs cannot be combined with reference inputs."))
    if not text and not (
        first_frame or last_frame or reference_images or reference_videos or reference_audio
    ):
        raise UsageError(tr("Prompt cannot be empty."))
    if sum(map(len, (reference_images, reference_videos, reference_audio))) > 12:
        raise UsageError(tr("At most 12 reference inputs are allowed."))
    if reference_audio and not (reference_images or reference_videos):
        raise UsageError(tr("Reference audio requires a reference image or video."))
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

    items: List[Dict[str, Any]] = []
    if text:
        items.append({"type": "text", "text": text})
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
    prompt: str = typer.Argument("", help="Video prompt; at most 7000 characters."),
    model: str = typer.Option("MiniMax-H3", help="Model: MiniMax-H3 or minimax-h3-lite."),
    resolution: str = typer.Option("768P", help="Output resolution: 480P, 768P, 1080P, 2K, or 4K."),
    duration: int = typer.Option(5, min=4, max=30, help="Video duration in seconds (4-30)."),
    ratio: str = typer.Option("16:9", help="Output ratio or adaptive for media input."),
    first_frame: Optional[str] = typer.Option(None, help="First-frame image URL or Data URL."),
    last_frame: Optional[str] = typer.Option(None, help="Last-frame image URL or Data URL."),
    reference_images: Optional[List[str]] = typer.Option(
        None, "--reference-image", help="Reference image URL or Data URL; repeatable."
    ),
    reference_videos: Optional[List[str]] = typer.Option(
        None, "--reference-video", help="Reference video URL or Data URL; repeatable."
    ),
    reference_audio: Optional[List[str]] = typer.Option(
        None, "--reference-audio", help="Reference audio URL or Data URL; repeatable."
    ),
    context_ir: bool = typer.Option(
        False,
        "--context-ir/--no-context-ir",
        help="Enable Context-IR prompt optimization.",
    ),
    skill_id: Optional[str] = typer.Option(None, help="Skill ID; requires --context-ir."),
    mute_audio: bool = typer.Option(False, "--mute-audio", help="Remove the video audio track."),
    watermark: bool = typer.Option(False, "--watermark", help="Add an AIGC watermark."),
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
    if model not in _MODELS:
        raise UsageError(tr("Unsupported video model: {model}.", model=model))
    if resolution not in _RESOLUTIONS:
        raise UsageError(tr("--resolution must be 480P, 768P, 1080P, 2K, or 4K."))
    if ratio not in _RATIOS:
        raise UsageError(tr("Unsupported video ratio: {ratio}.", ratio=ratio))
    if skill_id and not context_ir:
        raise UsageError(tr("--skill-id requires --context-ir."))
    references = (
        reference_images or [],
        reference_videos or [],
        reference_audio or [],
    )
    content = _content(prompt, first_frame, last_frame, *references)
    key = _new_key(idempotency_key)
    payload: Dict[str, Any] = {
        "model": model,
        "content": content,
        "resolution": resolution,
        "duration": duration,
        "ratio": ratio,
        "aigc_watermark": watermark,
    }
    if context_ir:
        payload["use_context_ir"] = True
    if skill_id:
        payload["skill_id"] = skill_id
    if mute_audio:
        payload["mute_audio"] = True
    if callback_url:
        payload["callback_url"] = callback_url
        callback_token = os.environ.get(CALLBACK_TOKEN_ENV, "").strip()
        if callback_token:
            payload["callback_token"] = callback_token

    plan = {"dry_run": dry_run, "idempotency_key": key, "request": payload}
    fields = [
        ("MODEL", model),
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
    model: Optional[str] = typer.Option(None, help="Filter by model."),
) -> None:
    state = runtime(ctx)
    normalized_status = status.casefold() if status else None
    if normalized_status and normalized_status not in _STATUSES:
        raise UsageError(tr("Unsupported task status: {status}.", status=status))
    if model and model not in _MODELS:
        raise UsageError(tr("Unsupported video model: {model}.", model=model))
    query: Dict[str, Any] = {"page_num": page, "page_size": page_size}
    if normalized_status:
        query["filter.status"] = normalized_status
    if model:
        query["filter.model"] = model
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


def _new_key(value: Optional[str]) -> str:
    key = (value or str(uuid.uuid4())).strip()
    if not 1 <= len(key) <= 128:
        raise UsageError(tr("Idempotency key must contain 1-128 characters."))
    return key


def _submit_task(
    state: Runtime,
    path: str,
    payload: Dict[str, Any],
    key: str,
    dry_run: bool,
    yes: bool,
    fields: List[tuple[str, Any]],
) -> None:
    renderer = Renderer(state.json_output, state.show_sensitive)
    if dry_run:
        renderer.details(
            "Create plan",
            fields,
            response={"dry_run": True, "idempotency_key": key, "request": payload},
        )
        return
    confirm_details(state, "Create plan", fields, "Confirm this operation?", yes)
    response = _request(state, "POST", path, body=payload, idempotency_key=key)
    renderer.details(
        "Operation submitted",
        [("TASK ID", response.get("task_id")), ("IDEMPOTENCY KEY", key)],
        response={**response, "idempotency_key": key},
    )


def _media_task_path(prefix: str, task_id: str) -> str:
    return f"{prefix}/{parse.quote(task_id, safe='')}"


def _media_action(state: Runtime, prefix: str, task_id: str, action: str, yes: bool) -> None:
    path = _media_task_path(prefix, task_id)
    current = _request(state, "GET", path)
    task = current.get("task") if isinstance(current.get("task"), dict) else {}
    confirm_details(
        state,
        "Operation plan",
        [("TASK ID", task_id), ("STATUS", task.get("status")), ("ACTION", action)],
        "Confirm this operation?",
        yes,
    )
    method, target = ("POST", f"{path}/cancel") if action == "cancel" else ("DELETE", path)
    response = _request(state, method, target)
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation submitted",
        [("TASK ID", response.get("task_id", task_id)), ("ACTION", action)],
        response=response,
    )


def _upload_asset(
    state: Runtime,
    kind: str,
    file: Path,
    content_type: str,
    limit: int,
    extra: Dict[str, int],
    yes: bool,
) -> None:
    try:
        size = file.stat().st_size
    except OSError as error:
        raise UsageError(str(error)) from error
    if not 0 < size <= limit:
        raise UsageError(tr("File size must be between 1 and {maximum} bytes.", maximum=limit))
    confirm_details(
        state,
        "Upload plan",
        [("FILE", str(file)), ("SIZE", size), ("CONTENT TYPE", content_type)],
        "Confirm this operation?",
        yes,
    )
    details: Dict[str, Any] = {
        "file_name": file.name,
        "content_type": content_type,
        "file_size": size,
    }
    response = _request(state, "POST", f"/{kind}/v1/upload_urls", body=details)
    upload_url = response.get("upload_url")
    object_key = response.get("object_key")
    if not isinstance(upload_url, str) or parse.urlsplit(upload_url).scheme != "https":
        _fail(state, "invalid_response", tr("API returned an invalid upload URL."))
    if not isinstance(object_key, str) or not object_key:
        _fail(state, "invalid_response", tr("API returned no upload object key."))
    headers = {"Content-Type": content_type}
    if kind == "image":
        for field, header in (
            ("authorization", "Authorization"),
            ("bucket", "bucket"),
            ("region", "ufile_indicated_region"),
        ):
            value = response.get(field)
            if not isinstance(value, str) or not value:
                _fail(state, "invalid_response", tr("API returned incomplete upload credentials."))
            headers[header] = value
    try:
        data = file.read_bytes()
        if len(data) != size:
            raise UsageError(tr("File changed while preparing the upload."))
        req = request.Request(upload_url, data=data, headers=headers, method="PUT")
        with request.urlopen(req, timeout=120.0) as uploaded:
            uploaded.read()
    except urlerror.HTTPError as error:
        _fail(
            state,
            "upload_error",
            tr("Reference upload failed with HTTP {status}.", status=error.code),
            {"http_status": error.code},
        )
    except (urlerror.URLError, TimeoutError, OSError) as error:
        _fail(
            state,
            "upload_error",
            tr("Unable to upload the reference file."),
            {"reason": str(error)},
        )
    registered = _request(
        state,
        "POST",
        f"/{kind}/v1/assets",
        body={**details, "object_key": object_key, **extra},
    )
    Renderer(state.json_output, state.show_sensitive).data(registered)


image_app = typer.Typer(help="Generate images and manage image tasks.", no_args_is_help=True)
app.add_typer(image_app, name="image")

_IMAGE_PATH = "/image/v1/tasks"
_IMAGE_RATIOS = {"1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"}
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_IMAGE_COLUMNS = (
    ("task_id", "TASK ID"),
    ("status", "STATUS"),
    ("point_cost", "POINTS"),
    ("created_at", "CREATED"),
)


@image_app.command("config", help="Show image generation availability and prices.")
def image_config(ctx: typer.Context) -> None:
    state = runtime(ctx)
    Renderer(state.json_output, state.show_sensitive).data(
        _request(state, "GET", "/image/v1/config")
    )


@image_app.command("create", help="Create a Qwen-Image task.")
def image_create(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Image prompt; at most 7000 characters."),
    resolution: str = typer.Option("2K", help="Image resolution: 1K or 2K."),
    ratio: str = typer.Option("1:1", help="Image aspect ratio."),
    reference_assets: Optional[List[str]] = typer.Option(
        None, "--reference-asset", help="Registered reference image asset ID; repeatable."
    ),
    optimize_prompt: bool = typer.Option(False, "--optimize-prompt", help="Optimize the prompt."),
    idempotency_key: Optional[str] = typer.Option(None, help="Idempotency key."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    text = prompt.strip()
    if not text or len(prompt) > 7000:
        raise UsageError(tr("Image prompt must contain 1-7000 characters."))
    if resolution not in {"1K", "2K"}:
        raise UsageError(tr("Image resolution must be 1K or 2K."))
    if ratio not in _IMAGE_RATIOS:
        raise UsageError(tr("Unsupported image ratio: {ratio}.", ratio=ratio))
    if len(reference_assets or []) > 10:
        raise UsageError(tr("At most 10 reference images are allowed."))
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "resolution": resolution,
        "aspect_ratio": ratio,
        "optimize_prompt": optimize_prompt,
    }
    if reference_assets:
        payload["reference_images"] = [{"asset_id": value} for value in reference_assets]
    state = runtime(ctx)
    _submit_task(
        state,
        _IMAGE_PATH,
        payload,
        _new_key(idempotency_key),
        dry_run,
        yes,
        [("RESOLUTION", resolution), ("RATIO", ratio), ("REFERENCES", len(reference_assets or []))],
    )


@image_app.command("show", help="Show an image task.")
def image_show(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    state = runtime(ctx)
    response = _request(state, "GET", _media_task_path(_IMAGE_PATH, task_id))
    task = response.get("task") if isinstance(response.get("task"), dict) else {}
    Renderer(state.json_output, state.show_sensitive).details(
        "Image task",
        [
            ("TASK ID", task.get("task_id", task_id)),
            ("STATUS", task.get("status")),
            ("POINTS", task.get("point_cost")),
            ("OUTPUT URL", task.get("output_url")),
            ("ERROR", task.get("error_message")),
        ],
        response=response,
    )


@image_app.command("list", help="List image tasks.")
def image_list(
    ctx: typer.Context,
    offset: int = typer.Option(0, min=0),
    limit: int = typer.Option(20, min=1, max=100),
    statuses: Optional[List[str]] = typer.Option(None, "--status", help="Task status; repeatable."),
    sort: str = typer.Option("latest", help="latest or oldest."),
) -> None:
    if sort not in {"latest", "oldest"}:
        raise UsageError(tr("Sort must be latest or oldest."))
    state = runtime(ctx)
    query: Dict[str, Any] = {"offset": offset, "limit": limit, "sort": sort}
    if statuses:
        query["statuses"] = statuses
    response = _request(state, "GET", _IMAGE_PATH, query=query)
    rows = response.get("items") if isinstance(response.get("items"), list) else []
    Renderer(state.json_output, state.show_sensitive).data(
        response, rows=rows, columns=_IMAGE_COLUMNS
    )


@image_app.command("cancel", help="Cancel a queued image task.")
def image_cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _media_action(runtime(ctx), _IMAGE_PATH, task_id, "cancel", yes)


@image_app.command("delete", help="Delete a finished image task and its output.")
def image_delete(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _media_action(runtime(ctx), _IMAGE_PATH, task_id, "delete", yes)


@image_app.command("upload", help="Upload and register a reference image.")
def image_upload(
    ctx: typer.Context,
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    width: int = typer.Option(..., min=1, help="Actual image width in pixels."),
    height: int = typer.Option(..., min=1, help="Actual image height in pixels."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    content_type = _IMAGE_MIME.get(file.suffix.lower())
    if not content_type:
        raise UsageError(tr("Image file must be JPG, PNG, or WebP."))
    _upload_asset(
        runtime(ctx),
        "image",
        file,
        content_type,
        30 * 1024 * 1024,
        {"width": width, "height": height},
        yes,
    )


audio_app = typer.Typer(help="Generate speech and manage audio tasks.", no_args_is_help=True)
app.add_typer(audio_app, name="audio")

_AUDIO_PATH = "/audio/v1/speech/jobs"
_AUDIO_LANGUAGES = {"ZH", "EN", "JA", "ES", "AR"}
_AUDIO_MIME = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}
_AUDIO_COLUMNS = (
    ("task_id", "TASK ID"),
    ("status", "STATUS"),
    ("point_cost", "POINTS"),
    ("created_at", "CREATED"),
)
_VOICE_COLUMNS = (
    ("voice_id", "VOICE ID"),
    ("kind", "KIND"),
    ("name", "NAME"),
    ("language", "LANGUAGE"),
)


@audio_app.command("pricing", help="Show speech pricing and point balance.")
def audio_pricing(ctx: typer.Context) -> None:
    state = runtime(ctx)
    Renderer(state.json_output, state.show_sensitive).data(
        _request(state, "GET", "/audio/v1/pricing")
    )


@audio_app.command("voices", help="List preset or custom voices.")
def audio_voices(
    ctx: typer.Context,
    kind: str = typer.Option("preset", help="preset or custom."),
) -> None:
    if kind not in {"preset", "custom"}:
        raise UsageError(tr("Voice kind must be preset or custom."))
    state = runtime(ctx)
    response = _request(state, "GET", "/audio/v1/voices", query={"kind": kind})
    rows = response.get("items") if isinstance(response.get("items"), list) else []
    Renderer(state.json_output, state.show_sensitive).data(
        response, rows=rows, columns=_VOICE_COLUMNS
    )


def _emotion_values(raw: str, mode: Optional[str]) -> List[float]:
    try:
        values = [float(part.strip()) for part in raw.split(",")]
    except ValueError as error:
        raise UsageError(tr("Emotion vector must contain eight numbers.")) from error
    if len(values) != 8 or any(not 0 <= value <= 0.8 for value in values):
        raise UsageError(tr("Emotion vector must contain eight values between 0 and 0.8."))
    if not 0 < sum(values) <= 0.8:
        raise UsageError(tr("Emotion vector sum must be greater than 0 and at most 0.8."))
    if mode == "single" and sum(value > 0 for value in values) != 1:
        raise UsageError(tr("Single emotion mode requires exactly one nonzero value."))
    return values


def _pronunciation_rules(raw: Sequence[str]) -> List[Dict[str, str]]:
    if len(raw) > 100:
        raise UsageError(tr("At most 100 pronunciation rules are allowed."))
    rules: List[Dict[str, str]] = []
    seen = set()
    for item in raw:
        parts = item.split(":", 2)
        if len(parts) != 3:
            raise UsageError(tr("Pronunciation must be WORD:KIND:VALUE."))
        word, kind, value = (part.strip() for part in parts)
        if not 1 <= len(word) <= 64 or kind not in {"pinyin", "alias", "cmu", "kana"}:
            raise UsageError(tr("Invalid pronunciation word or kind."))
        if not 1 <= len(value) <= 512 or word in seen:
            raise UsageError(tr("Invalid or duplicate pronunciation rule."))
        seen.add(word)
        rules.append({"word": word, "kind": kind, "value": value})
    return rules


@audio_app.command("create", help="Create an IndexTTS 2.5 speech task.")
def audio_create(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Speech text; at most 2000 characters."),
    voice_source: str = typer.Option("preset", help="preset, custom, or asset."),
    voice_id: Optional[str] = typer.Option(None, help="Preset or custom voice ID."),
    asset_id: Optional[str] = typer.Option(None, help="Registered reference audio asset ID."),
    language: str = typer.Option("ZH", help="ZH, EN, JA, ES, or AR."),
    speed: float = typer.Option(1.0, min=0, max=2.0, help="Speech speed (0 or 0.5-2.0)."),
    auto_emotion: bool = typer.Option(True, "--auto-emotion/--no-auto-emotion"),
    emotion_description: Optional[str] = typer.Option(None, help="Emotion description."),
    emotion_strength: float = typer.Option(0.8, min=0, max=1, help="Emotion strength (0-1)."),
    emotion_vector: Optional[str] = typer.Option(
        None, help="Eight comma-separated emotion values."
    ),
    emotion_vector_mode: Optional[str] = typer.Option(None, help="single or mixed."),
    pronunciations: Optional[List[str]] = typer.Option(
        None, "--pronunciation", help="WORD:KIND:VALUE; repeatable."
    ),
    save_voice: bool = typer.Option(False, "--save-voice", help="Save asset as a custom voice."),
    voice_name: Optional[str] = typer.Option(None, help="Name for a saved custom voice."),
    idempotency_key: Optional[str] = typer.Option(None, help="Idempotency key."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if len(text) > 2000 or not any(char.isalpha() or char.isdecimal() for char in text):
        raise UsageError(tr("Speech text must contain 1-2000 characters of letters or digits."))
    if language not in _AUDIO_LANGUAGES:
        raise UsageError(tr("Unsupported speech language: {language}.", language=language))
    if not math.isfinite(speed) or (speed != 0 and not 0.5 <= speed <= 2.0):
        raise UsageError(tr("Speech speed must be 0 or between 0.5 and 2.0."))
    if not math.isfinite(emotion_strength) or not 0 <= emotion_strength <= 1:
        raise UsageError(tr("Emotion strength must be between 0 and 1."))
    if voice_source not in {"preset", "custom", "asset"}:
        raise UsageError(tr("Voice source must be preset, custom, or asset."))
    if voice_source == "asset":
        if not asset_id or voice_id:
            raise UsageError(tr("Asset voice requires --asset-id and no --voice-id."))
        voice = {"source": "asset", "asset_id": asset_id}
    else:
        if not voice_id or asset_id:
            raise UsageError(tr("Preset or custom voice requires --voice-id and no --asset-id."))
        voice = {"source": voice_source, "voice_id": voice_id}
    if save_voice and (
        voice_source != "asset" or not voice_name or not 1 <= len(voice_name.strip()) <= 64
    ):
        raise UsageError(tr("--save-voice requires an asset voice and a name of 1-64 characters."))
    if voice_name and not save_voice:
        raise UsageError(tr("--voice-name requires --save-voice."))
    if emotion_description and len(emotion_description) > 200:
        raise UsageError(tr("Emotion description cannot exceed 200 characters."))
    if emotion_vector_mode and emotion_vector_mode not in {"single", "mixed"}:
        raise UsageError(tr("Emotion vector mode must be single or mixed."))
    if emotion_vector_mode and not emotion_vector:
        raise UsageError(tr("Emotion vector mode requires --emotion-vector."))
    if emotion_vector and (auto_emotion or emotion_description):
        raise UsageError(tr("Emotion vector requires --no-auto-emotion and no description."))
    payload: Dict[str, Any] = {
        "text": text,
        "language": language,
        "voice": voice,
        "speed": speed,
        "auto_emotion": auto_emotion,
        "emotion_strength": emotion_strength,
    }
    if emotion_description:
        payload["emotion_description"] = emotion_description
    if emotion_vector:
        payload["emotion_vector"] = _emotion_values(emotion_vector, emotion_vector_mode)
        if emotion_vector_mode:
            payload["emotion_vector_mode"] = emotion_vector_mode
    if pronunciations:
        payload["pronunciations"] = _pronunciation_rules(pronunciations)
    if save_voice:
        payload["save_voice"] = True
        payload["voice_name"] = voice_name.strip() if voice_name else ""
    state = runtime(ctx)
    _submit_task(
        state,
        _AUDIO_PATH,
        payload,
        _new_key(idempotency_key),
        dry_run,
        yes,
        [("LANGUAGE", language), ("VOICE SOURCE", voice_source), ("TEXT LENGTH", len(text))],
    )


@audio_app.command("show", help="Show a speech task.")
def audio_show(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    state = runtime(ctx)
    response = _request(state, "GET", _media_task_path(_AUDIO_PATH, task_id))
    task = response.get("task") if isinstance(response.get("task"), dict) else {}
    Renderer(state.json_output, state.show_sensitive).details(
        "Speech task",
        [
            ("TASK ID", task.get("task_id", task_id)),
            ("STATUS", task.get("status")),
            ("POINTS", task.get("point_cost")),
            ("OUTPUT URL", task.get("output_url")),
            ("ERROR", task.get("error_message")),
        ],
        response=response,
    )


@audio_app.command("list", help="List speech tasks.")
def audio_list(
    ctx: typer.Context,
    offset: int = typer.Option(0, min=0),
    limit: int = typer.Option(20, min=1, max=100),
    statuses: Optional[List[str]] = typer.Option(None, "--status", help="Task status; repeatable."),
) -> None:
    state = runtime(ctx)
    query: Dict[str, Any] = {"offset": offset, "limit": limit}
    if statuses:
        query["statuses"] = statuses
    response = _request(state, "GET", _AUDIO_PATH, query=query)
    rows = response.get("items") if isinstance(response.get("items"), list) else []
    Renderer(state.json_output, state.show_sensitive).data(
        response, rows=rows, columns=_AUDIO_COLUMNS
    )


@audio_app.command("cancel", help="Cancel a queued speech task.")
def audio_cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _media_action(runtime(ctx), _AUDIO_PATH, task_id, "cancel", yes)


@audio_app.command("delete", help="Delete a finished speech task and its output.")
def audio_delete(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _media_action(runtime(ctx), _AUDIO_PATH, task_id, "delete", yes)


@audio_app.command("upload", help="Upload and register reference audio.")
def audio_upload(
    ctx: typer.Context,
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    duration_ms: int = typer.Option(
        ..., min=500, max=15000, help="Actual duration in milliseconds."
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    if len(file.name) > 255:
        raise UsageError(tr("Audio file name cannot exceed 255 characters."))
    content_type = _AUDIO_MIME.get(file.suffix.lower())
    if not content_type:
        raise UsageError(tr("Audio file must be WAV, MP3, FLAC, OGG, or M4A."))
    _upload_asset(
        runtime(ctx),
        "audio",
        file,
        content_type,
        15 * 1024 * 1024,
        {"duration_ms": duration_ms},
        yes,
    )


@audio_app.command("voice-create", help="Save a reference asset as a custom voice.")
def audio_voice_create(
    ctx: typer.Context,
    asset_id: str = typer.Argument(..., help="Registered reference audio asset ID."),
    name: str = typer.Argument(..., help="Custom voice name."),
    idempotency_key: Optional[str] = typer.Option(None, help="Idempotency key."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the request only."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if not 1 <= len(name.strip()) <= 64:
        raise UsageError(tr("Voice name must contain 1-64 characters."))
    state = runtime(ctx)
    key = _new_key(idempotency_key)
    payload = {"asset_id": asset_id, "name": name.strip()}
    fields = [("ASSET ID", asset_id), ("VOICE NAME", name), ("IDEMPOTENCY KEY", key)]
    renderer = Renderer(state.json_output, state.show_sensitive)
    if dry_run:
        renderer.details(
            "Create plan",
            fields,
            response={"dry_run": True, "idempotency_key": key, "request": payload},
        )
        return
    confirm_details(state, "Create plan", fields, "Confirm this operation?", yes)
    response = _request(state, "POST", "/audio/v1/voices", body=payload, idempotency_key=key)
    renderer.data({**response, "idempotency_key": key})


@audio_app.command("voice-delete", help="Delete a custom voice.")
def audio_voice_delete(
    ctx: typer.Context,
    voice_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [("VOICE ID", voice_id), ("ACTION", "delete")],
        "Confirm this operation?",
        yes,
    )
    response = _request(state, "DELETE", _media_task_path("/audio/v1/voices", voice_id))
    Renderer(state.json_output, state.show_sensitive).data(response)


skill_app = typer.Typer(help="Manage MiniMax H3 video Skills.", no_args_is_help=True)
app.add_typer(skill_app, name="skill")
_SKILL_PATH = "/minimax/v2/skills"
_SKILL_COLUMNS = (
    ("id", "SKILL ID"),
    ("name", "NAME"),
    ("official", "OFFICIAL"),
    ("description", "DESCRIPTION"),
)


@skill_app.command("list", help="List official and custom video Skills.")
def skill_list(
    ctx: typer.Context,
    page: int = typer.Option(1, min=1),
    page_size: int = typer.Option(20, min=1, max=100),
    keyword: Optional[str] = typer.Option(None),
) -> None:
    state = runtime(ctx)
    query: Dict[str, Any] = {"page_num": page, "page_size": page_size}
    if keyword:
        query["keyword"] = keyword
    response = _request(state, "GET", _SKILL_PATH, query=query)
    rows = response.get("items") if isinstance(response.get("items"), list) else []
    Renderer(state.json_output, state.show_sensitive).data(
        response, rows=rows, columns=_SKILL_COLUMNS
    )


def _skill_payload(name: str, content: str, description: str) -> Dict[str, str]:
    payload = {"name": name.strip(), "content": content, "description": description.strip()}
    if not payload["name"] or not content.strip():
        raise UsageError(tr("Skill name and content cannot be empty."))
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 64 * 1024:
        raise UsageError(tr("Skill request cannot exceed 64 KiB."))
    return payload


def _save_skill(
    state: Runtime,
    method: str,
    path: str,
    payload: Dict[str, str],
    dry_run: bool,
    yes: bool,
) -> None:
    fields = [("NAME", payload["name"]), ("DESCRIPTION", payload["description"])]
    renderer = Renderer(state.json_output, state.show_sensitive)
    if dry_run:
        renderer.details("Operation plan", fields, response={"dry_run": True, "request": payload})
        return
    confirm_details(state, "Operation plan", fields, "Confirm this operation?", yes)
    renderer.data(_request(state, method, path, body=payload))


@skill_app.command("create", help="Create a custom video Skill.")
def skill_create(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    content: str = typer.Argument(...),
    description: str = typer.Option(""),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _save_skill(
        runtime(ctx), "POST", _SKILL_PATH, _skill_payload(name, content, description), dry_run, yes
    )


@skill_app.command("update", help="Replace a custom video Skill.")
def skill_update(
    ctx: typer.Context,
    skill_id: str = typer.Argument(...),
    name: str = typer.Argument(...),
    content: str = typer.Argument(...),
    description: str = typer.Option(""),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    _save_skill(
        runtime(ctx),
        "PUT",
        _media_task_path(_SKILL_PATH, skill_id),
        _skill_payload(name, content, description),
        dry_run,
        yes,
    )


@skill_app.command("delete", help="Delete a custom video Skill.")
def skill_delete(
    ctx: typer.Context,
    skill_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [("SKILL ID", skill_id), ("ACTION", "delete")],
        "Confirm this operation?",
        yes,
    )
    response = _request(state, "DELETE", _media_task_path(_SKILL_PATH, skill_id))
    Renderer(state.json_output, state.show_sensitive).data(response)
