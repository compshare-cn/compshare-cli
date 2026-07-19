from __future__ import annotations

import base64
import hashlib
import re
import secrets
import shlex
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr

JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DURATION_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[smhdw])$")
JOB_STATES = {
    "Starting",
    "Running",
    "Cancelling",
    "Succeeded",
    "Failed",
    "Cancelled",
    "Interrupted",
}


class RemoteJobProtocolError(ValueError):
    """Raised when the remote job helper returns malformed or error output."""


def new_job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"job-{stamp}-{secrets.token_hex(4)}"


def validate_job_id(value: str) -> str:
    if not JOB_ID_PATTERN.fullmatch(value):
        raise UsageError(
            tr(
                "Job ID must be 1-64 letters, numbers, dots, underscores, or hyphens, "
                "and must start with a letter or number."
            )
        )
    return value


def duration_seconds(value: str) -> int:
    match = DURATION_PATTERN.fullmatch(value.strip().casefold())
    if match is None:
        raise UsageError(tr("Duration must use a positive integer followed by s, m, h, d, or w."))
    factors = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return int(match.group("amount")) * factors[match.group("unit")]


def shell_command(script: str) -> str:
    """Wrap a helper script as one safely quoted OpenSSH remote command."""
    return f"sh -c {shlex.quote(script)}"


def joined_command(arguments: Sequence[str]) -> str:
    if not arguments:
        raise UsageError(tr("A remote command is required after --."))
    return shlex.join(arguments)


def _literal(value: str) -> str:
    return shlex.quote(value)


_COMMON_SCRIPT = r"""
set -u
umask 077

state_home=${XDG_STATE_HOME:-}
case "$state_home" in
  /*) ;;
  *)
    if [ -z "${HOME:-}" ]; then
      printf 'COMPSHARE_JOB_ERROR\t%s\n' \
        "$(printf '%s' 'HOME is not set on the instance.' | base64 | tr -d '\n')"
      exit 70
    fi
    state_home=$HOME/.local/state
    ;;
esac
jobs_root=$state_home/compshare/jobs
if ! mkdir -p "$jobs_root"; then
  job_directory_error="Unable to create remote job directory: $jobs_root"
  printf 'COMPSHARE_JOB_ERROR\t%s\n' \
    "$(printf '%s' "$job_directory_error" | base64 | tr -d '\n')"
  exit 73
fi

emit_value() {
  emit_key=$1
  emit_value=${2-}
  printf 'COMPSHARE_JOB_FIELD\t%s\t' "$emit_key"
  printf '%s' "$emit_value" | base64 | tr -d '\n'
  printf '\n'
}

emit_file() {
  emit_key=$1
  emit_path=$2
  printf 'COMPSHARE_JOB_FIELD\t%s\t' "$emit_key"
  if [ -f "$emit_path" ]; then
    base64 < "$emit_path" | tr -d '\n'
  fi
  printf '\n'
}

emit_error() {
  printf 'COMPSHARE_JOB_ERROR\t'
  printf '%s' "$1" | base64 | tr -d '\n'
  printf '\n'
  exit "${2:-1}"
}

read_value() {
  if [ -f "$1" ]; then
    cat "$1"
  fi
}

process_matches() {
  process_dir=$1
  process_pid=$(read_value "$process_dir/pid")
  case "$process_pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  if [ "$process_pid" -le 1 ] || ! kill -0 "$process_pid" 2>/dev/null; then
    return 1
  fi

  stored_boot=$(read_value "$process_dir/boot_id")
  if [ -n "$stored_boot" ] && [ -r /proc/sys/kernel/random/boot_id ]; then
    current_boot=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
    if [ -n "$current_boot" ] && [ "$stored_boot" != "$current_boot" ]; then
      return 1
    fi
  fi

  stored_start=$(read_value "$process_dir/process_start")
  if [ -n "$stored_start" ] && [ -r "/proc/$process_pid/stat" ]; then
    current_start=$(awk '{print $22}' "/proc/$process_pid/stat" 2>/dev/null || true)
    if [ -n "$current_start" ] && [ "$stored_start" != "$current_start" ]; then
      return 1
    fi
  fi
  return 0
}

job_state() {
  state_dir=$1
  if [ -f "$state_dir/cancelled" ]; then
    printf '%s' Cancelled
    return
  fi
  if [ -f "$state_dir/exit_code" ]; then
    state_exit=$(read_value "$state_dir/exit_code")
    if [ "$state_exit" = 0 ]; then
      printf '%s' Succeeded
    else
      printf '%s' Failed
    fi
    return
  fi
  if process_matches "$state_dir"; then
    if [ -f "$state_dir/cancel_requested" ]; then
      printf '%s' Cancelling
    else
      printf '%s' Running
    fi
    return
  fi
  if [ -f "$state_dir/pid" ]; then
    printf '%s' Interrupted
  else
    printf '%s' Starting
  fi
}

emit_job() {
  emit_dir=$1
  emit_existing=${2:-false}
  printf 'COMPSHARE_JOB_BEGIN\n'
  emit_value JobId "$(basename "$emit_dir")"
  emit_file Name "$emit_dir/name"
  emit_value State "$(job_state "$emit_dir")"
  emit_file PID "$emit_dir/pid"
  emit_file ExitCode "$emit_dir/exit_code"
  emit_file CreatedTime "$emit_dir/created_at"
  emit_file StartedTime "$emit_dir/started_at"
  emit_file FinishedTime "$emit_dir/finished_at"
  emit_file Cwd "$emit_dir/cwd"
  emit_file Command "$emit_dir/command"
  emit_value Existing "$emit_existing"
  printf 'COMPSHARE_JOB_END\n'
}
"""


