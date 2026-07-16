import json
import stat
from pathlib import Path

import pytest

from compshare_cli.config import ConfigStore, Profile
from compshare_cli.errors import ConfigError
from compshare_cli.runtime import Runtime


def test_profile_round_trip_and_file_permissions(monkeypatch, tmp_path) -> None:
    for name in (
        "COMPSHARE_PROFILE",
        "COMPSHARE_PUBLIC_KEY",
        "COMPSHARE_PRIVATE_KEY",
        "COMPSHARE_REGION",
        "COMPSHARE_ZONE",
        "COMPSHARE_PROJECT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    expected = Profile("public", "private")
    store.save_profile("testing", expected)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert store.load_profile("testing") == expected
    saved = json.loads(path.read_text(encoding="utf-8"))["profiles"]["testing"]
    assert set(saved) == {"public_key", "private_key"}


def test_environment_overrides_profile(monkeypatch, tmp_path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    store.save_profile("default", Profile("stored-public", "stored-private"))
    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "env-public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "env-private")

    loaded = store.load_profile()
    assert loaded.public_key == "env-public"
    assert loaded.private_key == "env-private"
    assert set(vars(loaded)) == {"public_key", "private_key"}


def test_language_is_saved_outside_credential_profiles(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.save_profile("default", Profile("public", "private"))
    store.save_language("en")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert store.load_language() == "en"
    assert saved["language"] == "en"
    assert set(saved["profiles"]["default"]) == {"public_key", "private_key"}


def test_profile_management(tmp_path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    store.save_profile("alpha", Profile("a", "secret-a"))
    store.save_profile("beta", Profile("b", "secret-b"), activate=False)

    assert store.list_profiles() == ["alpha", "beta"]
    assert store.current_profile() == "alpha"
    store.use_profile("beta")
    assert store.current_profile() == "beta"
    store.delete_profile("beta")
    assert store.list_profiles() == ["alpha"]
    assert store.current_profile() == "alpha"


def test_invalid_profile_data_is_reported_as_config_error(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"profiles":{"broken":"not-an-object"}}', encoding="utf-8")

    with pytest.raises(ConfigError, match="凭证格式无效"):
        ConfigStore(path).load_profile("broken")

    path.write_text('{"profiles":{"broken":{"public_key":123}}}', encoding="utf-8")
    with pytest.raises(ConfigError, match="凭证格式无效"):
        ConfigStore(path).load_profile("broken")


def test_blank_profile_name_is_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError, match="不能为空"):
        ConfigStore(tmp_path / "config.json").save_profile("  ", Profile("public", "private"))


def test_failed_config_replace_removes_temporary_file(monkeypatch, tmp_path) -> None:
    original_replace = Path.replace

    def fail_temporary_replace(path, target):
        if path.suffix == ".tmp":
            raise OSError("simulated replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_temporary_replace)
    with pytest.raises(ConfigError, match="无法写入配置文件"):
        ConfigStore(tmp_path / "config.json").save_profile("default", Profile("public", "private"))

    assert list(tmp_path.glob(".*.tmp")) == []


def test_runtime_location_is_independent_from_credentials(monkeypatch) -> None:
    monkeypatch.delenv("COMPSHARE_REGION", raising=False)
    monkeypatch.delenv("COMPSHARE_ZONE", raising=False)
    monkeypatch.setenv("COMPSHARE_ZONE", "cn-sh2-02")
    state = Runtime()
    assert state.region == "cn-sh2"
    assert state.zone == "cn-sh2-02"

    monkeypatch.setenv("COMPSHARE_REGION", "cn-bj2")
    monkeypatch.setenv("COMPSHARE_ZONE", "cn-bj2-03")
    state = Runtime()
    assert state.region == "cn-bj2"
    assert state.zone == "cn-bj2-03"
