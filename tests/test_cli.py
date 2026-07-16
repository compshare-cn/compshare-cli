import json

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from compshare_cli import cli
from compshare_cli.commands import instance
from compshare_cli.i18n import localize_command

runner = CliRunner()


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["instance", "--help"],
        ["image", "--help"],
        ["storage", "--help"],
        ["storage", "disk", "--help"],
    ],
)
def test_help_tree(args) -> None:
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_global_json_is_accepted_before_command(capsys) -> None:
    cli.main(["--json", "version"])
    assert json.loads(capsys.readouterr().out) == {"version": "0.1.3"}


def test_global_profile_is_accepted_before_command(capsys) -> None:
    cli.main(["--profile", "testing", "--json", "version"])
    assert json.loads(capsys.readouterr().out) == {"version": "0.1.3"}


def test_no_args_shows_help_without_error(capsys) -> None:
    cli.main([])
    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "Traceback" not in captured.err


def test_root_help_lists_config_first(capsys) -> None:
    cli.main(["-h"])
    help_text = capsys.readouterr().out
    assert help_text.index("config") < help_text.index("version")


def test_global_options_after_command_are_rejected(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["version", "--json"])
    assert raised.value.code == 2
    assert "No such option: --json" in json.loads(capsys.readouterr().out)["error"]