_RUNNER_SCRIPT = r"""#!/bin/sh
set -u
umask 077
job_dir=$1
finished=0
child_pid=

atomic_value() {
  atomic_target=$1
  atomic_value=${2-}
  atomic_temp=$atomic_target.tmp.$$
  printf '%s\n' "$atomic_value" > "$atomic_temp"
  mv "$atomic_temp" "$atomic_target"
}

finish_job() {
  finish_code=$1
  if [ "$finished" -ne 0 ]; then
    return
  fi
  finished=1
  atomic_value "$job_dir/finished_at" "$(date +%s)"
  atomic_value "$job_dir/exit_code" "$finish_code"
}

cancel_job() {
  trap - TERM INT HUP
  if [ -n "$child_pid" ]; then
    kill -TERM "$child_pid" 2>/dev/null || true
  fi
  : > "$job_dir/cancelled.tmp.$$"
  mv "$job_dir/cancelled.tmp.$$" "$job_dir/cancelled"
  finish_job 143
  exit 143
}

trap cancel_job TERM INT HUP
atomic_value "$job_dir/pid" "$$"
if [ -r /proc/sys/kernel/random/boot_id ]; then
  atomic_value "$job_dir/boot_id" "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
fi
if [ -r "/proc/$$/stat" ]; then
  atomic_value "$job_dir/process_start" "$(awk '{print $22}' "/proc/$$/stat" 2>/dev/null || true)"
fi
atomic_value "$job_dir/started_at" "$(date +%s)"

if [ -f "$job_dir/cancel_requested" ]; then
  cancel_job
fi

job_cwd=$(cat "$job_dir/cwd")
if [ -n "$job_cwd" ] && ! cd "$job_cwd"; then
  printf 'Unable to enter working directory: %s\n' "$job_cwd" >> "$job_dir/stderr.log"
  finish_job 125
  exit 125
fi

job_command=$(cat "$job_dir/command")
sh -c "$job_command" >> "$job_dir/stdout.log" 2>> "$job_dir/stderr.log" &
child_pid=$!
atomic_value "$job_dir/child_pid" "$child_pid"
wait "$child_pid"
job_exit=$?
child_pid=
finish_job "$job_exit"
exit "$job_exit"
"""


