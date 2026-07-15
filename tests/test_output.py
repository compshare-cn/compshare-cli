import json

from compshare_cli.output import Renderer, sanitized


def test_sensitive_values_are_redacted_recursively() -> None:
    assert sanitized(
        {
            "Password": "secret",
            "nested": [{"private_key": "key"}, {"FILEBROWSERPASSWORD": "pass"}],
        }
    ) == {
        "Password": "secret",
        "nested": [{"private_key": "***"}, {"FILEBROWSERPASSWORD": "pass"}],
    }


def test_json_renderer_emits_one_compact_document(capsys) -> None:
    Renderer(True).data({"RetCode": 0, "value": "中文"})
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    assert json.loads(output) == {"RetCode": 0, "value": "中文"}
