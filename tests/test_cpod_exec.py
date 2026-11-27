import json

import pytest
from typer.testing import CliRunner
from ucloud.core.transport import Response

from compshare_cli import cli
from compshare_cli.commands import instance
from compshare_cli.config import Profile
from compshare_cli.sdk import CompShareSDK

runner = CliRunner()


@pytest.mark.parametrize(
    ("mode", "response", "timeout"),
    [
        ("async", {"RetCode": 0, "TaskId": "task-1"}, 30),
        ("sync", {"RetCode": 0, "Output": "hello\n"}, 1900),
        ("sync", {"RetCode": 226656, "Output": "partial\n"}, 1900),
    ],
)
def test_exec_preserves_script_and_output_without_retries(
    monkeypatch, tmp_path, mode, response, timeout
) -> None:
    sdk = CompShareSDK(Profile("public", "private"))
    calls = []

    def send(request, **options):
        calls.append((request.data, options))
        return Response(
            url=request.url,
            method=request.method,
            content=json.dumps(response).encode(),
        )

    monkeypatch.setattr(sdk._service.transport, "send", send)
    monkeypatch.setattr("compshare_cli.api._sdk", lambda *_: sdk)
    script = tmp_path / "check.sh"
    script_text = "set -e\nprintf '你好\\n'\n"
    script.write_bytes(script_text.encode())
    args = ["--json", "instance", "exec", "cpod-1", "--file", str(script)]
    if mode == "sync":
        args.append("--sync")

    result = runner.invoke(cli.app, args)

    assert len(calls) == 1
    request, options = calls[0]
    assert request["Action"] == "RunCompShareInstanceCommand"
    assert request["InstanceId"] == "cpod-1"
    assert request["Type"] == mode
    assert request["Command"] == script_text
    assert "Region" not in request and "Zone" not in request
    assert options["max_retries"] == 0
    assert options["timeout"] == timeout
    output = json.loads(result.stdout)
    if response["RetCode"] == 0:
        assert result.exit_code == 0, output
        assert output["data"] == {key: value for key, value in response.items() if key != "RetCode"}
    else:
        assert result.exit_code == 1
        assert output["error"]["code"] == "remote_command_failed"
        assert output["error"]["details"] == {"ret_code": 226656, "output": "partial\n"}


@pytest.mark.parametrize(
    ("status", "execution_result"),
    [
        ("Running", None),
        ("Finished", None),
        ("Finished", {"RetCode": 0, "Output": "hello\n"}),
        ("Finished", {"RetCode": 226656, "Output": "partial\n"}),
    ],
)
def test_exec_result_distinguishes_query_success_from_execution_failure(
    monkeypatch, status, execution_result
) -> None:
    def call(state, action, params):
        assert action == "GetCompShareInstanceCommandResult"
        assert params == {"TaskId": "task-1"}
        return {"RetCode": 0, "Status": status, "Result": execution_result}

    monkeypatch.setattr(instance, "call", call)

    result = runner.invoke(cli.app, ["--json", "instance", "exec-result", "task-1"])

    output = json.loads(result.stdout)
    if status == "Finished" and execution_result is None:
        assert result.exit_code == 1
        assert output["error"]["code"] == "invalid_response"
    elif execution_result and execution_result["RetCode"]:
        assert result.exit_code == 1
        assert output["error"]["details"] == {
            "task_id": "task-1",
            "status": "Finished",
            "ret_code": 226656,
            "output": "partial\n",
        }
    else:
        assert result.exit_code == 0
        assert output["data"] == {"Status": status, "Result": execution_result}


@pytest.mark.parametrize(
    "script_bytes",
    [b"", b"echo\x00", b"\xff", b"a" * (256 * 1024 + 1)],
    ids=["empty", "nul", "invalid_utf8", "over_limit"],
)
def test_exec_rejects_invalid_script_before_api_call(
    capsys, monkeypatch, tmp_path, script_bytes
) -> None:
    monkeypatch.setattr(instance, "call", lambda *_: pytest.fail("unexpected API call"))
    script = tmp_path / "check.sh"
    script.write_bytes(script_bytes)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "instance", "exec", "cpod-1", "--file", str(script)])

    assert raised.value.code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_usage"


def test_sync_exec_prints_partial_output_before_failing(monkeypatch) -> None:
    def call(state, action, params):
        assert params == {
            "InstanceId": "cpod-1",
            "Command": "echo before-error; exit 1",
            "Type": "sync",
        }
        return {"RetCode": 226656, "Output": "before-error\n"}

    monkeypatch.setattr(instance, "call", call)

    result = runner.invoke(
        cli.app, ["instance", "exec", "cpod-1", "--sync", "echo before-error; exit 1"]
    )

    assert result.exit_code == 1
    assert result.stdout == "before-error\n"
    assert result.stderr
