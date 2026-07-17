from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, List, Optional

_ASKPASS_PASSWORD_FILE_ENV = "COMPSHARE_INTERNAL_SSH_PASSWORD_FILE"
_SSH_OPTIONS_WITH_VALUE = {
    "-B",
    "-b",
    "-c",
    "-D",
    "-E",
    "-e",
    "-F",
    "-I",
    "-i",
    "-J",
    "-L",
    "-l",
    "-m",
    "-O",
    "-o",
    "-P",
    "-p",
    "-R",
    "-S",
    "-W",
    "-w",
}
_SCP_SHARED_OPTIONS = {"-c", "-F", "-i", "-J", "-o"}


class PasswordAutomationUnavailable(RuntimeError):
    """Raised when the current terminal cannot safely automate an SSH password."""


@dataclass(frozen=True)
class RemoteExecutionResult:
    """Captured output and an Agent-friendly classification of an SSH execution."""

    exit_code: int
    stdout: str
    stderr: str
    phase: str
    error_code: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _is_windows() -> bool:
    return os.name == "nt"


def _password_authentication(argv: List[str], *, command_mode: bool = False) -> List[str]:
    executable = os.path.basename(argv[0]).casefold()
    if executable not in {"ssh", "ssh.exe"}:
        raise PasswordAutomationUnavailable
    options = [
        argv[0],
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if command_mode:
        options.extend(["-n", "-T"])
    return [*options, *argv[1:]]


def _scp_password_authentication(argv: List[str]) -> List[str]:
    executable = os.path.basename(argv[0]).casefold()
    if executable not in {"scp", "scp.exe"}:
        raise PasswordAutomationUnavailable
    return [
        argv[0],
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        *argv[1:],
    ]


def scp_upload_command(
    ssh_argv: List[str],
    local_path: str,
    remote_path: str,
    *,
    recursive: bool = False,
) -> List[str]:
    """Convert an API-provided SSH login command into an SCP upload command."""
    if not ssh_argv or os.path.basename(ssh_argv[0]).casefold() not in {"ssh", "ssh.exe"}:
        raise ValueError("unsupported SSH executable")

    destination: Optional[str] = None
    login: Optional[str] = None
    scp_options: List[str] = []
    index = 1
    while index < len(ssh_argv):
        token = ssh_argv[index]
        if token == "--":
            index += 1
            continue
        option = token[:2] if token.startswith("-") and len(token) > 1 else None
        if option in _SSH_OPTIONS_WITH_VALUE:
            if len(token) > 2:
                value = token[2:]
            else:
                index += 1
                if index >= len(ssh_argv):
                    raise ValueError(f"missing value for SSH option {option}")
                value = ssh_argv[index]
            if option == "-p":
                scp_options.extend(("-P", value))
            elif option == "-l":
                login = value
            elif option in _SCP_SHARED_OPTIONS:
                scp_options.extend((option, value))
        elif token.startswith("-"):
            flags = token[1:]
            if flags and set(flags) <= set("46Cqv"):
                scp_options.append(token)
        elif destination is None:
            destination = token
        else:
            raise ValueError("SSH login command contains a remote command")
        index += 1

    if destination is None:
        raise ValueError("SSH login command has no destination")
    if login and "@" not in destination:
        destination = f"{login}@{destination}"
    if recursive:
        scp_options.append("-r")
    return ["scp", *scp_options, local_path, f"{destination}:{remote_path}"]


def _askpass_executable() -> str:
    name = "compshare-ssh-askpass.exe" if _is_windows() else "compshare-ssh-askpass"
    sibling = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), name)
    if os.path.isfile(sibling) and os.access(sibling, os.X_OK):
        return sibling
    located = shutil.which(name)
    if located:
        return located
    raise PasswordAutomationUnavailable


def askpass() -> None:
    """Return the short-lived SSH password to OpenSSH's askpass pipe."""
    password_file = os.environ.get(_ASKPASS_PASSWORD_FILE_ENV)
    if password_file is None:
        raise SystemExit(1)
    try:
        with open(password_file, encoding="utf-8") as file:
            password = file.read()
    except OSError as exc:
        raise SystemExit(1) from exc
    finally:
        try:
            os.unlink(password_file)
        except OSError:
            pass
    sys.stdout.write(password + "\n")


def execute_with_password(argv: List[str], password: str) -> int:
    """Run a non-interactive SSH command using the API-provided password."""
    command = _password_authentication(argv, command_mode=True)
    return _run_with_askpass(command, password)


def execute_captured_with_password(argv: List[str], password: str) -> RemoteExecutionResult:
    """Run and capture a non-interactive SSH command without exposing its password."""
    command = _password_authentication(argv, command_mode=True)
    completed = _run_with_askpass(command, password, capture=True)
    assert isinstance(completed, subprocess.CompletedProcess)
    return remote_execution_result(completed.returncode, completed.stdout, completed.stderr)