def submit_script(
    job_id: str,
    command: str,
    *,
    name: Optional[str] = None,
    cwd: Optional[str] = None,
) -> str:
    validate_job_id(job_id)
    specification = f"{command}\0{cwd or ''}"
    specification_hash = hashlib.sha256(specification.encode("utf-8")).hexdigest()
    return (
        _COMMON_SCRIPT
        + f"""
job_id={_literal(job_id)}
job_dir=$jobs_root/$job_id
specification_hash={_literal(specification_hash)}
if [ -d "$job_dir" ]; then
  existing_hash=$(read_value "$job_dir/specification_sha256")
  if [ "$existing_hash" != "$specification_hash" ]; then
    emit_error "Job $job_id already exists with a different command or working directory." 65
  fi
  emit_job "$job_dir" true
  exit 0
fi

if ! mkdir "$job_dir"; then
  emit_error "Unable to create remote job $job_id." 73
fi
chmod 700 "$job_dir" 2>/dev/null || true
printf '%s' {_literal(command)} > "$job_dir/command"
printf '%s' {_literal(name or "")} > "$job_dir/name"
printf '%s' {_literal(cwd or "")} > "$job_dir/cwd"
printf '%s\n' "$specification_hash" > "$job_dir/specification_sha256"
printf '%s\n' "$(date +%s)" > "$job_dir/created_at"
: > "$job_dir/stdout.log"
: > "$job_dir/stderr.log"
cat > "$job_dir/runner.sh" <<'COMPSHARE_JOB_RUNNER'
{_RUNNER_SCRIPT}COMPSHARE_JOB_RUNNER
chmod 700 "$job_dir/runner.sh"

fail_launch() {{
  launch_code=$1
  launch_message=$2
  printf '%s\n' "$launch_message" >> "$job_dir/stderr.log"
  printf '%s\n' "$launch_code" > "$job_dir/exit_code.tmp.$$"
  mv "$job_dir/exit_code.tmp.$$" "$job_dir/exit_code"
  printf '%s\n' "$(date +%s)" > "$job_dir/finished_at.tmp.$$"
  mv "$job_dir/finished_at.tmp.$$" "$job_dir/finished_at"
  emit_error "$launch_message" "$launch_code"
}}

if ! command -v setsid >/dev/null 2>&1; then
  fail_launch 69 "setsid is required on the instance to start durable jobs."
fi
if ! command -v nohup >/dev/null 2>&1; then
  fail_launch 69 "nohup is required on the instance to start durable jobs."
fi

nohup setsid "$job_dir/runner.sh" "$job_dir" </dev/null >> "$job_dir/launcher.log" 2>&1 &
launcher_pid=$!
attempt=0
while [ ! -s "$job_dir/pid" ] && [ "$attempt" -lt 100 ]; do
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 0.05
done
if [ ! -s "$job_dir/pid" ]; then
  kill "$launcher_pid" 2>/dev/null || true
  launcher_error=$(cat "$job_dir/launcher.log" 2>/dev/null || true)
  fail_launch 70 "Unable to start remote job $job_id: $launcher_error"
fi
emit_job "$job_dir" false
"""
    )


def show_script(job_id: str) -> str:
    validate_job_id(job_id)
    return (
        _COMMON_SCRIPT
        + f"""
job_id={_literal(job_id)}
job_dir=$jobs_root/$job_id
[ -d "$job_dir" ] || emit_error "Remote job $job_id was not found." 66
emit_job "$job_dir" false
"""
    )


def list_script() -> str:
    return (
        _COMMON_SCRIPT
        + r"""
for job_dir in "$jobs_root"/*; do
  [ -d "$job_dir" ] || continue
  emit_job "$job_dir" false
done
"""
    )


def logs_script(
    job_id: str,
    *,
    tail: Optional[int],
    stdout_offset: Optional[int],
    stderr_offset: Optional[int],
    limit: int,
) -> str:
    validate_job_id(job_id)
    if tail is not None and tail < 1:
        raise UsageError(tr("--tail must be positive."))
    if stdout_offset is not None and stdout_offset < 0:
        raise UsageError(tr("--stdout-offset cannot be negative."))
    if stderr_offset is not None and stderr_offset < 0:
        raise UsageError(tr("--stderr-offset cannot be negative."))
    if limit < 1:
        raise UsageError(tr("--limit must be positive."))
    offset_mode = stdout_offset is not None or stderr_offset is not None
    stdout_offset = stdout_offset or 0
    stderr_offset = stderr_offset or 0
    if offset_mode:
        content_script = f"""
emit_value Mode offset
emit_value Limit {limit}
emit_value StdoutOffset {stdout_offset}
emit_value StderrOffset {stderr_offset}
printf 'COMPSHARE_JOB_FIELD\\tStdout\\t'
dd if="$job_dir/stdout.log" bs=1 skip={stdout_offset} count={limit} 2>/dev/null \
  | base64 | tr -d '\\n'
printf '\\n'
printf 'COMPSHARE_JOB_FIELD\\tStderr\\t'
dd if="$job_dir/stderr.log" bs=1 skip={stderr_offset} count={limit} 2>/dev/null \
  | base64 | tr -d '\\n'
printf '\\n'
"""
    else:
        selected_tail = tail or 200
        content_script = f"""
emit_value Mode tail
emit_value Tail {selected_tail}
printf 'COMPSHARE_JOB_FIELD\\tStdout\\t'
tail -n {selected_tail} "$job_dir/stdout.log" 2>/dev/null | base64 | tr -d '\\n'
printf '\\n'
printf 'COMPSHARE_JOB_FIELD\\tStderr\\t'
tail -n {selected_tail} "$job_dir/stderr.log" 2>/dev/null | base64 | tr -d '\\n'
printf '\\n'
"""
    return (
        _COMMON_SCRIPT
        + f"""
job_id={_literal(job_id)}
job_dir=$jobs_root/$job_id
[ -d "$job_dir" ] || emit_error "Remote job $job_id was not found." 66
stdout_size=$(wc -c < "$job_dir/stdout.log" | tr -d ' ')
stderr_size=$(wc -c < "$job_dir/stderr.log" | tr -d ' ')
printf 'COMPSHARE_JOB_BEGIN\n'
emit_value JobId "$job_id"
emit_value State "$(job_state "$job_dir")"
emit_value StdoutSize "$stdout_size"
emit_value StderrSize "$stderr_size"
{content_script}
printf 'COMPSHARE_JOB_END\n'
"""
    )


