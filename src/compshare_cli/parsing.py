from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from compshare_cli.errors import UsageError

_SIZE_RE = re.compile(r"^\s*(\d+)\s*(mib|mb|gib|gb|m|g)?\s*$", re.IGNORECASE)


def memory_mib(value: str) -> int:
    match = _SIZE_RE.match(value)
    if not match:
        raise UsageError(f"无效的内存大小: {value}，示例：64GiB")
    amount = int(match.group(1))
    unit = (match.group(2) or "gib").lower()
    result = amount if unit in {"mib", "mb", "m"} else amount * 1024
    if result <= 0 or result % 1024 != 0:
        raise UsageError("内存必须大于 0，且换算后为 1024 MiB 的整数倍")
    return result


def disk_gib(value: str) -> int:
    match = _SIZE_RE.match(value)
    if not match:
        raise UsageError(f"无效的磁盘大小: {value}，示例：100GiB")
    amount = int(match.group(1))
    unit = (match.group(2) or "gib").lower()
    if unit in {"mib", "mb", "m"}:
        if amount % 1024:
            raise UsageError("磁盘 MiB 数必须能换算成整数 GiB")
        amount //= 1024
    if amount <= 0:
        raise UsageError("磁盘大小必须大于 0")
    return amount


def encode_password(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def timestamp(value: str) -> int:
    if value.isdigit():
        return int(value)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UsageError("时间必须是 Unix 时间戳或 ISO 8601 格式") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


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
    except OSError as exc:
        raise UsageError(f"无法读取文件 {path}: {exc}") from exc


def read_base64(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise UsageError(f"无法读取文件 {path}: {exc}") from exc
