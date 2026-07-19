from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from compshare_cli.errors import ConfigError

DEFAULT_PROFILE = "default"
DEFAULT_BASE_URL = "https://api.compshare.cn"
CREDENTIAL_ENVIRONMENT = {
    "public_key": "COMPSHARE_PUBLIC_KEY",
    "private_key": "COMPSHARE_PRIVATE_KEY",
}


def config_path() -> Path:
    override = os.environ.get("COMPSHARE_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "compshare" / "config.json"


@dataclass(frozen=True)
class Profile:
    public_key: str
    private_key: str

    def sdk_config(self, region: Optional[str] = None) -> Dict[str, Any]:
        config = {
            "public_key": self.public_key,
            "private_key": self.private_key,
            "base_url": DEFAULT_BASE_URL,
        }
        if region is not None:
            config["region"] = region
        return config


class ConfigStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or config_path()

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"current_profile": DEFAULT_PROFILE, "profiles": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"无法读取配置文件 {self.path}: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("profiles", {}), dict):
            raise ConfigError(f"配置文件格式无效: {self.path}")
        profiles = data.get("profiles", {})
        if any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(profile, dict)
            or any(
                key in profile and not isinstance(profile[key], str)
                for key in ("public_key", "private_key")
            )
            for name, profile in profiles.items()
        ):
            raise ConfigError(f"配置文件中的凭证格式无效: {self.path}")
        return data

    def save_profile(self, name: str, profile: Profile, *, activate: bool = True) -> None:
        self._validate_profile_name(name)
        data = self._read()
        profiles = data.setdefault("profiles", {})
        profiles[name] = {key: value for key, value in asdict(profile).items() if value is not None}
        if activate:
            data["current_profile"] = name
        self._write(data)

    def list_profiles(self) -> List[str]:
        return sorted(self._read().get("profiles", {}))

    def current_profile(self) -> str:
        return str(self._read().get("current_profile", DEFAULT_PROFILE))

    def credential_status(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Describe the selected credential sources without exposing credential values."""
        data = self._read()
        selected = str(
            name
            or os.environ.get("COMPSHARE_PROFILE")
            or data.get("current_profile", DEFAULT_PROFILE)
        )
        profiles = data.get("profiles", {})
        raw = profiles.get(selected, {})
        sources = {
            f"{field}_source": (
                "environment"
                if os.environ.get(environment)
                else "profile"
                if raw.get(field)
                else "missing"
            )
            for field, environment in CREDENTIAL_ENVIRONMENT.items()
        }
        unique_sources = set(sources.values())
        if unique_sources == {"environment"}:
            source = "environment"
        elif unique_sources == {"profile"}:
            source = "profile"
        elif unique_sources == {"missing"}:
            source = "unconfigured"
        elif "missing" in unique_sources:
            source = "incomplete"
        else:
            source = "mixed"
        return {
            "credential_source": source,
            "selected_profile": selected,
            "profile_exists": selected in profiles,
            "credential_sources": sources,
        }

    def use_profile(self, name: str) -> None:
        self._validate_profile_name(name)
        data = self._read()
        if name not in data.get("profiles", {}):
            raise ConfigError(f"Credential profile does not exist: {name}")
        data["current_profile"] = name
        self._write(data)

    def delete_profile(self, name: str) -> None:
        self._validate_profile_name(name)
        data = self._read()
        profiles = data.get("profiles", {})
        if name not in profiles:
            raise ConfigError(f"Credential profile does not exist: {name}")
        del profiles[name]
        if data.get("current_profile") == name:
            data["current_profile"] = next(iter(sorted(profiles)), DEFAULT_PROFILE)
        self._write(data)

    def load_language(self) -> Optional[str]:
        value = self._read().get("language")
        return str(value) if value else None

    def save_language(self, language: str) -> None:
        data = self._read()
        data["language"] = language
        self._write(data)

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
                handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ConfigError(f"无法写入配置文件 {self.path}: {exc}") from exc

    @staticmethod
    def _validate_profile_name(name: str) -> None:
        if not name.strip():
            raise ConfigError("凭证配置名称不能为空。")

    def load_profile(self, name: Optional[str] = None) -> Profile:
        data = self._read()
        selected = (
            name
            or os.environ.get("COMPSHARE_PROFILE")
            or data.get("current_profile", DEFAULT_PROFILE)
        )
        raw = data.get("profiles", {}).get(selected, {})

        public_key = os.environ.get(CREDENTIAL_ENVIRONMENT["public_key"]) or raw.get("public_key")
        private_key = os.environ.get(CREDENTIAL_ENVIRONMENT["private_key"]) or raw.get(
            "private_key"
        )
        if not public_key or not private_key:
            raise ConfigError(
                "尚未配置 API 密钥。请运行 `compshare config --name NAME`，或设置 "
                "COMPSHARE_PUBLIC_KEY 和 COMPSHARE_PRIVATE_KEY。"
            )

        return Profile(
            public_key=str(public_key),
            private_key=str(private_key),
        )