def follow_script(job_id: str, *, tail: int, stream: str) -> str:
    validate_job_id(job_id)
    if tail < 1:
        raise UsageError(tr("--tail must be positive."))
    if stream not in {"all", "stdout", "stderr"}:
        raise UsageError(tr("--stream must be all, stdout, or stderr."))
    if stream == "stdout":
        files = '"$job_dir/stdout.log"'
    elif stream == "stderr":
        files = '"$job_dir/stderr.log"'
    else:
        files = '"$job_dir/stdout.log" "$job_dir/stderr.log"'
    return (
        _COMMON_SCRIPT
        + f"""
job_id={_literal(job_id)}
job_dir=$jobs_root/$job_id
[ -d "$job_dir" ] || {{
  printf 'Remote job %s was not found.\n' "$job_id" >&2
  exit 66
}}
current_state=$(job_state "$job_dir")
case "$current_state" in
  Succeeded|Failed|Cancelled|Interrupted)
    tail -n {tail} {files}
    exit 0
    ;;
esac
tail -n {tail} -F {files} &
tail_pid=$!
trap 'kill "$tail_pid" 2>/dev/null || true; exit 130' INT TERM HUP
while :; do
  current_state=$(job_state "$job_dir")
  case "$current_state" in
    Succeeded|Failed|Cancelled|Interrupted) break ;;
  esac
  sleep 1
done
sleep 0.2
kill "$tail_pid" 2>/dev/null || true
wait "$tail_pid" 2>/dev/null || true
"""
    )


def wait_script(job_id: str, *, timeout: int, interval: int) -> str:
    validate_job_id(job_id)
    if timeout < 1 or interval < 1:
        raise UsageError(tr("Wait timeout and polling interval must be positive."))
    return (
        _COMMON_SCRIPT
        + f"""
job_id={_literal(job_id)}
job_dir=$jobs_root/$job_id
[ -d "$job_dir" ] || emit_error "Remote job $job_id was not found." 66
started_wait=$(date +%s)
wait_timed_out=false
while :; do
  current_state=$(job_state "$job_dir")
  case "$current_state" in
    Succeeded|Failed|Cancelled|Interrupted) break ;;
  esac
  current_time=$(date +%s)
  if [ $((current_time - started_wait)) -ge {timeout} ]; then
    wait_timed_out=true
    break
  fi
  sleep {interval}
done
emit_job "$job_dir" false
printf 'COMPSHARE_JOB_BEGIN\n'
emit_value WaitTimedOut "$wait_timed_out"
printf 'COMPSHARE_JOB_END\n'
"""
    )


