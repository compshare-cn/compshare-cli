import base64
import json
from urllib import parse

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from compshare_cli import __version__, cli, insights

runner = CliRunner()


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_feedback_posts_category_and_message(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data)
        captured["timeout"] = timeout
        return Response({"ok": True, "id": 7})

    monkeypatch.setenv("COMPSHARE_INSIGHTS_URL", "https://insights.example.test/")
    monkeypatch.setattr(insights.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "feedback", "bug", "创建实例失败"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "ok": True,
        "schema_version": "1",
        "data": {"id": 7},
    }
    assert captured["url"] == "https://insights.example.test/v1/feedback"
    assert captured["timeout"] == 5.0
    assert captured["payload"]["category"] == "bug"
    assert captured["payload"]["message"] == "创建实例失败"
    assert set(captured["payload"]) == {"category", "message", "cli_version", "os", "time"}


def test_feedback_only_accepts_bug_or_suggest() -> None:
    result = runner.invoke(cli.app, ["feedback", "other", "message"])

    assert result.exit_code == 2
    assert "bug" in result.output
    assert "suggest" in result.output


def test_feedback_uses_default_service(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return Response({"ok": True})

    monkeypatch.delenv("COMPSHARE_INSIGHTS_URL", raising=False)
    monkeypatch.setattr(insights.request, "urlopen", fake_urlopen)
    result = runner.invoke(cli.app, ["feedback", "suggest", "建议内容"])

    assert result.exit_code == 0, result.output
    assert captured["url"] == "http://117.50.180.139:27299/v1/feedback"


def test_telemetry_contains_only_requested_fields(monkeypatch) -> None:
    launched = {}

    def fake_popen(args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("COMPSHARE_INSIGHTS_URL", "https://insights.example.test")
    monkeypatch.setattr(insights.subprocess, "Popen", fake_popen)
    insights.record_command("instance.create")

    encoded = launched["args"][-1]
    payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    assert payload["command"] == "instance.create"
    assert set(payload) == {"command", "cli_version", "os", "time"}
    assert launched["kwargs"]["stdout"] is insights.subprocess.DEVNULL


def test_event_worker_posts_to_event_endpoint(monkeypatch) -> None:
    captured = {}
    payload = {
        "command": "image.list",
        "cli_version": "0.2.1",
        "os": "linux",
        "time": "2026-07-17T10:00:00Z",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data)
        return Response({"ok": True})

    monkeypatch.setenv("COMPSHARE_INSIGHTS_URL", "https://insights.example.test")
    monkeypatch.setattr(insights.request, "urlopen", fake_urlopen)
    insights._send_event(encoded)

    assert parse.urlparse(captured["url"]).path == "/v1/events"
    assert captured["payload"] == payload


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["version"], "version"),
        (["--json", "instance", "list", "--all"], "instance.list"),
        (["--lang", "en", "instance", "list", "--all"], "instance.list"),
        (
            [
                "--profile",
                "work",
                "team",
                "billing",
                "export",
                "1",
                "--output",
                "orders.csv",
            ],
            "team.billing.export",
        ),
        (["--json", "--show-sensitive", "instance", "show", "uhost-1"], "instance.show"),
        (["ask", "云硬盘还收费吗？"], "ask"),
        (["feedback", "suggest", "message"], "feedback"),
        (["instance", "--help"], None),
        ([], None),
    ],
)
def test_telemetry_resolves_only_command_names(args, expected) -> None:
    assert cli._command_path(get_command(cli.app), args) == expected


def test_main_records_resolved_command(monkeypatch, capsys) -> None:
    commands = []
    monkeypatch.setattr(cli, "record_command", commands.append)

    cli.main(["version"])

    assert capsys.readouterr().out.strip() == __version__
    assert commands == ["version"]
