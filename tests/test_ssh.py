from pathlib import Path
from types import SimpleNamespace

import pytest

from compshare_cli import ssh


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
            "-p",
            "22",
            "root@example.invalid",
        ],
    )
    assert calls[-1] == ("close", False)


def test_connect_with_password_requires_an_interactive_terminal(monkeypatch) -> None:
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
    assert argv[:9] == [
        "scp",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    assert argv[9:] == [
        "-P",
        "2222",
        "/local/model.bin",
        "root@example.invalid:/workspace",
    ]
    assert password == "instance-secret"
