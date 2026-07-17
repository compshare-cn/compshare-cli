from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from base64 import b64decode, b64encode
from pathlib import Path
from typing import Any, Dict, Optional

from compshare_cli.config import config_path

CACHE_VERSION = 1
DEFAULT_TTL = 3600
_CACHED_HOST_FIELDS = {
    "Password",
    "Region",
    "SshLoginCommand",
    "State",
    "UHostId",
    "Zone",
}
_DPAPI_PREFIX = "dpapi:"


def _protect_password(password: str) -> Optional[str]:
    if os.name != "nt":
        return password
    try:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

        raw = password.encode("utf-8")
        buffer = ctypes.create_string_buffer(raw)
        source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        protected = DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source),
            "CompShare SSH cache",
            None,
            None,
            None,
            0x1,  # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(protected),
        ):
            return None
        try:
            encrypted = ctypes.string_at(protected.data, protected.size)
        finally:
            ctypes.windll.kernel32.LocalFree(protected.data)
        return _DPAPI_PREFIX + b64encode(encrypted).decode("ascii")
    except (AttributeError, OSError, ValueError):
        return None


def _unprotect_password(password: str) -> Optional[str]:
    if os.name != "nt":
        return password
    if not password.startswith(_DPAPI_PREFIX):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

        raw = b64decode(password[len(_DPAPI_PREFIX) :], validate=True)
        buffer = ctypes.create_string_buffer(raw)
        source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        clear = DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0x1,  # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(clear),
        ):
            return None
        try:
            decrypted = ctypes.string_at(clear.data, clear.size)
        finally:
            ctypes.windll.kernel32.LocalFree(clear.data)
        return decrypted.decode("utf-8")
    except (AttributeError, OSError, UnicodeDecodeError, ValueError):
        return None


def ssh_cache_path() -> Path:
    override = os.environ.get("COMPSHARE_SSH_CACHE_FILE")
    if override:
        return Path(override).expanduser()
    return config_path().with_name("ssh-cache.json")


class SSHCredentialCache:
    """Short-lived, profile-scoped cache for API-provided SSH connection data."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or ssh_cache_path()

    @staticmethod
    def _key(profile: str, instance: str) -> str:
        return f"{profile}\0{instance}"

    def get(
        self,
        profile: str,
        instance: str,
        *,
        ttl: int = DEFAULT_TTL,
        now: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if ttl <= 0:
            return None
        data = self._read()
        raw = data.get("entries", {}).get(self._key(profile, instance))
        if not isinstance(raw, dict):
            return None
        cached_at = raw.get("cached_at")
        host = raw.get("host")
        current = time.time() if now is None else now
        if not isinstance(cached_at, (int, float)) or current - cached_at > ttl:
            return None
        if not isinstance(host, dict):
            return None
        if not host.get("SshLoginCommand"):
            return None
        result = dict(host)
        password = result.get("Password")
        if isinstance(password, str):
            clear = _unprotect_password(password)
            if clear is None:
                return None
            result["Password"] = clear
        return result

    def put(
        self,
        profile: str,
        instance: str,
        host: Dict[str, Any],
        *,
        now: Optional[float] = None,
    ) -> None:
        cached_host = {key: host[key] for key in _CACHED_HOST_FIELDS if host.get(key) is not None}
        if not cached_host.get("SshLoginCommand"):
            return
        password = cached_host.get("Password")
        if isinstance(password, str):
            protected = _protect_password(password)
            if protected is None:
                return
            cached_host["Password"] = protected
        data = self._read()
        entries = data.setdefault("entries", {})
        entries[self._key(profile, instance)] = {
            "cached_at": time.time() if now is None else now,
            "host": cached_host,
        }
        self._write(data)

    def delete(self, profile: str, instance: str) -> None:
        data = self._read()
        entries = data.get("entries", {})
        if not isinstance(entries, dict) or entries.pop(self._key(profile, instance), None) is None:
            return
        self._write(data)

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": CACHE_VERSION, "entries": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": CACHE_VERSION, "entries": {}}
        if (
            not isinstance(data, dict)
            or data.get("version") != CACHE_VERSION
            or not isinstance(data.get("entries"), dict)
        ):
            return {"version": CACHE_VERSION, "entries": {}}
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        temporary: Optional[Path] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.path.parent, stat.S_IRWXU)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
                handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            # Caching is an optimization and must never prevent an SSH connection.
            return
