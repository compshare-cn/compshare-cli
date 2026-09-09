from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from compshare_cli import __version__


class CommandKind(str, Enum):
    READ = "read"
    WRITE = "write"


_READ_COMMANDS = {
    ("doctor",),
    ("instance", "search"),
    ("instance", "zones"),
    ("instance", "families"),
    ("instance", "list"),
    ("instance", "show"),
    ("instance", "wait"),
    ("instance", "price"),
    ("instance", "resize-price"),
    ("instance", "billing"),
    ("instance", "refund"),
    ("instance", "network"),
    ("instance", "models"),
    ("instance", "ports", "list"),
    ("instance", "schedule", "show"),
    ("instance", "software", "list"),
    ("instance", "template", "list"),
    ("instance", "template", "show"),
    ("instance", "template", "path"),
    ("instance", "job", "list"),
    ("instance", "job", "show"),
    ("instance", "job", "logs"),
    ("instance", "job", "wait"),
    ("image", "list"),
    ("image", "show"),
    ("image", "progress"),
    ("image", "shares"),
    ("image", "tags"),
    ("storage", "disk", "list"),
    ("storage", "disk", "price"),
    ("bandwidth", "list"),
    ("bandwidth", "instances"),
    ("minimax", "show"),
    ("minimax", "list"),
    ("minimax", "packages"),
    ("minimax", "points"),
    ("team", "list"),
    ("team", "joined"),
    ("team", "show"),
    ("team", "invite", "list"),
    ("team", "member", "list"),
    ("team", "billing", "list"),
    ("team", "billing", "summary"),
    ("team", "billing", "unpaid"),
    ("team", "billing", "products"),
    ("team", "audit"),
}

_WRITE_COMMANDS = {
    ("feedback",),
    ("instance", "create"),
    ("instance", "start"),
    ("instance", "stop"),
    ("instance", "reboot"),
    ("instance", "delete"),
    ("instance", "rename"),
    ("instance", "password"),
    ("instance", "reinstall"),
    ("instance", "resize"),
    ("instance", "charge"),
    ("instance", "ssh"),
    ("instance", "cp"),
    ("instance", "ports", "update"),
    ("instance", "schedule", "set"),
    ("instance", "schedule", "extend"),
    ("instance", "schedule", "cancel"),
    ("instance", "template", "create"),
    ("instance", "template", "delete"),
    ("instance", "job", "submit"),
    ("instance", "job", "cancel"),
    ("instance", "job", "prune"),
    ("image", "create"),
    ("image", "update"),
    ("image", "delete"),
    ("image", "share"),
    ("image", "unshare"),
    ("image", "publish"),
    ("image", "favorite"),
    ("image", "unfavorite"),
    ("storage", "disk", "create"),
    ("storage", "disk", "attach"),
    ("storage", "disk", "detach"),
    ("storage", "disk", "resize"),
    ("storage", "disk", "delete"),
    ("storage", "us3", "attach"),
    ("bandwidth", "create"),
    ("bandwidth", "resize"),
    ("bandwidth", "delete"),
    ("bandwidth", "switch"),
    ("minimax", "create"),
    ("minimax", "cancel"),
    ("team", "create"),
    ("team", "update"),
    ("team", "delete"),
    ("team", "invite", "send"),
    ("team", "invite", "accept"),
    ("team", "invite", "reject"),
    ("team", "invite", "cancel"),
    ("team", "member", "rename"),
    ("team", "quota", "grant"),
    ("team", "quota", "reclaim"),
}

