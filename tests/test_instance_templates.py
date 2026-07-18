import json
import os
import stat

import pytest

from compshare_cli.errors import ConfigError, UsageError
from compshare_cli.instance_templates import InstanceTemplateStore


def test_template_store_round_trip_and_permissions(tmp_path) -> None:
    path = tmp_path / "config" / "instance-templates.json"
    store = InstanceTemplateStore(path)

    saved = store.save(
        "训练配置",
        {
            "gpu": "4090",
            "count": 1,
            "data_disk": ["200GiB:CLOUD_SSD"],
            "us3": False,
        },
        description="training",
    )

    assert saved["name"] == "训练配置"
    assert store.get("训练配置")["parameters"]["data_disk"] == ["200GiB:CLOUD_SSD"]
    assert [item["name"] for item in store.list()] == ["训练配置"]
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_template_store_requires_force_to_replace(tmp_path) -> None:
    store = InstanceTemplateStore(tmp_path / "templates.json")
    original = store.save("training", {"gpu": "4090"}, description="first")

    with pytest.raises(UsageError, match="already exists"):
        store.save("training", {"gpu": "A100"})

    replaced = store.save("training", {"gpu": "A100"}, overwrite=True)
    assert replaced["parameters"]["gpu"] == "A100"
    assert replaced["created_at"] == original["created_at"]


def test_template_store_rejects_unknown_or_invalid_parameters(tmp_path) -> None:
    store = InstanceTemplateStore(tmp_path / "templates.json")

    with pytest.raises(ConfigError, match="Unknown"):
        store.save("bad", {"password": "secret"})
    with pytest.raises(ConfigError, match="positive integer"):
        store.save("bad", {"count": 0})
    with pytest.raises(UsageError, match="at least one"):
        store.save("empty", {})


def test_template_store_reports_corrupt_file(tmp_path) -> None:
    path = tmp_path / "templates.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ConfigError, match="Unable to read"):
        InstanceTemplateStore(path).list()


def test_template_store_rejects_unsupported_schema(tmp_path) -> None:
    path = tmp_path / "templates.json"
    path.write_text(
        json.dumps({"schema_version": 2, "templates": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Unsupported"):
        InstanceTemplateStore(path).list()
