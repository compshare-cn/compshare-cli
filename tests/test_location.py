from compshare_cli import location
from compshare_cli.runtime import Runtime


def test_region_is_derived_from_zone() -> None:
    assert location.region_from_zone("cn-sh2-02") == "cn-sh2"


def test_instance_location_searches_supported_regions(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        if action == "DescribeCompShareSupportZone":
            return {
                "ZoneInfo": [
                    {"Region": "cn-wlcb", "Zone": "cn-wlcb-01"},
                    {"Region": "cn-sh2", "Zone": "cn-sh2-02"},
                ]
            }
        if params["Region"] == "cn-sh2":
            return {"UHostSet": [{"UHostId": "uhost-1", "Zone": "cn-sh2-02"}]}
        return {"UHostSet": []}

    monkeypatch.setattr(location, "call", fake_call)
    region, zone, host = location.locate_instance(Runtime(), "uhost-1")

    assert (region, zone, host["UHostId"]) == ("cn-sh2", "cn-sh2-02", "uhost-1")
    assert [action for action, _ in calls] == [
        "DescribeCompShareInstance",
        "DescribeCompShareSupportZone",
        "DescribeCompShareInstance",
    ]
