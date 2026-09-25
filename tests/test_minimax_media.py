import json

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
        return json.dumps(self.payload, ensure_ascii=False).encode()


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("COMPSHARE_MINIMAX_API_KEY", "sk-ml-test")


def test_image_create_sends_documented_payload(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured.update(
            url=req.full_url,
            method=req.get_method(),
            headers=dict(req.header_items()),
            body=json.loads(req.data),
        )
        return FakeResponse({"task_id": "image-1"})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "minimax",
            "image",
            "create",
            "一只猫",
            "--resolution",
            "1K",
            "--ratio",
            "16:9",
            "--reference-asset",
            "asset-1",
            "--optimize-prompt",
            "--idempotency-key",
            "image-key",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://cp.compshare.cn/image/v1/tasks"
    assert captured["method"] == "POST"
    assert captured["headers"]["Idempotency-key"] == "image-key"
    assert captured["body"] == {
        "prompt": "一只猫",
        "resolution": "1K",
        "aspect_ratio": "16:9",
        "optimize_prompt": True,
        "reference_images": [{"asset_id": "asset-1"}],
    }


def test_image_list_repeats_status_query(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return FakeResponse({"items": [], "total": 0})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "minimax", "image", "list", "--status", "queued", "--status", "generating"],
    )
    assert result.exit_code == 0, result.output
    assert captured["url"] == (
        "https://cp.compshare.cn/image/v1/tasks"
        "?offset=0&limit=20&sort=latest&statuses=queued&statuses=generating"
    )


def test_audio_create_sends_voice_and_emotion(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured.update(url=req.full_url, body=json.loads(req.data))
        return FakeResponse({"task_id": "speech-1"})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "minimax",
            "audio",
            "create",
            "欢迎来到重庆",
            "--voice-source",
            "asset",
            "--asset-id",
            "audio-asset",
            "--no-auto-emotion",
            "--emotion-vector",
            "0.4,0,0,0,0,0,0,0.2",
            "--emotion-vector-mode",
            "mixed",
            "--pronunciation",
            "重庆:pinyin:chong2 qing4",
            "--save-voice",
            "--voice-name",
            "我的音色",
            "--idempotency-key",
            "speech-key",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://cp.compshare.cn/audio/v1/speech/jobs"
    assert captured["body"] == {
        "text": "欢迎来到重庆",
        "language": "ZH",
        "voice": {"source": "asset", "asset_id": "audio-asset"},
        "speed": 1.0,
        "auto_emotion": False,
        "emotion_strength": 0.8,
        "emotion_vector": [0.4, 0, 0, 0, 0, 0, 0, 0.2],
        "emotion_vector_mode": "mixed",
        "pronunciations": [{"word": "重庆", "kind": "pinyin", "value": "chong2 qing4"}],
        "save_voice": True,
        "voice_name": "我的音色",
    }


@pytest.mark.parametrize(
    "args",
    [
        ["create", "你好", "--voice-id", "v1", "--asset-id", "a1", "--dry-run"],
        [
            "create",
            "你好",
            "--voice-id",
            "v1",
            "--emotion-vector",
            "0.4,0,0,0,0,0,0,0",
            "--dry-run",
        ],
        ["create", "你好", "--voice-id", "v1", "--pronunciation", "bad", "--dry-run"],
        ["create", "你好", "--voice-id", "v1", "--speed", "nan", "--dry-run"],
    ],
)
def test_audio_create_rejects_invalid_options(args):
    result = runner.invoke(cli.app, ["--json", "minimax", "audio", *args])
    assert result.exit_code != 0


@pytest.mark.parametrize(
    ("kind", "filename", "flags", "upload_response", "register_response"),
    [
        (
            "image",
            "reference.png",
            ["--width", "10", "--height", "20"],
            {
                "upload_url": "https://upload.example.com/reference.png",
                "object_key": "image-key",
                "authorization": "UCloud signed",
                "bucket": "bucket-1",
                "region": "region-1",
            },
            {"reference": {"asset_id": "image-asset"}},
        ),
        (
            "audio",
            "reference.wav",
            ["--duration-ms", "5000"],
            {
                "upload_url": "https://upload.example.com/reference.wav?signature=secret",
                "object_key": "audio-key",
            },
            {"asset": {"asset_id": "audio-asset"}},
        ),
    ],
)
def test_reference_upload_uses_signed_url_then_registers(
    monkeypatch, tmp_path, kind, filename, flags, upload_response, register_response
):
    file = tmp_path / filename
    file.write_bytes(b"test-data")
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.get_method(), req.full_url, dict(req.header_items()), req.data))
        if req.full_url.endswith("/upload_urls"):
            return FakeResponse(upload_response)
        if req.get_method() == "PUT":
            return FakeResponse({})
        return FakeResponse(register_response)

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "minimax", kind, "upload", str(file), *flags, "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert [call[0] for call in calls] == ["POST", "PUT", "POST"]
    assert calls[0][1] == f"https://cp.compshare.cn/{kind}/v1/upload_urls"
    assert calls[1][3] == b"test-data"
    assert "Bearer sk-ml-test" not in str(calls[1])
    assert calls[2][1] == f"https://cp.compshare.cn/{kind}/v1/assets"
    registered = json.loads(calls[2][3])
    assert registered["object_key"] == upload_response["object_key"]
    assert registered["file_size"] == 9
    if kind == "image":
        assert calls[1][2]["Authorization"] == "UCloud signed"
        assert registered["width"] == 10
        assert registered["height"] == 20
    else:
        assert "Authorization" not in calls[1][2]
        assert registered["duration_ms"] == 5000


def test_video_skill_create_uses_documented_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured.update(url=req.full_url, method=req.get_method(), body=json.loads(req.data))
        return FakeResponse({"skill": {"id": "skill-1"}})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "minimax", "skill", "create", "镜头", "保持主体一致", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "url": "https://cp.compshare.cn/minimax/v2/skills",
        "method": "POST",
        "body": {"name": "镜头", "content": "保持主体一致", "description": ""},
    }


@pytest.mark.parametrize(
    ("kind", "action", "method", "suffix"),
    [
        ("image", "cancel", "POST", "/cancel"),
        ("image", "delete", "DELETE", ""),
        ("audio", "cancel", "POST", "/cancel"),
        ("audio", "delete", "DELETE", ""),
    ],
)
def test_media_actions_read_before_mutation(monkeypatch, kind, action, method, suffix):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.get_method(), req.full_url))
        if req.get_method() == "GET":
            return FakeResponse({"task": {"task_id": "task/1", "status": "queued"}})
        return FakeResponse({"task_id": "task/1"})

    monkeypatch.setattr(minimax.request, "urlopen", fake_urlopen)
    result = runner.invoke(cli.app, ["--json", "minimax", kind, action, "task/1", "--yes"])
    assert result.exit_code == 0, result.output
    prefix = "image/v1/tasks" if kind == "image" else "audio/v1/speech/jobs"
    url = f"https://cp.compshare.cn/{prefix}/task%2F1"
    assert calls == [("GET", url), (method, f"{url}{suffix}")]
