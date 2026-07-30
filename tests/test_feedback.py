import base64
import json

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from compshare_cli import __version__, cli, insights
from compshare_cli.config import Profile

runner = CliRunner()


def test_feedback_posts_category_and_message(monkeypatch) -> None:
    captured = {}

    def fake_invoke(profile, action, payload):
        captured["profile"] = profile
        captured["action"] = action
        captured["payload"] = payload
        return {"Id": "feedback-7"}

    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "private")
    monkeypatch.setattr(insights, "_invoke", fake_invoke)
    result = runner.invoke(
        cli.app,
        ["--json", "feedback", "bug", "创建实例失败"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "ok": True,
        "schema_version": "1",
        "data": {"id": "feedback-7"},
    }
    assert captured["profile"] == Profile("public", "private")
    assert captured["action"] == "CreateCSCLIFeedback"
    assert captured["payload"]["Category"] == "bug"
    assert captured["payload"]["Content"] == "创建实例失败"
    assert set(captured["payload"]) == {
        "Category",
        "Content",
        "CLIVersion",
        "OS",
        "OccurredAt",
    }


def test_feedback_only_accepts_bug_or_suggest() -> None:
    result = runner.invoke(cli.app, ["feedback", "other", "message"])

    assert result.exit_code == 2
    assert "bug" in result.output
    assert "suggest" in result.output


def test_insights_uses_external_gateway_by_default(monkeypatch) -> None:
    captured = {}

    class FakeSDK:
        def __init__(self, profile, region=None, base_url=None):
            captured["profile"] = profile
            captured["region"] = region
            captured["base_url"] = base_url

        def invoke(self, action, payload):
            captured["action"] = action
            captured["payload"] = payload
            return {"Id": "feedback-8"}

    monkeypatch.delenv("COMPSHARE_INSIGHTS_URL", raising=False)
    monkeypatch.setattr(insights, "CompShareSDK", FakeSDK)
    response = insights.submit_feedback(Profile("public", "private"), "suggest", "建议内容")

    assert response == {"ok": True, "id": "feedback-8"}
    assert captured["base_url"] == "https://api.compshare.cn"
    assert captured["action"] == "CreateCSCLIFeedback"


def test_telemetry_contains_only_requested_fields(monkeypatch) -> None:
    launched = {}

    def fake_popen(args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("COMPSHARE_INSIGHTS_URL", "https://insights.example.test")
    monkeypatch.setattr(insights.subprocess, "Popen", fake_popen)
    insights.record_command("instance.create", "work")

    encoded = launched["args"][-1]
    document = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    assert document["profile_name"] == "work"
    assert document["payload"]["Command"] == "instance.create"
    assert set(document["payload"]) == {"Command", "CLIVersion", "OS", "OccurredAt"}
    assert launched["kwargs"]["stdout"] is insights.subprocess.DEVNULL


def test_event_worker_posts_to_event_endpoint(monkeypatch) -> None:
    captured = {}
    document = {
        "profile_name": "work",
        "payload": {
            "Command": "image.list",
            "CLIVersion": "0.2.1",
            "OS": "linux",
            "OccurredAt": "2026-07-17T10:00:00Z",
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(document).encode("utf-8")).decode("ascii")

    def fake_load_profile(profile_name):
        captured["profile_name"] = profile_name
        return Profile("public", "private")

    def fake_invoke(profile, action, payload):
        captured["profile"] = profile
        captured["action"] = action
        captured["payload"] = payload
        return {"Id": "event-1"}

    monkeypatch.setattr(
        insights.ConfigStore,
        "load_profile",
        lambda self, name: fake_load_profile(name),
    )
    monkeypatch.setattr(insights, "_invoke", fake_invoke)
    insights._send_event(encoded)

    assert captured["profile_name"] == "work"
    assert captured["profile"] == Profile("public", "private")
    assert captured["action"] == "CreateCSCLIEvent"
    assert captured["payload"] == document["payload"]


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


def test_main_passes_selected_profile_to_telemetry(monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(cli, "record_command", lambda *args: calls.append(args))

    cli.main(["--profile", "work", "version"])

    assert capsys.readouterr().out.strip() == __version__
    assert calls == [("version", "work")]
