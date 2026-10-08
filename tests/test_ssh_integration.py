"""Exercise the CLI against an isolated OpenSSH server, without cloud credentials."""

import getpass
import json
import os
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from compshare_cli import cli
from compshare_cli.commands import instance


@pytest.fixture
def openssh(monkeypatch, tmp_path):
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    if os.name == "nt" or not Path(sshd).is_file() or not shutil.which("ssh-keygen"):
        pytest.skip("a local OpenSSH server is required")

    key = tmp_path / "key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        timeout=10,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "sshd_config"
    config.write_text(
        f'ListenAddress 127.0.0.1\nListenAddress ::1\nPort {port}\nHostKey "{key}"\n'
        f'PidFile "{tmp_path / "pid"}"\nAuthorizedKeysFile "{key}.pub"\n'
        f'SetEnv "XDG_STATE_HOME={tmp_path / "state"}"\n'
        "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n"
        "StrictModes no\nPermitRootLogin yes\nSubsystem sftp internal-sftp\n",
        encoding="utf-8",
    )
    known_hosts = tmp_path / "known_hosts"
    argv = [
        "ssh",
        "-F",
        "/dev/null",
        "-i",
        str(key),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-p",
        str(port),
        f"{getpass.getuser()}@127.0.0.1",
    ]
    host = {
        "UHostId": "uhost-local",
        "Region": "cn-wlcb",
        "Zone": "cn-wlcb-01",
        "State": "Running",
        "SshLoginCommand": shlex.join(argv),
    }
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("COMPSHARE_SSH_CACHE_FILE", str(tmp_path / "ssh-cache.json"))
    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "local-test-public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "local-test-private")
    monkeypatch.setattr(
        instance, "locate_instance", lambda *_: (host["Region"], host["Zone"], host)
    )
    with (tmp_path / "sshd.log").open("w") as log:
        server = subprocess.Popen([sshd, "-D", "-e", "-f", str(config)], stderr=log)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and server.poll() is None:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.02)
            else:
                pytest.skip("local sshd cannot start on this platform")
            yield host, known_hosts
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def _invoke(*args):
    result = CliRunner().invoke(cli.app, ["--json", "instance", *args])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    return result.exit_code, json.loads(result.stdout)


def test_remote_arguments_survive_openssh_and_the_remote_shell(openssh):
    arguments = ["hello world", "", "中文", "single' double\"", "$HOME", "a;b", "*", "a\nb"]
    code, payload = _invoke("ssh", "uhost-local", "--", "printf", "%s\n", *arguments)

    assert code == 0, payload
    assert payload["data"]["stdout"] == "".join(value + "\n" for value in arguments)


def test_shell_script_preserves_stdout_stderr_and_exit_status(openssh):
    script = "printf 'hello world\\n'; printf 'Permission denied\\n' >&2; exit 7"
    code, payload = _invoke("ssh", "uhost-local", "--", "sh", "-lc", script)

    assert code == 7, payload
    assert payload["error"]["code"] == "remote_exit_nonzero"
    details = payload["error"]["details"]
    assert details["phase"] == "remote_command"
    assert details["stdout"] == "hello world\n"
    assert details["stderr"].endswith("Permission denied\n")


@pytest.mark.parametrize("directory", [False, True])
def test_file_and_directory_round_trip_with_special_paths(openssh, tmp_path, directory):
    source = tmp_path / "local 空格:source"
    remote = tmp_path / "remote 空格; '$HOME'"
    destination = tmp_path / "downloaded 空格:result"
    content = b"\x00\xffbinary\n" + "中文".encode()
    if directory:
        source.mkdir()
        (source / "nested").mkdir()
        (source / "nested" / "file 空格.bin").write_bytes(content)
    else:
        source.write_bytes(content)

    code, upload = _invoke("cp", "uhost-local", str(source), ":" + str(remote))
    assert code == 0, upload
    code, download = _invoke("cp", "uhost-local", ":" + str(remote), str(destination))
    assert code == 0, download
    copied = destination / "nested" / "file 空格.bin" if directory else destination
    assert copied.read_bytes() == content


def test_changed_host_key_is_rejected(openssh, tmp_path):
    host, known_hosts = openssh
    code, payload = _invoke("ssh", "uhost-local", "--", "true")
    assert code == 0, payload
    wrong_key = tmp_path / "wrong_key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(wrong_key)],
        check=True,
        timeout=10,
    )
    destination = known_hosts.read_text().split()[0]
    known_hosts.write_text(destination + " " + Path(str(wrong_key) + ".pub").read_text())

    code, payload = _invoke("ssh", host["UHostId"], "--", "true")
    assert code == 255, payload
    assert payload["error"]["code"] == "host_key_verification_failed"


def test_printed_command_executes_the_same_remote_arguments(openssh):
    code, payload = _invoke("ssh", "uhost-local", "--", "true")
    assert code == 0, payload
    arguments = ["printf", "%s\n", "hello world", "$HOME", ""]
    result = CliRunner().invoke(
        cli.app,
        [
            "--json",
            "--show-sensitive",
            "instance",
            "ssh",
            "uhost-local",
            "--print",
            "--",
            *arguments,
        ],
    )
    assert result.exit_code == 0, result.exception
    command = json.loads(result.stdout)["data"]["command"]
    execution = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=10)
    assert execution.returncode == 0, execution.stderr
    assert execution.stdout == "hello world\n$HOME\n\n"


def test_remote_jobs_share_the_connection_and_preserve_helper_quoting(openssh, tmp_path):
    code, payload = _invoke("job", "list", "uhost-local")
    assert code == 0, payload
    assert payload["data"]["items"] == []
    assert (tmp_path / "state" / "compshare" / "jobs").is_dir()


@pytest.mark.parametrize("style", ["uri", "ipv6", "login_override"])
def test_native_scp_connection_forms(openssh, tmp_path, style):
    host, _ = openssh
    argv = shlex.split(host["SshLoginCommand"])
    port_index = argv.index("-p")
    port = int(argv[port_index + 1])
    user = getpass.getuser()
    if style == "uri":
        del argv[port_index : port_index + 2]
        argv[-1] = f"ssh://{user}@127.0.0.1:{port}"
    elif style == "ipv6":
        try:
            with socket.create_connection(("::1", port), timeout=1):
                pass
        except OSError:
            pytest.skip("IPv6 loopback is unavailable")
        argv[-1] = f"{user}@::1"
    else:
        argv[1:1] = ["-l", user]
        argv[-1] = "unused-user@127.0.0.1"
    host["SshLoginCommand"] = shlex.join(argv)
    source = tmp_path / "source"
    destination = tmp_path / "remote"
    source.write_bytes(b"native connection")
    code, payload = _invoke("cp", "uhost-local", str(source), ":" + str(destination))
    assert code == 0, payload
    assert destination.read_bytes() == source.read_bytes()