def execute_captured(argv: List[str]) -> RemoteExecutionResult:
    """Run and capture a non-interactive SSH command using normal OpenSSH auth."""
    executable = os.path.basename(argv[0]).casefold()
    if executable not in {"ssh", "ssh.exe"}:
        raise PasswordAutomationUnavailable
    command = [
        argv[0],
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-n",
        "-T",
        *argv[1:],
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return remote_execution_result(completed.returncode, completed.stdout, completed.stderr)


def remote_execution_result(exit_code: int, stdout: str, stderr: str) -> RemoteExecutionResult:
    """Classify common OpenSSH failures while preserving the original diagnostics."""
    if exit_code == 0:
        return RemoteExecutionResult(exit_code, stdout, stderr, "completed")

    diagnostic = stderr.casefold()
    patterns = (
        ("could not resolve hostname", "connection", "dns_resolution_failed"),
        ("name or service not known", "connection", "dns_resolution_failed"),
        ("connection timed out", "connection", "connection_timeout"),
        ("operation timed out", "connection", "connection_timeout"),
        ("no route to host", "connection", "network_unreachable"),
        ("network is unreachable", "connection", "network_unreachable"),
        ("connection refused", "connection", "connection_refused"),
        ("host key verification failed", "connection", "host_key_verification_failed"),
        ("permission denied", "authentication", "authentication_failed"),
        ("authentication failed", "authentication", "authentication_failed"),
        ("too many authentication failures", "authentication", "authentication_failed"),
    )
    for marker, phase, error_code in patterns:
        if marker in diagnostic:
            return RemoteExecutionResult(exit_code, stdout, stderr, phase, error_code)
    if exit_code == 255:
        return RemoteExecutionResult(exit_code, stdout, stderr, "ssh", "ssh_failed")
    return RemoteExecutionResult(exit_code, stdout, stderr, "remote_command", "remote_exit_nonzero")


def copy_with_password(argv: List[str], password: str) -> int:
    """Run an SCP upload using the API-provided password."""
    command = _scp_password_authentication(argv)
    return _run_with_askpass(command, password)


def _run_with_askpass(
    command: List[str],
    password: str,
    *,
    capture: bool = False,
) -> Any:
    with tempfile.TemporaryDirectory(prefix="compshare-ssh-") as temporary_directory:
        password_file = os.path.join(temporary_directory, "password")
        descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(password)
        environment = os.environ.copy()
        environment.update(
            {
                "SSH_ASKPASS": _askpass_executable(),
                "SSH_ASKPASS_REQUIRE": "force",
                _ASKPASS_PASSWORD_FILE_ENV: password_file,
            }
        )
        environment.setdefault("DISPLAY", "compshare-ssh")
        if capture:
            return subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        return subprocess.call(command, env=environment)


def connect_with_password(argv: List[str], password: str) -> int:
    """Run SSH interactively and answer its first password prompt."""
    if _is_windows():
        return _run_with_askpass(_password_authentication(argv), password)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise PasswordAutomationUnavailable

    try:
        import pexpect
    except ImportError as exc:  # pragma: no cover - packaging installs this on supported systems
        raise PasswordAutomationUnavailable from exc

    command = _password_authentication(argv)
    size = shutil.get_terminal_size(fallback=(80, 24))
    child = pexpect.spawn(
        command[0],
        command[1:],
        encoding=None,
        dimensions=(size.lines, size.columns),
    )
    prompt = re.compile(rb"password\s*:\s*$", re.IGNORECASE)
    password_bytes = password.encode("utf-8")
    tail = b""
    password_sent = False

    def answer_password(output: bytes) -> bytes:
        nonlocal password_sent, tail
        combined = tail + output
        if not password_sent and prompt.search(combined):
            child.sendline(password_bytes)
            password_sent = True
        tail = combined[-256:]
        return output

    previous_handler: Optional[Any] = None
    if hasattr(signal, "SIGWINCH"):

        def resize_terminal(*_: Any) -> None:
            current = shutil.get_terminal_size(fallback=(80, 24))
            child.setwinsize(current.lines, current.columns)

        try:
            previous_handler = signal.signal(signal.SIGWINCH, resize_terminal)
        except ValueError:  # pragma: no cover - only possible outside the main thread
            previous_handler = None

    try:
        child.interact(escape_character=None, output_filter=answer_password)
    except BaseException:
        child.close(force=True)
        raise
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGWINCH, previous_handler)

    child.close()
    if child.signalstatus is not None:
        return 128 + child.signalstatus
    return child.exitstatus or 0
