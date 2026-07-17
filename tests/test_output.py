import json
from io import BytesIO, TextIOWrapper

from compshare_cli import output
from compshare_cli.output import Renderer, sanitized


def test_sensitive_values_are_redacted_recursively() -> None:
    value = {
        "Password": "secret",
        "FileBrowserPassword": "browser-secret",
        "SshLoginCommand": "ssh root@example.invalid",
        "IPSet": [{"IP": "203.0.113.10", "IPId": "ip-resource-id"}],
        "Softwares": [{"Name": "JupyterLab", "URL": "https://example.invalid/token"}],
        "nested": [{"private_key": "key"}],
    }

    assert sanitized(value) == {
        "Password": "***",
        "FileBrowserPassword": "***",
        "SshLoginCommand": "***",
        "IPSet": [{"IP": "***", "IPId": "ip-resource-id"}],
        "Softwares": [{"Name": "JupyterLab", "URL": "***"}],
        "nested": [{"private_key": "***"}],
    }
    assert sanitized(value, show_sensitive=True) is value


def test_json_renderer_emits_one_compact_document(capsys) -> None:
    Renderer(True).data({"RetCode": 0, "value": "中文"})
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    assert json.loads(output) == {"RetCode": 0, "value": "中文"}


def test_json_renderer_writes_utf8_bytes_under_a_gbk_stdout(monkeypatch) -> None:
    raw = BytesIO()
    gbk_stdout = TextIOWrapper(raw, encoding="gbk")
    monkeypatch.setattr(output.sys, "stdout", gbk_stdout)

    Renderer(True).data({"ok": False, "error": "尚未配置 API 密钥。"})

    document = raw.getvalue().decode("utf-8")
    assert json.loads(document) == {"ok": False, "error": "尚未配置 API 密钥。"}


def test_table_accepts_no_rows(capsys) -> None:
    Renderer(False).table(None, (("Id", "ID"),))

    assert capsys.readouterr().out


def test_human_details_require_opt_in_for_sensitive_values(capsys) -> None:
    fields = (("Password", "instance-secret"), ("SSH", "ssh root@example.invalid"))

    Renderer(False).details("Instance details", fields)
    safe_output = capsys.readouterr().out
    Renderer(False, show_sensitive=True).details("Instance details", fields)
    private_output = capsys.readouterr().out

    assert "instance-secret" not in safe_output
    assert "root@example.invalid" not in safe_output
    assert safe_output.count("***") == 2
    assert "instance-secret" in private_output
    assert "root@example.invalid" in private_output


def test_human_details_fold_long_values_without_dropping_the_end(capsys) -> None:
    Renderer(False).details(
        "Answer",
        (("ANSWER", "很长的回答内容" * 40 + "最终结论"),),
    )

    assert "最终结论" in capsys.readouterr().out
