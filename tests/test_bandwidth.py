import json

import pytest
from typer.testing import CliRunner

from compshare_cli import cli
from compshare_cli.commands import bandwidth

runner = CliRunner()


def _document(output: str) -> dict:
    payload = json.loads(output)
    assert payload["schema_version"] == "1"
    return payload


@pytest.fixture(autouse=True)
def credentials(monkeypatch) -> None:
    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "test-public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "test-private")


def test_list_queries_supported_ucloud_zones(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        bandwidth,
        "supported_locations",
        lambda state, request_region=None: [
            {"Region": "cn-wlcb", "Zone": "cn-wlcb-01", "IsPod": False},
            {"Region": "cn-sh2", "Zone": "cn-sh2-02", "IsPod": False},
            {"Region": "cn-sh2", "Zone": "cn-sh2-01", "IsPod": True},
        ],
    )

    def fake_call(state, action, params):
        calls.append((action, params))
        if params["Zone"] == "cn-sh2-02":
            return {"RetCode": 0}
        return {
            "RetCode": 0,
            "CompanyShareBandwidth": {
                "ShareBandwidthId": "bw-1",
                "Bandwidth": 100,
                "Status": "Available",
                "BindEIPCount": 2,
            },
        }

    monkeypatch.setattr(bandwidth, "call", fake_call)
    result = runner.invoke(cli.app, ["--json", "bandwidth", "list"])

    assert result.exit_code == 0, result.output
    payload = _document(result.stdout)
    assert payload["data"]["items"] == [
        {
            "ShareBandwidthId": "bw-1",
            "ResourceId": None,
            "Region": "cn-wlcb",
            "Zone": "cn-wlcb-01",
            "Bandwidth": 100,
            "Status": "Available",
            "ChargeType": None,
            "Quantity": None,
            "PurchaseValue": None,
            "BindEIPCount": 2,
            "BindEIPInfo": None,
            "CreateTime": None,
            "UpdateTime": None,
        }
    ]
    assert calls == [
        (
            "DescribeCompShareShareBandwidth",
            {"Region": "cn-wlcb", "Zone": "cn-wlcb-01"},
        ),
        (
            "DescribeCompShareShareBandwidth",
            {"Region": "cn-sh2", "Zone": "cn-sh2-02"},
        ),
    ]


def test_instances_requests_bandwidth_assignments(monkeypatch) -> None:
    captured = {}

    def fake_pages(state, action, params, list_key):
        captured.update(action=action, params=params, list_key=list_key)
        return {
            "UHostSet": [
                {
                    "UHostId": "uhost-1",
                    "Name": "trainer",
                    "Region": "cn-wlcb",
                    "Zone": "cn-wlcb-01",
                    "IPSet": [
                        {
                            "Type": "Internet",
                            "IPId": "eip-1",
                            "IP": "203.0.113.10",
                            "ShareBandwidth": {
                                "Scope": "Company",
                                "ShareBandwidthId": "bw-1",
                                "Bandwidth": 100,
                                "CanSwitch": True,
                            },
                        },
                        {"Type": "Private", "IPId": "private-1", "IP": "10.0.0.1"},
                    ],
                }
            ]
        }

    monkeypatch.setattr(bandwidth, "collect_pages", fake_pages)
    result = runner.invoke(cli.app, ["--json", "bandwidth", "instances"])

    assert result.exit_code == 0, result.output
    item = _document(result.stdout)["data"]["items"][0]
    assert item == {
        "UHostId": "uhost-1",
        "Name": "trainer",
        "Zone": "cn-wlcb-01",
        "IP": "***",
        "EIPId": "eip-1",
        "Scope": "Company",
        "Bandwidth": 100,
        "CanSwitch": True,
        "Region": "cn-wlcb",
        "ShareBandwidthId": "bw-1",
        "TargetScope": None,
    }
    assert captured == {
        "action": "DescribeCompShareInstance",
        "params": {
            "SkipBill": True,
            "IncludeShareBandwidth": True,
        },
        "list_key": "UHostSet",
    }


def test_create_dry_run_quotes_without_purchasing(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {"RetCode": 0, "TotalPrice": 133000}

    monkeypatch.setattr(bandwidth, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "bandwidth",
            "create",
            "--bandwidth",
            "100",
            "--region",
            "cn-wlcb",
            "--zone",
            "cn-wlcb-01",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    data = _document(result.stdout)["data"]
    assert data["dry_run"] is True
    assert data["request"] == {
        "Region": "cn-wlcb",
        "Zone": "cn-wlcb-01",
        "ShareBandwidth": 100,
        "ChargeType": "Month",
        "Quantity": 1,
    }
    assert [action for action, _ in calls] == ["GetCompShareShareBandwidthPrice"]


@pytest.mark.parametrize(
    ("command", "quote_action"),
    [
        ("resize", "GetCompShareShareBandwidthUpgradePrice"),
        ("delete", "GetCompShareShareBandwidthRefundPrice"),
    ],
)
def test_change_dry_runs_only_quote(monkeypatch, command, quote_action) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(action)
        return {"RetCode": 0, "TotalPrice": -1000, "RefundPrice": -1000}

    monkeypatch.setattr(bandwidth, "call", fake_call)
    args = [
        "--json",
        "bandwidth",
        command,
        "bw-1",
        "--region",
        "cn-wlcb",
        "--zone",
        "cn-wlcb-01",
        "--dry-run",
    ]
    if command == "resize":
        args.extend(["--bandwidth", "200"])

    result = runner.invoke(cli.app, args)

    assert result.exit_code == 0, result.output
    assert calls == [quote_action]


def test_switch_groups_instances_by_zone_and_reports_missing(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        bandwidth,
        "locate_instances",
        lambda state, instances: (
            {
                "uhost-1": ("cn-wlcb", "cn-wlcb-01", {}),
                "uhost-2": ("cn-sh2", "cn-sh2-02", {}),
            },
            ["uhost-missing"],
        ),
    )

    def fake_captured(state, action, params):
        calls.append((action, params))
        instance = params["UHostIds"][0]
        return {"Results": [{"UHostId": instance, "Success": True}]}, None

    monkeypatch.setattr(bandwidth, "call_captured", fake_captured)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "bandwidth",
            "switch",
            "uhost-1",
            "uhost-2",
            "uhost-missing",
            "--to",
            "dedicated",
            "--yes",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = _document(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "partial_failure"
    assert len(payload["error"]["details"]["Results"]) == 3
    assert calls == [
        (
            "SwitchCompShareEIPShareBandwidth",
            {
                "Region": "cn-wlcb",
                "Zone": "cn-wlcb-01",
                "UHostIds": ["uhost-1"],
                "TargetScope": "Company",
            },
        ),
        (
            "SwitchCompShareEIPShareBandwidth",
            {
                "Region": "cn-sh2",
                "Zone": "cn-sh2-02",
                "UHostIds": ["uhost-2"],
                "TargetScope": "Company",
            },
        ),
    ]
