import json
from urllib import error as urlerror

import pytest
from typer.testing import CliRunner

from compshare_cli import __version__, cli, qa
from compshare_cli.errors import CLIError

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


def _answer():
    return {
        "request_id": "request-1",
        "answer": "关机后云硬盘仍会继续收费 [1]。",
        "citations": [
            {
                "number": 1,
                "document_id": "billing-faq",
                "title": "实例计费相关 FAQ",
                "snippet": "This long source excerpt is JSON-only.",
            }
        ],
        "outcome": "answered",
        "model": "deepseek-v4-flash",
    }


def test_ask_posts_only_the_question_and_preserves_json_response(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(_answer())

    monkeypatch.setattr(qa.request, "urlopen", fake_urlopen)
    result = runner.invoke(
        cli.app,
        ["--json", "ask", "按量实例关机以后，云硬盘还收费吗？"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "ok": True,
        "schema_version": "1",
        "data": _answer(),
    }
    assert captured == {
        "url": "http://117.50.180.139:55089/v1/answer",
        "method": "POST",
        "headers": {
            "Accept": "application/json",
            "Content-type": "application/json",
            "User-agent": f"compshare-cli/{__version__}",
        },
        "payload": {"question": "按量实例关机以后，云硬盘还收费吗？"},
        "timeout": 60.0,
    }


def test_ask_human_output_shows_answer_and_source_titles(monkeypatch) -> None:
    monkeypatch.setattr(qa.request, "urlopen", lambda *args, **kwargs: FakeResponse(_answer()))

    result = runner.invoke(cli.app, ["ask", "云硬盘还收费吗？"])

    assert result.exit_code == 0, result.output
    assert "关机后云硬盘仍会继续收费" in result.stdout
    assert "实例计费相关 FAQ" in result.stdout
    assert "This long source excerpt is JSON-only." not in result.stdout


def test_ask_rejects_an_empty_question() -> None:
    with pytest.raises(CLIError, match="不能为空|cannot be empty"):
        qa.ask_question("   ")


def test_ask_empty_question_is_a_json_cli_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "record_command", lambda command: None)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "ask", "   "])

    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli_error"
    assert "问题不能为空" in payload["error"]["message"]


def test_ask_reports_http_and_invalid_response_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        qa.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            urlerror.HTTPError(qa.ANSWER_URL, 503, "Unavailable", {}, None)
        ),
    )
    with pytest.raises(CLIError, match="503"):
        qa.ask_question("问题")

    class InvalidResponse(FakeResponse):
        def read(self):
            return b"not json"

    monkeypatch.setattr(qa.request, "urlopen", lambda *args, **kwargs: InvalidResponse({}))
    with pytest.raises(CLIError, match="无效响应|invalid response"):
        qa.ask_question("问题")
