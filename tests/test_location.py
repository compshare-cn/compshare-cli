import pytest

from compshare_cli import location
from compshare_cli.errors import UsageError
from compshare_cli.runtime import Runtime


def test_instance_location_uses_region_and_zone_from_response(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {
            "UHostSet": [
                {
                    "UHostId": "uhost-1",
                    "Region": "cn-sh2",
                    "Zone": "cn-sh2-02",
                }
            ]
        }

    monkeypatch.setattr(location, "call", fake_call)
    region, zone, host = location.locate_instance(Runtime(), "uhost-1")

    assert (region, zone, host["UHostId"]) == ("cn-sh2", "cn-sh2-02", "uhost-1")
    assert calls == [
        (
            "DescribeCompShareInstance",
            {"UHostIds": ["uhost-1"], "Limit": 1, "Offset": 0},
        )
    ]


def test_instance_location_does_not_treat_requested_region_as_resolved(monkeypatch) -> None:
    def fake_call(state, action, params):
        assert params["Region"] == "cn-wlcb"
        return {
            "UHostSet": [
                {
                    "UHostId": "uhost-1",
                    "Region": "cn-sh2",
                    "Zone": "cn-sh2-02",
                }
            ]
        }

    monkeypatch.setattr(location, "call", fake_call)

    region, zone, _ = location.locate_instance(
        Runtime(),
        "uhost-1",
        request_region="cn-wlcb",
    )

    assert (region, zone) == ("cn-sh2", "cn-sh2-02")


@pytest.mark.parametrize(
    "host",
    [
        {"UHostId": "uhost-1", "Zone": "cn-sh2-02"},
        {"UHostId": "uhost-1", "Region": "cn-sh2"},
    ],
)
def test_instance_location_rejects_incomplete_response(monkeypatch, host) -> None:
    monkeypatch.setattr(location, "call", lambda *args, **kwargs: {"UHostSet": [host]})

    with pytest.raises(UsageError, match="Region.*Zone"):
        location.locate_instance(Runtime(), "uhost-1")


def test_supported_locations_does_not_inject_region(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {"ZoneInfo": [{"Region": "cn-sh2", "Zone": "cn-sh2-02"}]}

    monkeypatch.setattr(location, "call", fake_call)

    assert location.supported_locations(Runtime()) == [{"Region": "cn-sh2", "Zone": "cn-sh2-02"}]
    assert calls == [("DescribeCompShareSupportZone", {})]


def test_supported_locations_passes_only_an_explicit_request_region(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {"ZoneInfo": []}

    monkeypatch.setattr(location, "call", fake_call)

    location.supported_locations(Runtime(), request_region="cn-sh2")

    assert calls == [("DescribeCompShareSupportZone", {"Region": "cn-sh2"})]


def test_supported_locations_accepts_null_list(monkeypatch) -> None:
    monkeypatch.setattr(location, "call", lambda *args, **kwargs: {"ZoneInfo": None})

    assert location.supported_locations(Runtime()) == []


def test_locate_disk_uses_disk_inventory_for_attached_disk(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        if action == "DescribeCompshareDisk":
            return {
                "DiskSet": [
                    {
                        "ResourceId": "udisk-1",
                        "Zone": "cn-sh2-02",
                        "MountInstance": "uhost-1",
                    }
                ]
            }
        return {"ZoneInfo": [{"Region": "cn-sh2", "Zone": "cn-sh2-02"}]}

    monkeypatch.setattr(location, "call", fake_call)

    region, zone, host, disk = location.locate_disk(Runtime(), "udisk-1")

    assert (region, zone) == ("cn-sh2", "cn-sh2-02")
    assert host == {"UHostId": "uhost-1", "Region": "cn-sh2", "Zone": "cn-sh2-02"}
    assert disk["ResourceId"] == "udisk-1"
    assert calls == [
        ("DescribeCompshareDisk", {}),
        ("DescribeCompShareSupportZone", {}),
    ]


def test_locate_disk_supports_detached_disk(monkeypatch) -> None:
    def fake_call(state, action, params):
        if action == "DescribeCompshareDisk":
            return {
                "DiskSet": [{"ResourceId": "udisk-1", "Zone": "cn-sh2-02", "MountInstance": ""}]
            }
        return {"ZoneInfo": [{"Region": "cn-sh2", "Zone": "cn-sh2-02"}]}

    monkeypatch.setattr(location, "call", fake_call)

    _, _, host, _ = location.locate_disk(Runtime(), "udisk-1")

    assert host is None
