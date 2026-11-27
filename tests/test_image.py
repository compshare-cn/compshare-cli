import json

from typer.testing import CliRunner

from compshare_cli import cli
from compshare_cli.commands import image


def test_image_create_waits_for_documented_process(monkeypatch):
    region, zone = "cn-wlcb", "cn-wlcb-01"
    location = {"Region": region, "Zone": zone}
    created = {"CompShareImageId": "compshareImage-test"}
    final = {"Process": 100.0, "RemainingDuration": 0, "TotalDuration": 30}
    progress = iter([{"Process": 0.0}, {"Process": 65.5}, final])
    calls = []

    def fake_call(_state, action, params):
        calls.append((action, params))
        return created if action == "CreateCompShareCustomImage" else next(progress)

    monkeypatch.setattr(image, "call", fake_call)
    monkeypatch.setattr(image, "locate_instance", lambda *_: (region, zone, {}))
    monkeypatch.setattr(image.time, "sleep", lambda _: None)
    result = CliRunner().invoke(
        cli.app,
        [
            "--json",
            "image",
            "create",
            "--instance",
            "uhost-test",
            "--name",
            "training",
            "--wait",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"] == {"operation": created, "final": final}
    assert calls == [
        ("CreateCompShareCustomImage", {**location, "UHostId": "uhost-test", "Name": "training"}),
        *[("GetCompShareImageCreateProgress", {**location, **created})] * 3,
    ]


def test_image_list_favorites_uses_community_filter(monkeypatch):
    calls = []

    def fake_collect(_state, action, params, key, **pagination):
        calls.append((action, params, key, pagination))
        return {key: []}

    monkeypatch.setattr(image, "collect_pages", fake_collect)
    result = CliRunner().invoke(
        cli.app, ["--json", "image", "list", "--source", "community", "--favorite"]
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "DescribeCommunityImages",
            {"IfFavorite": True},
            "CompshareImageGroup",
            {"offset": 0, "limit": 20},
        )
    ]
