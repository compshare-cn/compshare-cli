import json
import os
import stat

import pytest

from compshare_cli import ssh_cache
from compshare_cli.ssh_cache import SSHCredentialCache


def _host(password="secret"):
    return {
        "UHostId": "uhost-1",
        "Region": "cn-wlcb",
        "Zone": "cn-wlcb-01",
        "State": "Running",
        "SshLoginCommand": "ssh root@example.invalid",
        "Password": password,
        "Unrelated": "not-cached",
    }


def test_ssh_cache_round_trip_is_profile_scoped_and_permission_restricted(tmp_path) -> None:
    path = tmp_path / "ssh-cache.json"
    cache = SSHCredentialCache(path)
    cache.put("alpha", "uhost-1", _host(), now=100)

    assert cache.get("alpha", "uhost-1", ttl=60, now=150) == {
        key: value for key, value in _host().items() if key != "Unrelated"
    }
    assert cache.get("beta", "uhost-1", ttl=60, now=150) is None
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved_host = next(iter(saved["entries"].values()))["host"]
    assert "Unrelated" not in saved_host
    if os.name == "nt":
        assert saved_host["Password"].startswith("dpapi:")
        assert saved_host["Password"] != _host()["Password"]


def test_ssh_cache_expires_and_can_be_deleted(tmp_path) -> None:
    cache = SSHCredentialCache(tmp_path / "ssh-cache.json")
    cache.put("default", "uhost-1", _host(), now=100)

    assert cache.get("default", "uhost-1", ttl=60, now=161) is None
    assert cache.get("default", "uhost-1", ttl=60, now=160) is not None
    cache.delete("default", "uhost-1")
    assert cache.get("default", "uhost-1", ttl=60, now=150) is None


def test_corrupt_ssh_cache_is_ignored(tmp_path) -> None:
    path = tmp_path / "ssh-cache.json"
    path.write_text("not json", encoding="utf-8")

    assert SSHCredentialCache(path).get("default", "uhost-1") is None


@pytest.mark.parametrize("timestamp", [200, float("nan"), float("inf"), "invalid", None])
def test_invalid_cache_timestamps_are_ignored(tmp_path, timestamp) -> None:
    cache = SSHCredentialCache(tmp_path / "ssh-cache.json")
    cache.put("default", "uhost-1", _host(), now=timestamp if timestamp is not None else 100)
    data = json.loads(cache.path.read_text())
    data["entries"]["default\0uhost-1"]["cached_at"] = timestamp
    cache.path.write_text(json.dumps(data))
    assert cache.get("default", "uhost-1", now=150) is None


def test_non_utf8_cache_is_ignored(tmp_path) -> None:
    path = tmp_path / "ssh-cache.json"
    path.write_bytes(b"\xff\xfe")
    assert SSHCredentialCache(path).get("default", "uhost-1") is None


def test_cache_does_not_change_existing_parent_permissions(tmp_path) -> None:
    tmp_path.chmod(0o755)
    permissions = stat.S_IMODE(tmp_path.stat().st_mode)
    SSHCredentialCache(tmp_path / "ssh-cache.json").put("default", "uhost-1", _host())
    assert stat.S_IMODE(tmp_path.stat().st_mode) == permissions


@pytest.mark.parametrize("field", ["Region", "Zone", "SshLoginCommand", "Password"])
def test_malformed_cached_host_is_ignored(tmp_path, field) -> None:
    cache = SSHCredentialCache(tmp_path / "ssh-cache.json")
    host = _host()
    host[field] = {"invalid": "value"}
    cache.put("default", "uhost-1", host, now=100)
    assert cache.get("default", "uhost-1", now=150) is None


@pytest.mark.parametrize("data", [[], {"version": 2, "entries": {}}, {"version": 1, "entries": []}])
def test_invalid_cache_schema_is_ignored(tmp_path, data) -> None:
    path = tmp_path / "ssh-cache.json"
    path.write_text(json.dumps(data))
    assert SSHCredentialCache(path).get("default", "uhost-1") is None


def test_failed_cache_write_keeps_previous_credentials_and_removes_temporary_file(
    monkeypatch, tmp_path
) -> None:
    cache = SSHCredentialCache(tmp_path / "private" / "ssh-cache.json")
    cache.put("default", "uhost-1", _host("old-password"), now=100)
    if os.name != "nt":
        assert stat.S_IMODE(cache.path.parent.stat().st_mode) == 0o700

    def fail(*_):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(type(cache.path), "replace", fail)
    cache.put("default", "uhost-1", _host("new-password"), now=101)
    assert cache.get("default", "uhost-1", now=150)["Password"] == "old-password"
    assert list(cache.path.parent.iterdir()) == [cache.path]


def test_password_protection_failure_disables_caching(monkeypatch, tmp_path) -> None:
    cache = SSHCredentialCache(tmp_path / "ssh-cache.json")
    monkeypatch.setattr(ssh_cache, "_protect_password", lambda _: None)
    cache.put("default", "uhost-1", _host())
    assert not cache.path.exists()


def test_password_decryption_failure_is_a_cache_miss(monkeypatch, tmp_path) -> None:
    cache = SSHCredentialCache(tmp_path / "ssh-cache.json")
    cache.put("default", "uhost-1", _host(), now=100)
    monkeypatch.setattr(ssh_cache, "_unprotect_password", lambda _: None)
    assert cache.get("default", "uhost-1", now=150) is None