def test_config_error_is_json(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(tmp_path / "missing.json"))
    monkeypatch.delenv("COMPSHARE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("COMPSHARE_PRIVATE_KEY", raising=False)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "instance", "list"])
    assert raised.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "尚未配置" in payload["error"]


def test_credential_configuration_does_not_include_resource_scope() -> None:
    root_help = runner.invoke(cli.app, ["--help"])
    config_help = runner.invoke(cli.app, ["config", "--help"])
    schedule_help = runner.invoke(cli.app, ["instance", "schedule", "set", "--help"])

    assert "--project-id" not in root_help.stdout
    assert "config" in root_help.stdout
    assert "configure" not in root_help.stdout
    assert "--name" in config_help.stdout
    assert "--region" not in config_help.stdout
    assert "--zone" not in config_help.stdout
    assert "--project-id" not in config_help.stdout
    assert "--project-id" in schedule_help.stdout
    assert "--install-completion" not in root_help.stdout
    assert "--show-completion" not in root_help.stdout
    assert "--region" not in root_help.stdout
    assert "--zone" not in root_help.stdout
    assert root_help.stdout.index("--profile") < root_help.stdout.index("--json")


def test_config_profile_commands(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(path))

    saved = runner.invoke(
        cli.app,
        ["config", "set", "--name", "work", "--public-key", "pub", "--private-key", "sec"],
    )
    assert saved.exit_code == 0, saved.output

    listed = runner.invoke(cli.app, ["--json", "config", "list"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["profiles"] == [{"Profile": "work", "Active": True}]

    shown_path = runner.invoke(cli.app, ["config", "path"])
    assert shown_path.exit_code == 0
    assert shown_path.stdout.strip() == str(path)

    deleted = runner.invoke(cli.app, ["config", "delete", "work", "--yes"])
    assert deleted.exit_code == 0, deleted.output


def test_lang_command_persists_help_language(monkeypatch, tmp_path, capsys) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("COMPSHARE_LANG", raising=False)

    cli.main(["--help"])
    chinese = capsys.readouterr().out
    assert "在终端管理优云智算 GPU 计算资源" in chinese
    assert "管理 GPU 实例" in chinese
    assert "显示帮助并退出" in chinese
    assert "--install-completion" not in chinese
    assert "--lang" not in chinese

    cli.main(["lang", "en"])
    changed = capsys.readouterr().out
    assert "Default help language set to English" in changed
    assert json.loads(config_file.read_text(encoding="utf-8"))["language"] == "en"

    cli.main(["instance", "--help"])
    english = capsys.readouterr().out
    assert "Manage GPU instances" in english
    assert "Show this message and exit" in english

    cli.main(["lang", "zh"])
    assert "默认帮助语言已切换为中文" in capsys.readouterr().out
    cli.main(["--help"])
    assert "在终端管理优云智算 GPU 计算资源" in capsys.readouterr().out


def test_lang_command_shows_current_language_as_json(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.delenv("COMPSHARE_LANG", raising=False)
    cli.main(["--json", "lang", "en"])
    assert json.loads(capsys.readouterr().out) == {"ok": True, "language": "en"}

    cli.main(["--json", "lang"])
    assert json.loads(capsys.readouterr().out) == {"language": "en"}


def test_lang_is_not_a_global_option(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(tmp_path / "config.json"))
    with pytest.raises(SystemExit) as raised:
        cli.main(["--lang", "en"])
    assert raised.value.code == 2
    assert "No such option: --lang" in capsys.readouterr().err


def test_help_language_can_come_from_environment(monkeypatch, capsys) -> None:
    monkeypatch.setenv("COMPSHARE_LANG", "en")
    cli.main(["image", "--help"])
    assert "Manage instance images" in capsys.readouterr().out


def test_every_command_has_chinese_and_english_description() -> None:
    english = get_command(cli.app)
    chinese = localize_command(get_command(cli.app), "zh")

    def descriptions(command, prefix=()):
        result = []
        children = getattr(command, "commands", None)
        if children is not None:
            for name, child in children.items():
                path = (*prefix, name)
                result.append((path, child.help or child.short_help))
                result.extend(descriptions(child, path))
        return result

    english_descriptions = descriptions(english)
    chinese_descriptions = descriptions(chinese)
    assert len(english_descriptions) == len(chinese_descriptions)
    assert all(description for _, description in english_descriptions)
    assert all(description for _, description in chinese_descriptions)
    assert all(
        any("\u4e00" <= character <= "\u9fff" for character in description)
        for _, description in chinese_descriptions
    )


def test_search_checks_real_capacity_with_image(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        if action == "DescribeAvailableCompShareInstanceTypes":
            return {
                "RetCode": 0,
                "AvailableInstanceTypes": [
                    {
                        "Name": "4090",
                        "Zone": "cn-wlcb-01",
                        "GraphicsMemory": {"Value": 24},
                        "MachineSizes": [
                            {
                                "Gpu": 1,
                                "Collection": [
                                    {
                                        "Cpu": 16,
                                        "Memory": [64],
                                        "MinimalCpuPlatform": ["Auto"],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        assert action == "CheckCompShareResourceCapacity"
        return {
            "RetCode": 0,
            "Specs": [{"Gpu": 1, "Cpu": 16, "Mem": 64, "ResourceEnough": True}],
        }

    monkeypatch.setattr(instance, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "instance",
            "search",
            "--gpu",
            "4090",
            "--image",
            "image-1",
            "--available",
        ],
        env={
            "COMPSHARE_PUBLIC_KEY": "public",
            "COMPSHARE_PRIVATE_KEY": "private",
        },
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["Inventory"]["4090"][0]["ResourceEnough"] is True
    assert [action for action, _ in calls] == [
        "DescribeAvailableCompShareInstanceTypes",
        "CheckCompShareResourceCapacity",
    ]
    capacity = calls[1][1]
    assert capacity["CompShareImageId"] == "image-1"
    assert capacity["Disks"] == [{"IsBoot": True, "Type": "CLOUD_SSD", "Size": 100}]


def test_create_interactive_wizard_resolves_all_required_parameters(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        responses = {
            "DescribeCompShareSupportZone": {
                "ZoneInfo": [
                    {
                        "Region": "cn-wlcb",
                        "Zone": "cn-wlcb-01",
                        "Describe": "华北二A",
                    }
                ]
            },
            "DescribeAvailableCompShareInstanceTypes": {
                "AvailableInstanceTypes": [{"Name": "3080Ti", "GraphicsMemory": {"Value": 12}}]
            },
            "DescribeCompShareImages": {
                "ImageSet": [
                    {
                        "CompShareImageId": "image-1",
                        "Name": "Ubuntu 22.04",
                        "Status": "Available",
                    }
                ]
            },
            "CheckCompShareResourceCapacity": {
                "Specs": [{"Gpu": 1, "Cpu": 12, "Mem": 32, "ResourceEnough": True}]
            },
            "GetCompShareInstancePrice": {
                "PriceDetails": [{"ChargeType": "Postpay", "Instance": 0.7, "SystemDisks": 0}]
            },
            "CreateCompShareInstance": {"RetCode": 0, "UHostIds": ["uhost-test"]},
        }
        return responses[action]

    monkeypatch.setattr(instance, "call", fake_call)
    result = runner.invoke(
        cli.app,
        ["instance", "create", "--yes"],
        input="1\n1\n\n\n",
        env={
            "COMPSHARE_PUBLIC_KEY": "public",
            "COMPSHARE_PRIVATE_KEY": "private",
        },
    )

    assert result.exit_code == 0, result.output
    assert [action for action, _ in calls] == [
        "DescribeCompShareSupportZone",
        "DescribeAvailableCompShareInstanceTypes",
        "DescribeCompShareImages",
        "CheckCompShareResourceCapacity",
        "GetCompShareInstancePrice",
        "CreateCompShareInstance",
    ]
    created = calls[-1][1]
    assert created["GpuType"] == "3080Ti"
    assert created["GPU"] == 1
    assert created["CPU"] == 12
    assert created["Memory"] == 32 * 1024
    assert created["CompShareImageId"] == "image-1"
    assert created["ChargeType"] == "Postpay"
    assert created["Disks"] == [{"IsBoot": True, "Type": "CLOUD_SSD", "Size": 100}]


def test_create_json_requires_explicit_parameters(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "instance", "create"])
    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "--gpu" in payload["error"]


def test_create_explicit_json_mode_skips_discovery(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        if action == "CheckCompShareResourceCapacity":
            return {"Specs": [{"Gpu": 1, "Cpu": 12, "Mem": 32, "ResourceEnough": True}]}
        if action == "GetCompShareInstancePrice":
            return {"PriceDetails": [{"ChargeType": "Postpay", "Instance": 0.7}]}
        assert action == "CreateCompShareInstance"
        return {"RetCode": 0, "UHostIds": ["uhost-test"]}

    monkeypatch.setattr(instance, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "instance",
            "create",
            "--gpu",
            "3080Ti",
            "--count",
            "1",
            "--cpu",
            "12",
            "--memory",
            "32GiB",
            "--image",
            "image-1",
            "--yes",
        ],
        env={
            "COMPSHARE_PUBLIC_KEY": "public",
            "COMPSHARE_PRIVATE_KEY": "private",
        },
    )

    assert result.exit_code == 0, result.output
    assert [action for action, _ in calls] == [
        "CheckCompShareResourceCapacity",
        "GetCompShareInstancePrice",
        "CreateCompShareInstance",
    ]
    assert json.loads(result.stdout)["selection"]["ChargeType"] == "Postpay"


def test_create_dry_run_never_calls_create(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(action)
        if action == "CheckCompShareResourceCapacity":
            return {"Specs": [{"Gpu": 1, "Cpu": 12, "Mem": 32, "ResourceEnough": True}]}
        if action == "GetCompShareInstancePrice":
            return {"PriceDetails": [{"Instance": 0.7}]}
        raise AssertionError(action)

    monkeypatch.setattr(instance, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "instance",
            "create",
            "--gpu",
            "3080Ti",
            "--count",
            "1",
            "--cpu",
            "12",
            "--memory",
            "32GiB",
            "--image",
            "image-1",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["CheckCompShareResourceCapacity", "GetCompShareInstancePrice"]
    assert json.loads(result.stdout)["dry_run"] is True


def test_instance_wait_polls_until_running(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(action)
        if action == "StartCompShareInstance":
            return {"RetCode": 0}
        return {"UHostSet": [{"UHostId": "uhost-1", "State": "Running"}]}

    monkeypatch.setattr(instance, "call", fake_call)
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {"UHostId": value, "State": "Running", "Zone": "cn-wlcb-01"},
        ),
    )
    result = runner.invoke(
        cli.app,
        ["--json", "instance", "start", "uhost-1", "--wait"],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["StartCompShareInstance", "DescribeCompShareInstance"]
    assert json.loads(result.stdout)["final"]["UHostSet"][0]["State"] == "Running"


def test_schedule_auto_detects_project_id(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {"ProjectSet": [{"ProjectId": "org-default", "IsDefault": True}]}

    def fake_invoke(state, action, params, **kwargs):
        calls.append((action, params))
        return {"RetCode": 0}

    monkeypatch.setattr(instance, "call", fake_call)
    monkeypatch.setattr(instance, "invoke", fake_invoke)
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-bj2",
            "cn-bj2-03",
            {"UHostId": value, "Zone": "cn-bj2-03"},
        ),
    )
    result = runner.invoke(
        cli.app,
        ["instance", "schedule", "set", "uhost-1", "--at", "2h"],
    )

    assert result.exit_code == 0, result.output
    assert calls[0] == ("GetProjectList", {})
    assert calls[1][1]["ProjectId"] == "org-default"


def test_monitor_omits_production_rejected_zone(monkeypatch) -> None:
    calls = []

    def fake_invoke(state, action, params, **kwargs):
        calls.append((action, params))
        return {"RetCode": 0}

    monkeypatch.setattr(instance, "invoke", fake_invoke)
    result = runner.invoke(
        cli.app,
        ["instance", "monitor", "cpod-1", "--region", "cn-bj2"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("GetCompShareInstanceMonitor", {"Region": "cn-bj2", "UHostIds": ["cpod-1"]})]


def test_software_url_includes_required_zone(monkeypatch) -> None:
    calls = []

    def fake_invoke(state, action, params, **kwargs):
        calls.append((action, params))
        return {"RetCode": 0, "URL": "https://example.invalid"}

    monkeypatch.setattr(instance, "invoke", fake_invoke)
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-bj2",
            "cn-bj2-03",
            {"UHostId": value, "Zone": "cn-bj2-03"},
        ),
    )
    result = runner.invoke(
        cli.app,
        [
            "instance",
            "software",
            "url",
            "cpod-1",
            "JupyterLab",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "GetSoftwareURL",
            {
                "Region": "cn-bj2",
                "Zone": "cn-bj2-03",
                "UHostId": "cpod-1",
                "Software": "JupyterLab",
            },
        )
    ]


def test_ssh_print_includes_instance_password(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "Zone": "cn-wlcb-01",
                "SshLoginCommand": "ssh root@example.invalid",
                "Password": "instance-secret",
            },
        ),
    )
    result = runner.invoke(
        cli.app,
        ["--json", "instance", "ssh", "uhost-1", "--print"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "instance": "uhost-1",
        "command": "ssh root@example.invalid",
        "password": "instance-secret",
    }


def test_ssh_shows_password_before_connecting(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "Zone": "cn-wlcb-01",
                "SshLoginCommand": "ssh root@example.invalid",
                "Password": "instance-secret",
            },
        ),
    )
    commands = []
    monkeypatch.setattr(instance.subprocess, "call", lambda argv: commands.append(argv) or 0)

    result = runner.invoke(cli.app, ["instance", "ssh", "uhost-1"])

    assert result.exit_code == 0, result.output
    assert "Password: instance-secret" in result.stdout
    assert commands == [["ssh", "root@example.invalid"]]