def cancel_script(job_id: str, *, force: bool) -> str:
    validate_job_id(job_id)
    signal = "KILL" if force else "TERM"
    forced_block = (
        r"""
sleep 0.2
: > "$job_dir/cancelled.tmp.$$"
mv "$job_dir/cancelled.tmp.$$" "$job_dir/cancelled"
printf '%s\n' 137 > "$job_dir/exit_code.tmp.$$"
mv "$job_dir/exit_code.tmp.$$" "$job_dir/exit_code"
printf '%s\n' "$(date +%s)" > "$job_dir/finished_at.tmp.$$"
mv "$job_dir/finished_at.tmp.$$" "$job_dir/finished_at"
"""
        if force
        else "sleep 0.2\n"
    )
    return (
        _COMMON_SCRIPT
        + f"""
job_id={_literal(job_id)}
job_dir=$jobs_root/$job_id
[ -d "$job_dir" ] || emit_error "Remote job $job_id was not found." 66
current_state=$(job_state "$job_dir")
case "$current_state" in
  Succeeded|Failed|Cancelled|Interrupted)
    emit_job "$job_dir" false
    exit 0
    ;;
esac
: > "$job_dir/cancel_requested"
job_pid=$(read_value "$job_dir/pid")
case "$job_pid" in
  ''|*[!0-9]*) ;;
  *)
    if [ "$job_pid" -gt 1 ] && process_matches "$job_dir"; then
      kill -{signal} "-$job_pid" 2>/dev/null || kill -{signal} "$job_pid" 2>/dev/null || true
    fi
    ;;
esac
{forced_block}
emit_job "$job_dir" false
"""
    )


def prune_script(*, older_than: int, delete: bool) -> str:
    if older_than < 1:
        raise UsageError(tr("Prune duration must be positive."))
    delete_command = 'rm -rf "$job_dir"' if delete else ":"
    return (
        _COMMON_SCRIPT
        + f"""
now=$(date +%s)
for job_dir in "$jobs_root"/*; do
  [ -d "$job_dir" ] || continue
  current_state=$(job_state "$job_dir")
  case "$current_state" in
    Succeeded|Failed|Cancelled|Interrupted) ;;
    *) continue ;;
  esac
  reference_time=$(read_value "$job_dir/finished_at")
  if [ -z "$reference_time" ]; then
    reference_time=$(read_value "$job_dir/created_at")
  fi
  case "$reference_time" in
    ''|*[!0-9]*) continue ;;
  esac
  if [ $((now - reference_time)) -lt {older_than} ]; then
    continue
  fi
  emit_job "$job_dir" false
  {delete_command}
done
"""
    )


def parse_records(output: str) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        if raw_line == "COMPSHARE_JOB_BEGIN":
            if current is not None:
                raise RemoteJobProtocolError("Remote job response contains nested records.")
            current = {}
            continue
        if raw_line == "COMPSHARE_JOB_END":
            if current is None:
                raise RemoteJobProtocolError("Remote job response ended an unknown record.")
            records.append(current)
            current = None
            continue
        parts = raw_line.split("\t")
        if parts[0] == "COMPSHARE_JOB_ERROR" and len(parts) == 2:
            raise RemoteJobProtocolError(_decode(parts[1]))
        if parts[0] == "COMPSHARE_JOB_FIELD" and len(parts) == 3 and current is not None:
            current[parts[1]] = _decode(parts[2])
            continue
        if current is None and not raw_line.startswith("COMPSHARE_JOB_"):
            continue
        raise RemoteJobProtocolError("Remote job response used an unsupported format.")
    if current is not None:
        raise RemoteJobProtocolError("Remote job response ended before the record was complete.")
    return records


def normalized_record(record: Dict[str, str]) -> Dict[str, object]:
    result: Dict[str, object] = dict(record)
    for key in (
        "PID",
        "ExitCode",
        "CreatedTime",
        "StartedTime",
        "FinishedTime",
        "StdoutOffset",
        "StderrOffset",
        "StdoutSize",
        "StderrSize",
        "Tail",
        "Limit",
    ):
        if key not in result:
            continue
        value = result.get(key)
        if value in {None, ""}:
            result[key] = None
            continue
        try:
            result[key] = int(str(value))
        except ValueError:
            pass
    for key in ("Existing", "WaitTimedOut"):
        value = result.get(key)
        if value is not None:
            result[key] = str(value).casefold() == "true"
    if result.get("Mode") == "offset":
        for stream in ("Stdout", "Stderr"):
            size = int(result.get(f"{stream}Size") or 0)
            offset = int(result.get(f"{stream}Offset") or 0)
            limit = int(result.get("Limit") or 0)
            next_offset = min(size, offset + limit)
            result[f"{stream}NextOffset"] = next_offset
            result[f"{stream}EOF"] = next_offset >= size
    return result


def _decode(value: str) -> str:
    try:
        return base64.b64decode(value, validate=True).decode("utf-8", errors="replace")
    except ValueError as exc:
        raise RemoteJobProtocolError("Remote job response contains invalid Base64 data.") from exc
