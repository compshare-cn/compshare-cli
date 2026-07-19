import base64
import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import pytest

from compshare_cli.errors import UsageError
from compshare_cli.remote_jobs import (
    RemoteJobProtocolError,
    duration_seconds,
    joined_command,
    list_script,
    logs_script,
    normalized_record,
    parse_records,
    prune_script,
    show_script,
    submit_script,
    validate_job_id,
)


def _run(script: str, *, home: Path, path: Optional[str] = None) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "XDG_STATE_HOME": str(home / "state"),
            "PATH": path or environment["PATH"],
        }
    )
    return subprocess.run(
        ["sh", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_job_id_duration_and_command_validation() -> None:
    assert validate_job_id("job-20260719_test.1") == "job-20260719_test.1"
    assert duration_seconds("12h") == 43200
    assert duration_seconds("7D") == 604800
    assert joined_command(["printf", "%s", "hello world"]) == "printf %s 'hello world'"

    with pytest.raises(UsageError):
        validate_job_id("../escape")
    with pytest.raises(UsageError):
        duration_seconds("7 days")
    with pytest.raises(UsageError):
        joined_command([])


def test_protocol_parser_and_normalizer() -> None:
    encoded = base64.b64encode(b"job-test").decode("ascii")
    records = parse_records(
        "SSH banner\n"
        f"COMPSHARE_JOB_BEGIN\nCOMPSHARE_JOB_FIELD\tJobId\t{encoded}\n"
        "COMPSHARE_JOB_END\n"
    )
    assert records == [{"JobId": "job-test"}]

    normalized = normalized_record(
        {
            "PID": "123",
            "ExitCode": "",
            "Existing": "true",
            "Mode": "offset",
            "Limit": "4",
            "StdoutOffset": "2",
            "StdoutSize": "10",
            "StderrOffset": "8",
            "StderrSize": "8",
        }
    )
    assert normalized["PID"] == 123
    assert normalized["ExitCode"] is None
    assert normalized["Existing"] is True
    assert normalized["StdoutNextOffset"] == 6
    assert normalized["StdoutEOF"] is False
    assert normalized["StderrNextOffset"] == 8
    assert normalized["StderrEOF"] is True

    with pytest.raises(RemoteJobProtocolError):
        parse_records("COMPSHARE_JOB_UNSUPPORTED\n")


def test_relative_xdg_state_home_falls_back_to_home(tmp_path) -> None:
    environment = os.environ.copy()
    environment.update({"HOME": str(tmp_path), "XDG_STATE_HOME": "relative/state"})
    completed = subprocess.run(
        ["sh", "-c", list_script()],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / ".local" / "state" / "compshare" / "jobs").is_dir()


def test_submit_show_and_read_logs_with_xdg_state_directory(tmp_path) -> None:
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    fake_setsid = bin_directory / "setsid"
    fake_setsid.write_text('#!/bin/sh\nexec "$@"\n', encoding="utf-8")
    fake_setsid.chmod(0o700)
    command_path = f"{bin_directory}{os.pathsep}{os.environ['PATH']}"

    submitted = _run(
        submit_script(
            "job-test",
            "printf 'hello\\n'; printf 'warning\\n' >&2; exit 7",
            name="build",
            cwd=str(tmp_path),
        ),
        home=tmp_path,
        path=command_path,
    )
    assert submitted.returncode == 0, submitted.stderr
    submit_record = normalized_record(parse_records(submitted.stdout)[0])
    assert submit_record["JobId"] == "job-test"
    assert submit_record["Existing"] is False

    job = None
    for _ in range(100):
        shown = _run(show_script("job-test"), home=tmp_path, path=command_path)
        assert shown.returncode == 0, shown.stderr
        job = normalized_record(parse_records(shown.stdout)[0])
        if job["State"] == "Failed":
            break
        time.sleep(0.02)
    assert job is not None
    assert job["State"] == "Failed"
    assert job["ExitCode"] == 7
    assert job["Name"] == "build"
    assert job["Cwd"] == str(tmp_path)

    logs = _run(
        logs_script(
            "job-test",
            tail=None,
            stdout_offset=0,
            stderr_offset=0,
            limit=65536,
        ),
        home=tmp_path,
        path=command_path,
    )
    assert logs.returncode == 0, logs.stderr
    log_record = normalized_record(parse_records(logs.stdout)[0])
    assert log_record["Stdout"] == "hello\n"
    assert log_record["Stderr"] == "warning\n"
    assert log_record["StdoutNextOffset"] == len("hello\n")
    assert log_record["StderrNextOffset"] == len("warning\n")
    assert log_record["StdoutEOF"] is True

    listed = _run(list_script(), home=tmp_path, path=command_path)
    assert [record["JobId"] for record in parse_records(listed.stdout)] == ["job-test"]


def test_submit_is_idempotent_for_the_same_job_id(tmp_path) -> None:
    job_directory = tmp_path / "state" / "compshare" / "jobs" / "job-existing"
    job_directory.mkdir(parents=True)
    command = "printf done"

    (job_directory / "specification_sha256").write_text(
        hashlib.sha256(f"{command}\0".encode("utf-8")).hexdigest(), encoding="utf-8"
    )
    (job_directory / "command").write_text(command, encoding="utf-8")
    (job_directory / "name").write_text("existing", encoding="utf-8")
    (job_directory / "cwd").write_text("", encoding="utf-8")
    (job_directory / "created_at").write_text("1", encoding="utf-8")
    (job_directory / "exit_code").write_text("0", encoding="utf-8")

    completed = _run(
        submit_script("job-existing", command),
        home=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    record = normalized_record(parse_records(completed.stdout)[0])
    assert record["Existing"] is True
    assert record["State"] == "Succeeded"

    conflict = _run(
        submit_script("job-existing", "printf different"),
        home=tmp_path,
    )
    assert conflict.returncode != 0
    with pytest.raises(RemoteJobProtocolError, match="different command"):
        parse_records(conflict.stdout)

    cwd_conflict = _run(
        submit_script("job-existing", command, cwd="/different"),
        home=tmp_path,
    )
    assert cwd_conflict.returncode != 0
    with pytest.raises(RemoteJobProtocolError, match="working directory"):
        parse_records(cwd_conflict.stdout)


def test_prune_removes_only_old_terminal_jobs(tmp_path) -> None:
    jobs_root = tmp_path / "state" / "compshare" / "jobs"
    old_job = jobs_root / "job-old"
    recent_job = jobs_root / "job-recent"
    for job_directory in (old_job, recent_job):
        job_directory.mkdir(parents=True)
        (job_directory / "command").write_text("true", encoding="utf-8")
        (job_directory / "name").write_text("", encoding="utf-8")
        (job_directory / "cwd").write_text("", encoding="utf-8")
        (job_directory / "exit_code").write_text("0", encoding="utf-8")
    (old_job / "created_at").write_text("1", encoding="utf-8")
    (old_job / "finished_at").write_text("1", encoding="utf-8")
    now = str(int(time.time()))
    (recent_job / "created_at").write_text(now, encoding="utf-8")
    (recent_job / "finished_at").write_text(now, encoding="utf-8")

    pruned = _run(prune_script(older_than=3600, delete=True), home=tmp_path)

    assert pruned.returncode == 0, pruned.stderr
    assert [record["JobId"] for record in parse_records(pruned.stdout)] == ["job-old"]
    assert not old_job.exists()
    assert recent_job.is_dir()
