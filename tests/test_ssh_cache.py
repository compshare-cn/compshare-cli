import json
import stat

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
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "Unrelated" not in next(iter(saved["entries"].values()))["host"]


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
