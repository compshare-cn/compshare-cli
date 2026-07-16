from __future__ import annotations

import base64
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr

_SIZE_RE = re.compile(r"^\s*(\d+)\s*(mib|mb|gib|gb|m|g)?\s*$", re.IGNORECASE)


def memory_mib(value: str) -> int:
    match = _SIZE_RE.match(value)
    if not match:
        raise UsageError(tr("Invalid memory size: {value}. Example: 64GiB", value=value))
    amount = int(match.group(1))
    unit = (match.group(2) or "gib").lower()
    result = amount if unit in {"mib", "mb", "m"} else amount * 1024
    if result <= 0 or result % 1024 != 0:
        raise UsageError(tr("Memory must be positive and resolve to whole GiB."))
    return result


def disk_gib(value: str) -> int:
    match = _SIZE_RE.match(value)
    if not match:
        raise UsageError(tr("Invalid disk size: {value}. Example: 100GiB", value=value))
    amount = int(match.group(1))
    unit = (match.group(2) or "gib").lower()
    if unit in {"mib", "mb", "m"}:
        if amount % 1024:
            raise UsageError(tr("Disk MiB must resolve to whole GiB."))
        amount //= 1024
    if amount <= 0:
        raise UsageError(tr("Disk size must be positive."))
    return amount


def encode_password(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def timestamp(value: str) -> int:
    relative = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", value, re.IGNORECASE)
    if relative:
        amount = int(relative.group(1))
        seconds = {"m": 60, "h": 3600, "d": 86400}[relative.group(2).lower()]
        return int(time.time()) + amount * seconds
    if value.isdigit():
        return int(value)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UsageError(
            tr("Time must be a Unix timestamp, ISO 8601 value, or relative value like 30m or 2h.")
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def past_timestamp(value: str) -> int:
    """Parse an absolute time or a duration such as 7d before the current time."""
    relative = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", value, re.IGNORECASE)
    if not relative:
        return timestamp(value)
    amount = int(relative.group(1))
    seconds = {"m": 60, "h": 3600, "d": 86400}[relative.group(2).lower()]
    return int(time.time()) - amount * seconds


def money(value: str) -> Decimal:
    """Parse a positive CNY amount with no more than two decimal places."""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise UsageError(tr("Invalid amount: {value}. Example: 1000.50", value=value)) from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise UsageError(tr("Amount must be positive and use at most two decimal places."))
    return amount


def money_cents(value: str) -> int:
    return int(money(value) * 100)


def compact(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def split_csv(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        result.extend(item.strip() for item in value.split(",") if item.strip())
    return result


def read_text(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UsageError(tr("Unable to read file {path}: {error}", path=path, error=exc)) from exc


def read_base64(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise UsageError(tr("Unable to read file {path}: {error}", path=path, error=exc)) from exc
