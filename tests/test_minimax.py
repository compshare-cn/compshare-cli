import io
import json
from urllib import error as urlerror

import pytest
from typer.testing import CliRunner

from compshare_cli import cli
from compshare_cli.commands import minimax

runner = CliRunner()


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def _document(output: str) -> dict:
    payload = json.loads(output)
    assert payload["schema_version"] == "1"
    return payload


@pytest.fixture(autouse=True)
def api_key(monkeypatch) -> None:
    monkeypatch.setenv("COMPSHARE_MINIMAX_API_KEY", "sk-ml-test")


def test_create_posts_content_with_auth_and_idempotency(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured.update(
            url=req.full_url,
            method=req.get_method(),
            headers=dict(req.header_items()),
            body=json.loads(req.data.decode("utf-8")),
            timeout=timeout,
        )
        return FakeResponse({"task_id": "task-1"})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "minimax",
            "create",
            "一只猫在海边奔跑",
            "--resolution",
            "1080P",
            "--duration",
            "6",
            "--reference-image",
            "https://example.com/cat.png",
            "--context-ir",
            "--idempotency-key",
            "video-1",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _document(result.stdout)["data"] == {
        "task_id": "task-1",
        "idempotency_key": "video-1",
    }
    assert captured["url"] == "https://cp.compshare.cn/minimax/v2/video_generation"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 60.0
    assert captured["headers"]["Authorization"] == "Bearer sk-ml-test"
    assert captured["headers"]["Idempotency-key"] == "video-1"
    assert captured["body"] == {
        "model": "MiniMax-H3",
        "content": [
            {"type": "text", "text": "一只猫在海边奔跑"},
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/cat.png"},
                "role": "reference_image",
            },
        ],
        "resolution": "1080P",
        "duration": 6,
        "ratio": "16:9",
        "aigc_watermark": False,
        "use_context_ir": True,
    }


def test_create_dry_run_needs_no_key_and_does_not_call_api(monkeypatch) -> None:
    monkeypatch.delenv("COMPSHARE_MINIMAX_API_KEY")
    monkeypatch.setenv("COMPSHARE_MINIMAX_CALLBACK_TOKEN", "callback-secret")
    monkeypatch.setattr(
        minimax.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("dry run called the API"),
    )
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "minimax",
            "create",
            "海面上的帆船",
            "--idempotency-key",
            "preview-1",
            "--callback-url",
            "https://example.com/callback",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    data = _document(result.stdout)["data"]
    assert data["dry_run"] is True
    assert data["idempotency_key"] == "preview-1"
    assert data["request"]["model"] == "MiniMax-H3"
    assert data["request"]["callback_url"] == "***"
    assert data["request"]["callback_token"] == "***"
    assert "callback-secret" not in result.stdout


def test_list_sends_documented_query_and_preserves_items(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured.update(url=req.full_url, method=req.get_method())
        return FakeResponse(
            {
                "items": [{"id": "task-1", "status": "succeeded"}],
                "total": 1,
            }
        )

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "minimax", "list", "--page", "2", "--page-size", "50", "--status", "succeeded"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "url": (
            "https://cp.compshare.cn/minimax/v2/query/video_generation"
            "?page_num=2&page_size=50&filter.status=succeeded"
        ),
        "method": "GET",
    }
    assert _document(result.stdout)["data"] == {
        "items": [{"id": "task-1", "status": "succeeded"}],
        "total": 1,
    }


@pytest.mark.parametrize(
    ("args", "path", "payload"),
    [
        (
            ["show", "task/1"],
            "/minimax/v2/query/video_generation/task%2F1",
            {"task": {"id": "task/1", "status": "running"}},
        ),
        (
            ["packages"],
            "/minimax/v2/query/point_packages",
            {"items": [], "total": 0},
        ),
        (
            ["points"],
            "/minimax/v2/query/point_usage_summary",
            {"total_points": 100, "reserved_points": 10, "available_points": 90},
        ),
    ],
)
def test_read_commands_use_documented_endpoints(monkeypatch, args, path, payload) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured.update(url=req.full_url, method=req.get_method())
        return FakeResponse(payload)

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(cli.app, ["--json", "minimax", *args])

    assert result.exit_code == 0, result.output
    assert captured == {"url": f"https://cp.compshare.cn{path}", "method": "GET"}
    assert _document(result.stdout)["data"] == payload


def test_cancel_reads_status_before_delete(monkeypatch) -> None:
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.get_method(), req.full_url))
        if req.get_method() == "GET":
            return FakeResponse({"task": {"id": "task-1", "status": "running"}})
        return FakeResponse({"task_id": "task-1", "action": "delete", "status": "running"})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "minimax", "cancel", "task-1", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        ("GET", "https://cp.compshare.cn/minimax/v2/query/video_generation/task-1"),
        ("DELETE", "https://cp.compshare.cn/minimax/v2/video_generation/task-1"),
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["create", "prompt", "--ratio", "adaptive", "--dry-run"],
        ["create", "prompt", "--last-frame", "https://example.com/last.png", "--dry-run"],
        [
            "create",
            "prompt",
            "--first-frame",
            "https://example.com/first.png",
            "--reference-image",
            "https://example.com/reference.png",
            "--dry-run",
        ],
    ],
)
def test_create_rejects_invalid_content_combinations(args) -> None:
    result = runner.invoke(cli.app, ["--json", "minimax", *args])
    assert result.exit_code != 0


def test_missing_api_key_is_a_structured_configuration_error(monkeypatch) -> None:
    monkeypatch.delenv("COMPSHARE_MINIMAX_API_KEY")
    result = runner.invoke(cli.app, ["--json", "minimax", "points"])

    assert result.exit_code == 2
    payload = _document(result.stdout)
    assert payload["error"]["code"] == "configuration_error"
    assert "COMPSHARE_MINIMAX_API_KEY" in payload["error"]["message"]


def test_http_error_preserves_api_details_without_exposing_key(monkeypatch) -> None:
    body = json.dumps(
        {
            "type": "error",
            "error": {"type": "bad_request_error", "message": "invalid request"},
            "request_id": "request-1",
        }
    ).encode()

    def fail(req, timeout):
        raise urlerror.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    monkeypatch.setattr(minimax.request, "urlopen", fail)
    result = runner.invoke(cli.app, ["--json", "minimax", "points"])

    assert result.exit_code == 1
    assert "sk-ml-test" not in result.stdout
    error = _document(result.stdout)["error"]
    assert error["code"] == "api_error"
    assert error["message"] == "invalid request"
    assert error["details"]["http_status"] == 400


def test_http_error_accepts_the_production_string_error_shape(monkeypatch) -> None:
    body = json.dumps({"error": "invalid api key"}).encode()

    def fail(req, timeout):
        raise urlerror.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body))

    monkeypatch.setattr(minimax.request, "urlopen", fail)
    result = runner.invoke(cli.app, ["--json", "minimax", "points"])

    assert result.exit_code == 1
    assert _document(result.stdout)["error"]["message"] == "invalid api key"
