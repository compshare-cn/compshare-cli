import json

import pytest
from typer.testing import CliRunner
from ucloud.core import exc as ucloud_exc

from compshare_cli import api, cli
from compshare_cli.commands import storage

runner = CliRunner()
LOCATION = ["--region", "cn-bj2", "--zone", "cn-bj2-03"]
BASE = {"Region": "cn-bj2", "Zone": "cn-bj2-03", "ProjectId": "org-test"}
CHANGES = [
    (
        ["create", "--name", "training", "--size", "100GiB", "--coupon", "coupon-1"],
        "GetCompShareCFSPrice",
        "CreateCFS",
        {"Size": 100, "ChargeType": "Month", "Quantity": 1},
        {
            "Size": 100,
            "ChargeType": "Month",
            "Quantity": 1,
            "Name": "training",
            "CouponId": "coupon-1",
        },
    ),
    (
        ["resize", "cfs-1", "--size", "200GiB", "--coupon", "coupon-1"],
        "GetCompShareCFSUpgradePrice",
        "ResizeCFS",
        {"CfsId": "cfs-1", "Size": 200},
        {"CfsId": "cfs-1", "Size": 200, "CouponId": "coupon-1"},
    ),
    (
        ["delete", "cfs-1", "--recycle"],
        "GetCompShareCFSRefundPrice",
        "DeleteCFS",
        {"CFSId": "cfs-1"},
        {"CfsId": "cfs-1", "Recycle": True},
    ),
]


@pytest.fixture
def gateway(monkeypatch):
    calls = []
    responses = {
        "DescribeCompShareSupportZone": {
            "ZoneInfo": [
                {"Region": "cn-bj2", "Zone": "cn-bj2-03", "IsPod": True},
                {"Region": "cn-sh2", "Zone": "cn-sh2-02", "IsPod": False},
            ]
        },
        "DescribeCFS": {
            "Found": False,
            "CFSSet": [
                {
                    "CfsId": "cfs-1",
                    "Size": 100,
                    "MountStatus": "Mounted",
                    "MountedUHostIds": ["cpod-1"],
                },
            ],
        },
        "GetCompShareCFSPrice": {"PriceDetails": [{"ChargeType": "Month", "Disks": 19.25}]},
        "GetCompShareCFSUpgradePrice": {"Price": 9.25},
        "GetCompShareCFSRefundPrice": {"RefundPrice": 5.75},
    }

    class FakeSDK:
        def __init__(self, *_args):
            pass

        def invoke(self, action, params):
            calls.append((action, dict(params)))
            response = responses.get(action, {"CfsId": "cfs-1"})
            if isinstance(response, Exception):
                raise response
            return {"RetCode": 0, **response}

    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "test-public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "test-private")
    monkeypatch.setattr(api, "CompShareSDK", FakeSDK)
    monkeypatch.setattr(storage, "locate_instance", lambda *_args: ("cn-bj2", "cn-bj2-03", {}))
    return calls, responses


@pytest.mark.parametrize(
    "args,action,params",
    [
        (["list"], "DescribeCFS", {"ProjectId": "org-test"}),
        (["show", "cfs-1"], "DescribeCFS", {"CfsId": "cfs-1", "ProjectId": "org-test"}),
        (["list", *LOCATION], "DescribeCFS", BASE),
        (
            ["price", "--size", "50GiB", "--charge", "Dynamic", "--quantity", "2", *LOCATION],
            "GetCompShareCFSPrice",
            {**BASE, "Size": 50, "ChargeType": "Dynamic", "Quantity": 2},
        ),
        (
            ["resize-price", "cfs-1", "--size", "2048GiB", *LOCATION],
            "GetCompShareCFSUpgradePrice",
            {**BASE, "CfsId": "cfs-1", "Size": 2048},
        ),
        (["refund", "cfs-1", *LOCATION], "GetCompShareCFSRefundPrice", {**BASE, "CFSId": "cfs-1"}),
    ],
)
def test_cfs_reads_use_documented_fields(gateway, args, action, params):
    calls, _ = gateway
    result = runner.invoke(cli.app, ["--json", "storage", "cfs", *args, "--project", "org-test"])

    assert result.exit_code == 0, result.output
    assert calls[-1] == (action, params)
    data = json.loads(result.stdout)["data"]
    if args[0] == "list":
        assert data["items"][0]["CfsId"] == "cfs-1"
        assert data["items"][0]["MountedUHostIds"] == ["cpod-1"]


@pytest.mark.parametrize("args,quote,action,quote_values,values", CHANGES)
@pytest.mark.parametrize("dry_run", [True, False])
def test_cfs_changes_quote_before_mutating(
    gateway, args, quote, action, quote_values, values, dry_run
):
    calls, _ = gateway
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "storage",
            "cfs",
            *args,
            *LOCATION,
            "--project",
            "org-test",
            "--dry-run" if dry_run else "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[1] == (quote, {**BASE, **quote_values})
    if dry_run:
        assert len(calls) == 2
        data = json.loads(result.stdout)["data"]
        assert data["dry_run"] is True
        assert data["request"] == {**BASE, **values}
    else:
        assert calls[2:] == [(action, {**BASE, **values})]