_BLOCKED_COMMAND_PREFIXES = {
    ("config",),
    ("version",),
    ("instance", "scp"),
    ("instance", "upgrade-price"),
    ("team", "billing", "export"),
}
_DRY_RUN_COMMANDS = {
    ("instance", "create"),
    ("instance", "resize"),
    ("instance", "charge"),
    ("instance", "job", "prune"),
    ("bandwidth", "create"),
    ("bandwidth", "resize"),
    ("bandwidth", "delete"),
    ("minimax", "create"),
}
_PRINT_ONLY_COMMANDS = {("instance", "ssh"), ("instance", "cp")}
_FORBIDDEN_FLAGS = {
    "--help",
    "--install-completion",
    "--json",
    "--private-key",
    "--profile",
    "--public-key",
    "--show-sensitive",
    "--version",
    "-h",
}
_COMPSHARE_ENVIRONMENT = {
    "COMPSHARE_MINIMAX_API_KEY",
    "COMPSHARE_MINIMAX_CALLBACK_TOKEN",
    "COMPSHARE_PRIVATE_KEY",
    "COMPSHARE_PUBLIC_KEY",
}
_CHILD_ENVIRONMENT = {
    "ALL_PROXY",
    "APPDATA",
    "COMSPEC",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "SSH_AUTH_SOCK",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
}
_MAX_ARGS = 128
_MAX_ARG_LENGTH = 8192
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_TIMEOUT_SECONDS = 900


class MCPBridgeError(RuntimeError):
    """Raised when a CLI request cannot be executed safely through MCP."""


class CommandTimeout(MCPBridgeError):
    """Raised when a CLI subprocess exceeds the MCP call timeout."""


def _flag_set(args: Sequence[str]) -> set[str]:
    flags = set()
    for value in args:
        if value == "--":
            break
        if value.startswith("-"):
            flags.add(value.split("=", 1)[0])
    return flags


def validate_args(args: Sequence[str]) -> List[str]:
    if isinstance(args, (str, bytes)) or not args:
        raise MCPBridgeError("args must be a non-empty list of CompShare CLI arguments")
    if len(args) > _MAX_ARGS:
        raise MCPBridgeError(f"too many arguments; maximum is {_MAX_ARGS}")
    normalized = []
    before_separator = True
    for value in args:
        if not isinstance(value, str):
            raise MCPBridgeError("every CLI argument must be a string")
        if not value or "\x00" in value or len(value) > _MAX_ARG_LENGTH:
            raise MCPBridgeError(
                f"arguments must be non-empty, NUL-free, and at most {_MAX_ARG_LENGTH} characters"
            )
        if value == "--":
            before_separator = False
        elif before_separator and value.split("=", 1)[0] in _FORBIDDEN_FLAGS:
            raise MCPBridgeError(
                f"{value.split('=', 1)[0]} is managed by the MCP bridge and cannot be supplied"
            )
        normalized.append(value)
    if normalized[0].startswith("-"):
        raise MCPBridgeError("args must start with a CompShare command, not a global option")
    return normalized


def _matching_command(args: Sequence[str]) -> Optional[Tuple[str, ...]]:
    known = _READ_COMMANDS | _WRITE_COMMANDS | _BLOCKED_COMMAND_PREFIXES
    for length in range(min(3, len(args)), 0, -1):
        candidate = tuple(args[:length])
        if candidate in known:
            return candidate
    return None


def classify_command(args: Sequence[str]) -> CommandKind:
    normalized = validate_args(args)
    command = _matching_command(normalized)
    if command is None:
        shown = " ".join(normalized[:3])
        raise MCPBridgeError(f"unsupported CompShare command: {shown}")
    if command in _BLOCKED_COMMAND_PREFIXES:
        raise MCPBridgeError(
            f"{' '.join(command)} is managed outside this connector and cannot be called "
            "through MCP"
        )
    flags = _flag_set(normalized)
    if command == ("instance", "job", "logs") and flags & {"--follow", "-f"}:
        raise MCPBridgeError("follow mode is not supported over MCP; request log slices instead")
    if command == ("instance", "ssh") and "--print" not in flags and "--" not in normalized:
        raise MCPBridgeError(
            "interactive SSH is not supported over MCP; pass a remote command after --"
        )
    if command in _WRITE_COMMANDS:
        if command in _DRY_RUN_COMMANDS and "--dry-run" in flags:
            return CommandKind.READ
        if command in _PRINT_ONLY_COMMANDS and "--print" in flags:
            return CommandKind.READ
        return CommandKind.WRITE
    return CommandKind.READ


