import asyncio
import json
import subprocess

import pytest
from typer.main import get_command

from compshare_cli import __version__, cli, mcp_server
from compshare_cli.mcp_server import (
    CommandKind,
    CompShareRunner,
    MCPBridgeError,
    classify_command,
)


@pytest.mark.parametrize(
    "args",
    [
        ["instance", "list", "--all"],
        ["team", "billing", "summary", "--team", "1"],
        ["instance", "create", "--dry-run"],
        ["instance", "resize", "uhost-1", "--dry-run"],
        ["instance", "job", "prune", "uhost-1", "--dry-run"],
        ["instance", "ssh", "uhost-1", "--print"],
        ["instance", "cp", "uhost-1", "local", ":/remote", "--print"],
    ],
)
def test_classifies_read_and_preview_commands(args) -> None:
    assert classify_command(args) is CommandKind.READ


@pytest.mark.parametrize(
    "args",
    [
        ["instance", "stop", "uhost-1", "--yes"],
        ["instance", "job", "submit", "uhost-1", "--", "python", "train.py"],
        ["instance", "ssh", "uhost-1", "--", "nvidia-smi"],
        ["storage", "disk", "delete", "disk-1", "--yes"],
        ["minimax", "create", "prompt", "--yes"],
    ],
)
def test_classifies_write_commands(args) -> None:
    assert classify_command(args) is CommandKind.WRITE


@pytest.mark.parametrize(
    "args,message",
    [
        (["config", "list"], "managed outside"),
        (["instance", "list", "--show-sensitive"], "managed by the MCP bridge"),
        (["instance", "job", "logs", "uhost-1", "job-1", "--follow"], "not supported"),
        (["instance", "ssh", "uhost-1"], "interactive SSH"),
        (["team", "billing", "export"], "managed outside"),
        (["made-up", "command"], "unsupported"),
    ],
)
def test_rejects_unsafe_or_unsupported_commands(args, message) -> None:
    with pytest.raises(MCPBridgeError, match=message):
        classify_command(args)


def test_remote_command_flags_are_not_treated_as_bridge_flags() -> None:
    assert (
        classify_command(["instance", "ssh", "uhost-1", "--", "echo", "--show-sensitive"])
        is CommandKind.WRITE
    )


def _visible_leaf_commands() -> set[tuple[str, ...]]:
    leaves = set()

    def visit(command, prefix=()) -> None:
        children = getattr(command, "commands", None)
        if not children:
            if not command.hidden:
                leaves.add(prefix)
            return
        for name, child in children.items():
            visit(child, (*prefix, name))

    visit(get_command(cli.app))
    return leaves


def test_command_policy_covers_every_visible_cli_leaf() -> None:
    covered = mcp_server._READ_COMMANDS | mcp_server._WRITE_COMMANDS
    blocked = mcp_server._BLOCKED_COMMAND_PREFIXES
    missing = {
        command
        for command in _visible_leaf_commands()
        if command not in covered
        and not any(command[: len(prefix)] == prefix for prefix in blocked)
    }
    assert missing == set()


def test_runner_forces_json_and_isolates_credentials(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"ok": True, "schema_version": "1", "data": {"items": []}}),
            stderr="",
        )

    monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)
    runner = CompShareRunner(
        command_prefix=["python", "-m", "compshare_cli"],
        environ={
            "PATH": str(tmp_path),
            "COMPSHARE_PUBLIC_KEY": "public-test",
            "COMPSHARE_PRIVATE_KEY": "private-test",
            "UNRELATED_SECRET": "must-not-pass",
        },
    )
    try:
        result = runner.run(
            ["instance", "list", "--all"],
            expected_kind=CommandKind.READ,
            timeout_seconds=30,
        )
    finally:
        runner.close()

    assert result["ok"] is True
    assert captured["command"] == [
        "python",
        "-m",
        "compshare_cli",
        "--json",
        "instance",
        "list",
        "--all",
    ]
    assert captured["env"]["COMPSHARE_PUBLIC_KEY"] == "public-test"
    assert captured["env"]["COMPSHARE_PRIVATE_KEY"] == "private-test"
    assert "UNRELATED_SECRET" not in captured["env"]
    assert "compshare-mcp-" in captured["env"]["COMPSHARE_CONFIG_FILE"]


def test_write_timeout_is_unknown_and_not_retryable(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(mcp_server.subprocess, "run", timeout)
    runner = CompShareRunner(environ={})
    try:
        result = runner.run(
            ["instance", "stop", "uhost-1", "--yes"],
            expected_kind=CommandKind.WRITE,
            timeout_seconds=5,
        )
    finally:
        runner.close()

    assert result["ok"] is False
    assert result["outcome"] == "unknown"
    assert result["retryable"] is False
    assert result["error"]["action"] == "check_existing"


def test_help_uses_live_structured_cli_contract() -> None:
    runner = CompShareRunner(environ={})
    try:
        result = runner.help(["instance", "create"])
    finally:
        runner.close()

    assert result["ok"] is True
    assert result["result"]["data"]["command_path"] == "compshare instance create"


def test_mcp_server_exposes_controlled_tools() -> None:
    mcp = pytest.importorskip("mcp")

    class FakeRunner:
        def status(self, timeout_seconds=30):
            return {"ok": True, "version": __version__}

        def help(self, command, timeout_seconds=10):
            return {"ok": True, "command": command}

        def run(self, args, *, expected_kind, timeout_seconds):
            return {"ok": True, "kind": expected_kind.value, "args": args}

    async def check() -> None:
        server = mcp_server.create_server(FakeRunner())
        async with mcp.Client(server) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            assert set(tools) == {
                "compshare_status",
                "compshare_help",
                "compshare_read",
                "compshare_write",
            }
            assert tools["compshare_read"].annotations.read_only_hint is True
            assert tools["compshare_write"].annotations.destructive_hint is True
            result = await client.call_tool("compshare_read", {"args": ["instance", "list"]})
            assert result.is_error is False

    asyncio.run(check())