@pytest.mark.parametrize("args,quote,action,quote_values,values", CHANGES)
def test_cfs_changes_require_confirmation(gateway, args, quote, action, quote_values, values):
    calls, _ = gateway
    result = runner.invoke(cli.app, ["--json", "storage", "cfs", *args, *LOCATION])

    assert result.exit_code != 0
    assert [entry[0] for entry in calls] == ["DescribeCompShareSupportZone", quote]


@pytest.mark.parametrize(
    "args",
    [
        ["price", "--size", "49GiB"],
        ["price", "--size", "2049GiB"],
        ["price", "--size", "513MiB"],
        ["price", "--size", "100GiB", "--charge", "Postpay"],
        ["price", "--size", "100GiB", "--quantity", "0"],
        ["create", "--name", " ", "--size", "100GiB", "--yes"],
    ],
)
def test_invalid_cfs_options_do_not_reach_the_api(gateway, args):
    calls, _ = gateway
    result = runner.invoke(cli.app, ["--json", "storage", "cfs", *args, *LOCATION])

    assert result.exit_code != 0
    assert calls == []


def test_cfs_rejects_non_container_zones_before_quoting(gateway):
    calls, _ = gateway
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "storage",
            "cfs",
            "price",
            "--size",
            "100GiB",
            "--region",
            "cn-sh2",
            "--zone",
            "cn-sh2-02",
        ],
    )

    assert result.exit_code != 0
    assert [entry[0] for entry in calls] == ["DescribeCompShareSupportZone"]


def test_resize_quote_rejection_prevents_mutation(gateway):
    calls, responses = gateway
    responses["GetCompShareCFSUpgradePrice"] = ucloud_exc.RetCodeException(
        action="GetCompShareCFSUpgradePrice",
        code=1001,
        message="target must exceed current size",
    )
    result = runner.invoke(
        cli.app,
        ["--json", "storage", "cfs", "resize", "cfs-1", "--size", "100GiB", *LOCATION, "--yes"],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "api_error"
    assert [entry[0] for entry in calls] == [
        "DescribeCompShareSupportZone",
        "GetCompShareCFSUpgradePrice",
    ]


def test_missing_refund_is_not_reported_as_zero(gateway):
    _, responses = gateway
    responses["GetCompShareCFSRefundPrice"] = {}
    result = runner.invoke(cli.app, ["--json", "storage", "cfs", "refund", "cfs-1", *LOCATION])

    assert result.exit_code == 0, result.output
    assert "RefundPrice" not in json.loads(result.stdout)["data"]


@pytest.mark.parametrize(
    "group,command,action",
    [
        ("us3", "attach", "AttachUS3"),
        ("cfs", "attach", "AttachUS3"),
        ("cfs", "detach", "DetachCFS"),
    ],
)
def test_container_mount_changes_require_confirmation_and_support_preview(
    gateway, group, command, action
):
    calls, _ = gateway
    args = ["storage", group, command, "--instance", "cpod-1"]
    denied = runner.invoke(cli.app, ["--json", *args])
    assert denied.exit_code != 0
    assert calls == []

    preview = runner.invoke(cli.app, ["--json", *args, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    data = json.loads(preview.stdout)["data"]
    assert data["action"] == action
    assert data["request"] == {"Region": "cn-bj2", "Zone": "cn-bj2-03", "UHostId": "cpod-1"}
    assert calls == []
    if command == "attach":
        assert "50 GiB" in data["notice"]
        rejected = runner.invoke(cli.app, args, input="n\n")
        assert rejected.exit_code != 0
        assert "50 GiB" in rejected.output
        assert calls == []

    accepted = runner.invoke(cli.app, ["--json", *args, "--yes"])
    assert accepted.exit_code == 0, accepted.output
    assert calls == [(action, data["request"])]


@pytest.mark.parametrize("command", ["attach", "detach"])
def test_cfs_mount_commands_reject_regular_instances(gateway, command):
    calls, _ = gateway
    result = runner.invoke(
        cli.app,
        ["storage", "cfs", command, "--instance", "uhost-1", "--yes"],
    )
    assert result.exit_code != 0
    assert calls == []


def test_regular_us3_attachment_keeps_existing_behavior(gateway):
    calls, _ = gateway
    result = runner.invoke(cli.app, ["--json", "storage", "us3", "attach", "--instance", "uhost-1"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("AttachUS3", {"Region": "cn-bj2", "Zone": "cn-bj2-03", "UHostId": "uhost-1"}),
    ]