def validate_help_path(command: Sequence[str]) -> List[str]:
    if isinstance(command, (str, bytes)):
        raise MCPBridgeError("command must be a list of zero to three command names")
    if len(command) > 3:
        raise MCPBridgeError("help accepts at most three command names")
    normalized = []
    for value in command:
        if not isinstance(value, str) or not value or value.startswith("-") or "\x00" in value:
            raise MCPBridgeError("help path entries must be plain command names")
        normalized.append(value)
    if normalized and normalized[0] in {"config", "version"}:
        raise MCPBridgeError(f"{normalized[0]} is managed outside this connector")
    return normalized


def _validate_timeout(timeout_seconds: int) -> int:
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise MCPBridgeError(f"timeout_seconds must be between 1 and {_MAX_TIMEOUT_SECONDS}")
    return timeout_seconds


class CompShareRunner:
    def __init__(
        self,
        *,
        command_prefix: Optional[Sequence[str]] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        source = dict(os.environ if environ is None else environ)
        self._scratch = tempfile.TemporaryDirectory(prefix="compshare-mcp-")
        self.command_prefix = list(command_prefix or (sys.executable, "-m", "compshare_cli"))
        self.environment = {
            key: value
            for key, value in source.items()
            if key in _CHILD_ENVIRONMENT or key in _COMPSHARE_ENVIRONMENT or key.startswith("LC_")
        }
        scratch = self._scratch.name
        self.environment.update(
            {
                "COMPSHARE_CONFIG_FILE": os.path.join(scratch, "config.json"),
                "COMPSHARE_SSH_CACHE_FILE": os.path.join(scratch, "ssh-cache.json"),
                "COMPSHARE_TEMPLATE_FILE": os.path.join(scratch, "templates.json"),
            }
        )
        self._secrets = tuple(
            value for key in _COMPSHARE_ENVIRONMENT if (value := self.environment.get(key))
        )

    def close(self) -> None:
        self._scratch.cleanup()

    def status(self, timeout_seconds: int = 30) -> Dict[str, Any]:
        timeout = _validate_timeout(timeout_seconds)
        credential_status = {
            "publicKey": bool(self.environment.get("COMPSHARE_PUBLIC_KEY")),
            "privateKey": bool(self.environment.get("COMPSHARE_PRIVATE_KEY")),
            "minimaxApiKey": bool(self.environment.get("COMPSHARE_MINIMAX_API_KEY")),
        }
        missing = [
            name
            for name, present in (
                ("COMPSHARE_PUBLIC_KEY", credential_status["publicKey"]),
                ("COMPSHARE_PRIVATE_KEY", credential_status["privateKey"]),
            )
            if not present
        ]
        if missing:
            return {
                "ok": False,
                "version": __version__,
                "credentialMode": "workbuddy-token",
                "credentials": credential_status,
                "error": {
                    "kind": "authentication",
                    "message": "Update the Connector credentials: " + ", ".join(missing),
                },
            }
        try:
            api = self._invoke(("instance", "zones"), timeout)
        except MCPBridgeError as exc:
            return {
                "ok": False,
                "version": __version__,
                "credentialMode": "workbuddy-token",
                "credentials": credential_status,
                "error": {"kind": "connection", "message": str(exc)},
            }
        result = self._result(api)
        return {
            "ok": result["ok"],
            "version": __version__,
            "credentialMode": "workbuddy-token",
            "credentials": credential_status,
            "api": result,
        }

    def help(self, command: Sequence[str], timeout_seconds: int = 10) -> Dict[str, Any]:
        path = validate_help_path(command)
        completed = self._invoke((*path, "--help"), _validate_timeout(timeout_seconds))
        return self._result(completed)

    def run(
        self,
        args: Sequence[str],
        *,
        expected_kind: CommandKind,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        normalized = validate_args(args)
        actual_kind = classify_command(normalized)
        if actual_kind is not expected_kind:
            raise MCPBridgeError(
                f"command is classified as {actual_kind.value}; use compshare_{actual_kind.value}"
            )
        timeout = _validate_timeout(timeout_seconds)
        try:
            completed = self._invoke(normalized, timeout)
        except CommandTimeout as exc:
            is_write = actual_kind is CommandKind.WRITE
            return {
                "ok": False,
                "exitCode": None,
                "outcome": "unknown" if is_write else "not-completed",
                "retryable": not is_write,
                "error": {
                    "kind": "timeout",
                    "message": str(exc),
                    "action": "check_existing" if is_write else "retry_later",
                },
            }
        return self._result(completed)

    def _invoke(
        self, args: Sequence[str], timeout_seconds: int
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [*self.command_prefix, "--json", *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                env=self.environment,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeout(
                f"CompShare command timed out after {timeout_seconds} seconds"
            ) from exc
        except OSError as exc:
            raise MCPBridgeError(f"failed to execute CompShare CLI: {exc}") from exc

    def _result(self, completed: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
        raw = completed.stdout.strip()
        if len(raw.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise MCPBridgeError("CompShare output exceeded 2 MiB; narrow the request")
        for secret in self._secrets:
            raw = raw.replace(secret, "[REDACTED]")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            error = completed.stderr.strip() or raw or "no output"
            for secret in self._secrets:
                error = error.replace(secret, "[REDACTED]")
            raise MCPBridgeError(f"CompShare CLI returned invalid JSON: {error[:1000]}") from exc
        if not isinstance(payload, dict):
            raise MCPBridgeError("CompShare CLI returned a non-object JSON response")
        return {
            "ok": completed.returncode == 0 and payload.get("ok") is True,
            "exitCode": completed.returncode,
            "result": payload,
        }


def create_server(runner: Optional[CompShareRunner] = None):
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise MCPBridgeError("MCP support is not installed; install compshare-cli[mcp]") from exc

    bridge = runner or CompShareRunner()
    server = MCPServer(
        "CompShare",
        version=__version__,
        instructions=(
            "Use status and help before running commands. Use the read tool for inspection and "
            "dry runs. Use the write tool only after explicit user confirmation."
        ),
    )

    @server.tool(
        title="检查 CompShare 连接状态",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    def compshare_status(timeout_seconds: int = 30) -> dict[str, Any]:
        """检查凭证注入、CLI 版本和 CompShare API 连通性，不执行写操作。"""
        try:
            return bridge.status(timeout_seconds)
        except MCPBridgeError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="查看 CompShare 命令帮助",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def compshare_help(command: List[str], timeout_seconds: int = 10) -> dict[str, Any]:
        """读取当前 CLI 的结构化帮助；command 是不含 compshare 的零到三个命令名。"""
        try:
            return bridge.help(command, timeout_seconds)
        except MCPBridgeError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="执行 CompShare 只读命令",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    def compshare_read(args: List[str], timeout_seconds: int = 30) -> dict[str, Any]:
        """执行白名单内的只读、dry-run 或 print-only 命令。

        args 不含开头的 compshare 和 --json，例如 ["instance", "list", "--all"]。
        写命令会被拒绝并提示使用 compshare_write。
        """
        try:
            return bridge.run(
                args,
                expected_kind=CommandKind.READ,
                timeout_seconds=timeout_seconds,
            )
        except MCPBridgeError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="执行 CompShare 写命令",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def compshare_write(
        args: List[str],
        user_confirmed: bool,
        confirmation_summary: str,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """执行白名单内的资源写入、付费、远程命令或文件传输。

        仅在用户看到本次准确对象、参数、费用和影响后明确同意时调用。
        user_confirmed 必须为 true，confirmation_summary 必须具体记录本次确认。
        写操作只执行一次；超时结果未知时先读取资源状态，禁止直接重试。
        """
        try:
            if not user_confirmed:
                raise MCPBridgeError("explicit user confirmation is required")
            summary = confirmation_summary.strip()
            if len(summary) < 8:
                raise MCPBridgeError(
                    "confirmation_summary must describe the specific confirmed operation"
                )
            result = bridge.run(
                args,
                expected_kind=CommandKind.WRITE,
                timeout_seconds=timeout_seconds,
            )
            result["confirmationSummary"] = summary
            return result
        except MCPBridgeError as exc:
            raise ToolError(str(exc)) from exc

    return server


def main() -> None:
    try:
        server = create_server()
    except MCPBridgeError as exc:
        raise SystemExit(str(exc)) from exc
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
