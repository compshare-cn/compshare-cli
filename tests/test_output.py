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
    assert json.loads(output) == {
        "ok": True,
        "schema_version": "1",
        "data": {"value": "中文"},
        "meta": {"ret_code": 0},
    }


def test_json_renderer_writes_utf8_bytes_under_a_gbk_stdout(monkeypatch) -> None:
    raw = BytesIO()
    gbk_stdout = TextIOWrapper(raw, encoding="gbk")
    monkeypatch.setattr(output.sys, "stdout", gbk_stdout)

    Renderer(True).data({"ok": False, "error": "尚未配置 API 密钥。"})

    document = raw.getvalue().decode("utf-8")
    assert json.loads(document) == {
        "ok": False,
        "schema_version": "1",
        "error": {"code": "operation_failed", "message": "尚未配置 API 密钥。"},
    }


def test_json_renderer_reports_redacted_field_paths(capsys) -> None:
    Renderer(True).data({"Password": "secret", "IPSet": [{"IP": "203.0.113.1"}]})

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {"Password": "***", "IPSet": [{"IP": "***"}]}
    assert payload["meta"]["redacted_fields"] == [
        "data.Password",
        "data.IPSet[0].IP",
    ]


def test_json_list_renderer_projects_rows_and_moves_pagination_to_metadata(capsys) -> None:
    Renderer(True).data(
        {
            "Action": "DescribeThingsResponse",
            "RetCode": 0,
            "ThingSet": [{"Id": "one", "Readme": "large"}],
            "TotalCount": 1,
            "ReturnedCount": 1,
            "Offset": 0,
            "Limit": None,
        },
        rows=[{"Id": "one", "Readme": "large"}],
        columns=(("Id", "ID"),),
        json_list=True,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {"items": [{"Id": "one"}]}
    assert payload["meta"] == {
        "action": "DescribeThingsResponse",
        "ret_code": 0,
        "total": 1,
        "returned": 1,
        "offset": 0,
        "all": True,
    }


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
