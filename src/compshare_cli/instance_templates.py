from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from compshare_cli.config import config_path
from compshare_cli.errors import ConfigError, UsageError

TEMPLATE_SCHEMA_VERSION = 1

TEXT_PARAMETERS = frozenset(
    {
        "gpu",
        "memory",
        "image",
        "image_source",
        "region",
        "zone",
        "disk",
        "disk_type",
        "charge",
        "name",
        "platform",
        "remark",
        "firewall",
    }
)
INTEGER_PARAMETERS = frozenset({"count", "cpu", "quantity", "max_count"})
LIST_PARAMETERS = frozenset({"data_disk"})
BOOLEAN_PARAMETERS = frozenset({"us3"})
TEMPLATE_PARAMETERS = TEXT_PARAMETERS | INTEGER_PARAMETERS | LIST_PARAMETERS | BOOLEAN_PARAMETERS


def template_path() -> Path:
    override = os.environ.get("COMPSHARE_TEMPLATE_FILE")
    if override:
        return Path(override).expanduser()
    return config_path().parent / "instance-templates.json"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validated_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    unknown = sorted(set(parameters) - TEMPLATE_PARAMETERS)
    if unknown:
        raise ConfigError(f"Unknown instance template parameters: {', '.join(unknown)}")

    validated: Dict[str, Any] = {}
    for key, value in parameters.items():
        if value is None:
            continue
        if key in TEXT_PARAMETERS:
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"Instance template parameter {key} must be a non-empty string.")
            validated[key] = value
        elif key in INTEGER_PARAMETERS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"Instance template parameter {key} must be a positive integer.")
            validated[key] = value
        elif key in LIST_PARAMETERS:
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ConfigError(f"Instance template parameter {key} must be a string list.")
            validated[key] = list(value)
        elif key in BOOLEAN_PARAMETERS:
            if not isinstance(value, bool):
                raise ConfigError(f"Instance template parameter {key} must be a boolean.")
            validated[key] = value
    return validated


class InstanceTemplateStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or template_path()

    def list(self) -> List[Dict[str, Any]]:
        templates = self._read()["templates"]
        return [dict(templates[name]) for name in sorted(templates, key=str.casefold)]

    def get(self, name: str) -> Dict[str, Any]:
        template = self._read()["templates"].get(name)
        if template is None:
            raise UsageError(f"Instance template does not exist: {name}")
        return dict(template)

    def save(
        self,
        name: str,
        parameters: Dict[str, Any],
        *,
        description: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        if not name.strip():
            raise UsageError("Instance template name cannot be empty.")
        clean = _validated_parameters(parameters)
        if not clean:
            raise UsageError("Specify at least one instance template parameter.")
        if description is not None and not isinstance(description, str):
            raise UsageError("Instance template description must be a string.")

        data = self._read()
        existing = data["templates"].get(name)
        if existing is not None and not overwrite:
            raise UsageError(
                f"Instance template already exists: {name}. Use --force to replace it."
            )
        now = _timestamp()
        template = {
            "name": name,
            "description": (
                description
                if description is not None
                else existing.get("description", "")
                if existing
                else ""
            ),
            "parameters": clean,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        data["templates"][name] = template
        self._write(data)
        return dict(template)

    def delete(self, name: str) -> None:
        data = self._read()
        if name not in data["templates"]:
            raise UsageError(f"Instance template does not exist: {name}")
        del data["templates"][name]
        self._write(data)

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": TEMPLATE_SCHEMA_VERSION, "templates": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Unable to read instance templates {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Invalid instance template file: {self.path}")
        if data.get("schema_version") != TEMPLATE_SCHEMA_VERSION:
            raise ConfigError(
                f"Unsupported instance template schema in {self.path}: {data.get('schema_version')}"
            )
        templates = data.get("templates")
        if not isinstance(templates, dict):
            raise ConfigError(f"Invalid instance template file: {self.path}")
        normalized: Dict[str, Dict[str, Any]] = {}
        for name, template in templates.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(template, dict):
                raise ConfigError(f"Invalid instance template file: {self.path}")
            parameters = template.get("parameters")
            if not isinstance(parameters, dict):
                raise ConfigError(f"Invalid instance template {name} in {self.path}")
            description = template.get("description", "")
            if not isinstance(description, str):
                raise ConfigError(f"Invalid instance template {name} in {self.path}")
            normalized[name] = {
                "name": name,
                "description": description,
                "parameters": _validated_parameters(parameters),
                "created_at": str(template.get("created_at", "")),
                "updated_at": str(template.get("updated_at", "")),
            }
        return {"schema_version": TEMPLATE_SCHEMA_VERSION, "templates": normalized}

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
            raise ConfigError(f"Unable to write instance templates {self.path}: {exc}") from exc
