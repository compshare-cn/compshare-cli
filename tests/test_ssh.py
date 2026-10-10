import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from compshare_cli import ssh
from compshare_cli.errors import CLIError, UsageError


@pytest.mark.skipif(os.name == "nt", reason="pexpect requires POSIX")
def test_connect_with_password_answers_split_prompt_once(monkeypatch) -> None:
    calls = []
    sent = []

    class FakeChild:
        exitstatus = 7
        signalstatus = None

        def interact(self, *, escape_character, output_filter) -> None:
            assert escape_character is None
            output_filter(b"root@example.invalid's pass")
            output_filter(b"word: ")
            output_filter(b"Password: ")

        def sendline(self, value: bytes) -> None:
            sent.append(value)

        def setwinsize(self, rows: int, columns: int) -> None:
            calls.append(("resize", rows, columns))

        def close(self, force: bool = False) -> None:
            calls.append(("close", force))

    def spawn(command, args, **kwargs):
        calls.append(("spawn", command, args, kwargs))
        return FakeChild()

    monkeypatch.setattr(ssh.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(ssh.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("pexpect.spawn", spawn)

    exit_code = ssh.connect_with_password(
        ["ssh", "-p", "22", "root@example.invalid"],
        "instance-secret",
    )

    assert exit_code == 7
    assert sent == [b"instance-secret"]
    assert calls[0][:3] == (
        "spawn",
        "ssh",
        [
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=no",
            "-p",
            "22",
            "root@example.invalid",
        ],
    )
    assert calls[-1] == ("close", False)


def test_connect_with_password_requires_an_interactive_terminal(monkeypatch) -> None:
    monkeypatch.setattr(ssh, "_is_windows", lambda: False)
    monkeypatch.setattr(ssh.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    try:
        ssh.connect_with_password(["ssh", "root@example.invalid"], "instance-secret")
    except ssh.PasswordAutomationUnavailable:
        pass
    else:  # pragma: no cover - assertion branch
        raise AssertionError("expected PasswordAutomationUnavailable")


def test_connect_with_password_uses_askpass_on_windows(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(ssh, "_is_windows", lambda: True)
    monkeypatch.setattr(
        ssh,
        "_run_with_askpass",
        lambda argv, password: calls.append((argv, password)) or 23,
    )

    exit_code = ssh.connect_with_password(
        ["ssh", "-p", "2222", "root@example.invalid"],
        "instance-secret",
    )

    assert exit_code == 23
    argv, password = calls[0]
    assert argv == [
        "ssh",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=no",
        "-p",
        "2222",
        "root@example.invalid",
    ]
    assert password == "instance-secret"


def test_execute_with_password_uses_askpass_without_password_in_argv(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv(ssh._ASKPASS_PASSWORD_FILE_ENV, raising=False)
    monkeypatch.setattr(ssh, "_askpass_executable", lambda: "/tmp/compshare-ssh-askpass")

    def call(argv, env):
        password_file = Path(env[ssh._ASKPASS_PASSWORD_FILE_ENV])
        calls.append((argv, dict(env), password_file, password_file.read_text()))
        return 19

    monkeypatch.setattr(ssh.subprocess, "call", call)

    exit_code = ssh.execute_with_password(
        ["ssh", "root@example.invalid", "nvidia-smi", "--query-gpu=name"],
        "instance-secret",
    )

    assert exit_code == 19
    argv, environment, password_file, stored_password = calls[0]
    assert argv == [
        "ssh",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=no",
        "-n",
        "-T",
        "root@example.invalid",
        "nvidia-smi",
        "--query-gpu=name",
    ]
    assert "instance-secret" not in argv
    assert stored_password == "instance-secret"
    assert not password_file.exists()
    assert environment["SSH_ASKPASS"] == "/tmp/compshare-ssh-askpass"
    assert environment["SSH_ASKPASS_REQUIRE"] == "force"
    assert environment[ssh._ASKPASS_PASSWORD_FILE_ENV] == str(password_file)
    assert ssh._ASKPASS_PASSWORD_FILE_ENV not in ssh.os.environ


@pytest.mark.parametrize(
    ("stderr", "phase", "error_code"),
    [
        (
            "ssh: connect to host x port 22: Connection timed out",
            "connection",
            "connection_timeout",
        ),
        (
            "root@x: Permission denied (publickey,password).",
            "authentication",
            "authentication_failed",
        ),
        ("unclassified OpenSSH failure", "ssh", "ssh_failed"),
    ],
)
def test_remote_execution_result_classifies_ssh_failures(stderr, phase, error_code) -> None:
    result = ssh.remote_execution_result(255, "", stderr)

    assert result.phase == phase
    assert result.error_code == error_code


def test_askpass_reads_and_removes_internal_password_file(monkeypatch, capsys, tmp_path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("instance-secret")
    monkeypatch.setenv(ssh._ASKPASS_PASSWORD_FILE_ENV, str(password_file))

    ssh.askpass()

    assert capsys.readouterr().out == "instance-secret\n"
    assert not password_file.exists()


def test_scp_upload_command_converts_port_after_destination_and_recurses() -> None:
    command = ssh.scp_upload_command(
        ["ssh", "root@example.invalid", "-p", "2222"],
        "/local/dataset",
        "/workspace/dataset",
        recursive=True,
    )

    assert command == [
        "scp",
        "-P",
        "2222",
        "-r",
        "/local/dataset",
        "root@example.invalid:/workspace/dataset",
    ]


def test_scp_upload_command_preserves_shared_options_and_login() -> None:
    command = ssh.scp_upload_command(
        [
            "ssh",
            "-p2222",
            "-lroot",
            "-i",
            "/keys/instance key",
            "-oProxyJump=bastion",
            "example.invalid",
        ],
        "/local/model.bin",
        "/workspace/model.bin",
    )

    assert command == [
        "scp",
        "-P",
        "2222",
        "-i",
        "/keys/instance key",
        "-o",
        "ProxyJump=bastion",
        "/local/model.bin",
        "root@example.invalid:/workspace/model.bin",
    ]


def test_scp_download_command_preserves_connection_and_recurses() -> None:
    command = ssh.scp_download_command(
        ["ssh", "-p2222", "-lroot", "example.invalid"],
        "/workspace/results",
        "/local/results",
    )

    assert command == [
        "scp",
        "-P",
        "2222",
        "-r",
        "root@example.invalid:/workspace/results",
        "/local/results",
    ]


def test_copy_with_password_adds_scp_authentication_options(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        ssh,
        "_run_with_askpass",
        lambda argv, password: calls.append((argv, password)) or 11,
    )

    exit_code = ssh.copy_with_password(
        ["scp", "-P", "2222", "/local/model.bin", "root@example.invalid:/workspace"],
        "instance-secret",
    )

    assert exit_code == 11
    argv, password = calls[0]
    assert argv[:11] == [
        "scp",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=no",
    ]
    assert argv[11:] == [
        "-P",
        "2222",
        "/local/model.bin",
        "root@example.invalid:/workspace",
    ]
    assert password == "instance-secret"


@pytest.mark.parametrize(
    "diagnostic", ["Permission denied", "Connection refused", "No route to host"]
)
def test_remote_program_diagnostics_are_not_ssh_failures(diagnostic) -> None:
    result = ssh.remote_execution_result(7, "output", diagnostic)
    assert result.phase == "remote_command"
    assert result.error_code == "remote_exit_nonzero"
    assert result.stdout == "output"


@pytest.mark.parametrize(
    ("diagnostic", "phase", "error_code"),
    [
        ("Could not resolve hostname x", "connection", "dns_resolution_failed"),
        ("Name or service not known", "connection", "dns_resolution_failed"),
        ("Operation timed out", "connection", "connection_timeout"),
        ("No route to host", "connection", "network_unreachable"),
        ("Network is unreachable", "connection", "network_unreachable"),
        ("Connection refused", "connection", "connection_refused"),
        ("Host key verification failed", "connection", "host_key_verification_failed"),
        ("Authentication failed", "authentication", "authentication_failed"),
        ("Too many authentication failures", "authentication", "authentication_failed"),
    ],
)
def test_other_ssh_failure_diagnostics(diagnostic, phase, error_code) -> None:
    result = ssh.remote_execution_result(255, "", diagnostic)
    assert (result.phase, result.error_code) == (phase, error_code)


@pytest.mark.parametrize(
    ("login", "destination", "options"),
    [
        (["ssh", "root@2001:db8::1"], "root@[2001:db8::1]", []),
        (["ssh", "root@[2001:db8::1]"], "root@[2001:db8::1]", []),
        (["ssh", "-l", "alice", "root@example.invalid"], "alice@example.invalid", []),
        (["ssh", "ssh://root@example.invalid:2222"], "root@example.invalid", ["-P", "2222"]),
    ],
)
def test_scp_connection_preserves_native_ssh_destinations(login, destination, options) -> None:
    assert ssh.scp_upload_command(login, "/local/file", "/remote/file") == [
        "scp",
        *options,
        "/local/file",
        f"{destination}:/remote/file",
    ]


@pytest.mark.parametrize(
    "login",
    [
        [],
        ["sh", "example.invalid"],
        ["ssh"],
        ["ssh", ""],
        ["ssh", "-p"],
        ["ssh", "example.invalid", "echo"],
        ["ssh", "ssh://example.invalid:invalid"],
    ],
)
def test_scp_rejects_invalid_login_commands(login) -> None:
    with pytest.raises(ValueError):
        ssh.scp_upload_command(login, "/local/file", "/remote/file")


def test_key_authentication_capture_never_prompts(monkeypatch) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return ssh.subprocess.CompletedProcess(argv, 0, "中文\n", "")

    monkeypatch.setattr(ssh.subprocess, "run", run)
    result = ssh.execute_captured(["ssh", "example.invalid", "true"])
    assert result.ok
    assert "BatchMode=yes" in calls[0][0]
    assert calls[0][1]["errors"] == "replace"


@pytest.mark.parametrize(
    "runner", [ssh.execute_captured_with_password, ssh.copy_captured_with_password]
)
def test_captured_password_authentication_cleans_up_on_failure(monkeypatch, runner) -> None:
    password_files = []
    monkeypatch.setattr(ssh, "_askpass_executable", lambda: "/unused/askpass")

    def run(argv, **kwargs):
        password_file = Path(kwargs["env"][ssh._ASKPASS_PASSWORD_FILE_ENV])
        password_files.append(password_file)
        assert password_file.read_text() == "temporary-secret"
        if os.name != "nt":
            assert password_file.stat().st_mode & 0o777 == 0o600
        raise OSError("test process failure")

    monkeypatch.setattr(ssh.subprocess, "run", run)
    executable = "scp" if runner == ssh.copy_captured_with_password else "ssh"
    with pytest.raises(CLIError, match="test process failure"):
        runner([executable, "example.invalid"], "temporary-secret")
    assert password_files and all(not path.exists() for path in password_files)


@pytest.mark.parametrize("missing", [True, False])
def test_askpass_missing_environment_or_file_exits_cleanly(monkeypatch, tmp_path, missing) -> None:
    monkeypatch.delenv(ssh._ASKPASS_PASSWORD_FILE_ENV, raising=False)
    if not missing:
        monkeypatch.setenv(ssh._ASKPASS_PASSWORD_FILE_ENV, str(tmp_path / "absent"))
    with pytest.raises(SystemExit) as exc:
        ssh.askpass()
    assert exc.value.code == 1


@pytest.mark.parametrize(
    ("diagnostic", "phase", "error_code"),
    [
        ("root@x: Permission denied (password).", "authentication", "authentication_failed"),
        ("scp: /restricted: Permission denied", "file_transfer", "transfer_failed"),
        ("scp: /missing: No such file or directory", "file_transfer", "transfer_failed"),
        ("ssh: Connection refused", "connection", "connection_refused"),
    ],
)
def test_scp_distinguishes_file_errors_from_authentication(diagnostic, phase, error_code) -> None:
    result = ssh.remote_execution_result(1, "", diagnostic, transfer=True)
    assert (result.phase, result.error_code) == (phase, error_code)


@pytest.mark.parametrize("login", [None, {}, "", "ssh", "ssh 'unterminated", "sh x", "ssh x echo"])
def test_login_command_validation_is_user_facing(login) -> None:
    with pytest.raises(UsageError, match="SSH"):
        ssh.ssh_login_command(login)


def test_capture_replaces_invalid_utf8_output() -> None:
    result = ssh.run_command(
        [ssh.sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"],
        capture=True,
    )
    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_missing_askpass_helper_has_a_useful_error(monkeypatch) -> None:
    monkeypatch.setattr(ssh.os.path, "isfile", lambda *_: False)
    monkeypatch.setattr(ssh.shutil, "which", lambda *_: None)
    with pytest.raises(ssh.PasswordAutomationUnavailable, match="compshare-ssh-askpass"):
        ssh._askpass_executable()


@pytest.mark.parametrize("capture", [False, True])
def test_missing_process_is_a_user_facing_error(capture) -> None:
    with pytest.raises(CLIError, match="compshare-no-such-executable"):
        ssh.run_command(["compshare-no-such-executable"], capture=capture)
