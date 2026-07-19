import json

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from compshare_cli import __version__, cli
from compshare_cli.commands import doctor as doctor_module
from compshare_cli.commands import image as image_module
from compshare_cli.commands import instance, storage, team
from compshare_cli.config import ConfigStore, Profile
from compshare_cli.i18n import localize_command
from compshare_cli.ssh import RemoteExecutionResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolate_ssh_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPSHARE_SSH_CACHE_FILE", str(tmp_path / "ssh-cache.json"))
    monkeypatch.setenv("COMPSHARE_TEMPLATE_FILE", str(tmp_path / "instance-templates.json"))
    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "test-public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "test-private")


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["instance", "--help"],
        ["instance", "template", "--help"],
        ["image", "--help"],
        ["storage", "--help"],
        ["storage", "disk", "--help"],
        ["team", "--help"],
        ["team", "invite", "--help"],
        ["team", "billing", "--help"],
    ],
)
def test_help_tree(args) -> None:
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_global_json_is_accepted_before_command(capsys) -> None:
    cli.main(["--json", "version"])
    assert json.loads(capsys.readouterr().out) == {"version": __version__}


def test_version_flag(capsys) -> None:
    cli.main(["--version"])

    assert capsys.readouterr().out.strip() == __version__


def test_global_profile_is_accepted_before_command(capsys) -> None:
    cli.main(["--profile", "testing", "--json", "version"])
    assert json.loads(capsys.readouterr().out) == {"version": __version__}


def test_no_args_shows_help_without_error(capsys) -> None:
    cli.main([])
    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "Traceback" not in captured.err


def test_root_help_lists_config_first(capsys) -> None:
    cli.main(["-h"])
    help_text = capsys.readouterr().out
    assert "--version" in help_text
    assert "--lang" in help_text
    assert "│ lang " not in help_text
    assert help_text.index("config") < help_text.index("feedback") < help_text.index("doctor")


def test_shell_completion_is_available(monkeypatch) -> None:
    monkeypatch.setattr("typer.completion._get_shell_name", lambda: "zsh")

    shown = runner.invoke(cli.app, ["--show-completion"], prog_name="compshare")
    assert shown.exit_code == 0, shown.output
    assert "#compdef compshare" in shown.stdout
    assert "_COMPSHARE_COMPLETE=complete_zsh" in shown.stdout

    completed = runner.invoke(
        cli.app,
        [],
        prog_name="compshare",
        env={
            "_COMPSHARE_COMPLETE": "complete_zsh",
            "_TYPER_COMPLETE_ARGS": "compshare instance sh",
        },
    )
    assert completed.exit_code == 0, completed.output
    assert '"show"' in completed.stdout


def test_global_options_after_command_are_rejected(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["version", "--json"])
    assert raised.value.code == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert "No such option: --json" in error
    assert "compshare --json instance list" in error


def test_json_config_does_not_prompt_for_credentials(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "config"])

    assert raised.value.code == 2
    output = capsys.readouterr().out
    assert "公钥:" not in output
    assert "--public-key" in json.loads(output)["error"]


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
    assert "--install-completion" in root_help.stdout
    assert "--show-completion" in root_help.stdout
    assert "--region" not in root_help.stdout
    assert "--zone" not in root_help.stdout
    assert "--show-sensitive" in root_help.stdout
    assert "--show-sensitive" not in config_help.stdout
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


def test_confirmation_retries_empty_and_invalid_answers(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(path))
    ConfigStore().save_profile("work", Profile("pub", "private"))

    result = runner.invoke(
        cli.app,
        ["config", "delete", "work"],
        input="\ninvalid\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.count("[y/N]") == 3
    assert result.stdout.count("请输入 y 或 n") == 2
    assert "work" not in ConfigStore().list_profiles()


def test_json_confirmation_requires_yes_without_prompt(monkeypatch, tmp_path, capsys) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(path))
    ConfigStore().save_profile("work", Profile("pub", "private"))

    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "config", "delete", "work"])

    assert raised.value.code == 2
    output = capsys.readouterr().out
    assert "[y/N]" not in output
    assert "--yes" in json.loads(output)["error"]
    assert "work" in ConfigStore().list_profiles()


def test_lang_option_persists_help_language(monkeypatch, tmp_path, capsys) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("COMPSHARE_LANG", raising=False)

    cli.main(["--help"])
    chinese = capsys.readouterr().out
    assert "在终端管理优云智算 GPU 计算资源" in chinese
    assert "管理 GPU 实例" in chinese
    assert "显示帮助并退出" in chinese
    assert "--install-completion" in chinese
    assert "为当前 Shell 安装命令补全" in chinese
    assert "--lang" in chinese

    cli.main(["--lang", "en", "--help"])
    changed = capsys.readouterr().out
    assert "Manage CompShare GPU compute from the terminal" in changed
    assert json.loads(config_file.read_text(encoding="utf-8"))["language"] == "en"

    cli.main(["instance", "--help"])
    english = capsys.readouterr().out
    assert "Manage GPU instances" in english
    assert "Show this message and exit" in english

    cli.main(["--lang=zh", "--help"])
    assert "在终端管理优云智算 GPU 计算资源" in capsys.readouterr().out
    cli.main(["--help"])
    assert "在终端管理优云智算 GPU 计算资源" in capsys.readouterr().out


def test_lang_option_applies_to_command_and_json_output(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.delenv("COMPSHARE_LANG", raising=False)
    cli.main(["--lang", "en", "--json", "version"])
    assert json.loads(capsys.readouterr().out) == {"version": __version__}
    assert ConfigStore().load_language() == "en"


def test_help_language_can_come_from_environment(monkeypatch, capsys) -> None:
    monkeypatch.setenv("COMPSHARE_LANG", "en")
    cli.main(["image", "--help"])
    assert "Manage instance images" in capsys.readouterr().out


def test_image_list_does_not_require_location(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key, **kwargs):
        calls.append((action, params, list_key))
        return {"ImageSet": []}

    monkeypatch.setattr(image_module, "collect_pages", fake_pages)
    result = runner.invoke(cli.app, ["--json", "image", "list", "--source", "custom"])

    assert result.exit_code == 0, result.output
    assert calls == [("DescribeCompShareCustomImages", {}, "ImageSet")]


def test_custom_image_list_passes_explicit_region_and_zone(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key, **kwargs):
        calls.append((action, params, list_key))
        return {"ImageSet": []}

    monkeypatch.setattr(image_module, "collect_pages", fake_pages)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "image",
            "list",
            "--source",
            "custom",
            "--region",
            "cn-sh2",
            "--zone",
            "cn-sh2-02",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "DescribeCompShareCustomImages",
            {"Region": "cn-sh2", "Zone": "cn-sh2-02"},
            "ImageSet",
        )
    ]


def test_storage_disk_list_uses_disk_inventory_and_resource_id(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {
            "TotalCount": 1,
            "DiskSet": [
                {
                    "ResourceId": "udisk-abcdefghijklmnop",
                    "Name": "data",
                    "Configuration": "100GB",
                    "DiskType": "CLOUD_SSD",
                    "Zone": "cn-sh2-02",
                    "MountInstance": "uhost-1",
                }
            ],
        }

    monkeypatch.setattr(storage, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "storage",
            "disk",
            "list",
            "--instance",
            "uhost-1",
            "--region",
            "cn-sh2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        ("DescribeCompshareDisk", {"HostId": "uhost-1", "Region": "cn-sh2"})
    ]
    assert "udisk-abcdefghijklmnop" in result.stdout


def test_favorite_uses_image_group_api(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        image_module,
        "invoke",
        lambda state, action, params, **kwargs: calls.append((action, params)),
    )

    result = runner.invoke(cli.app, ["image", "favorite", "group-1"])

    assert result.exit_code == 0, result.output
    assert calls == [("CreateCompShareImageFavorite", {"GroupId": "group-1"})]


def test_unfavorite_uses_image_group_api(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        image_module,
        "invoke",
        lambda state, action, params, **kwargs: calls.append((action, params)),
    )

    result = runner.invoke(cli.app, ["image", "unfavorite", "group-1"])

    assert result.exit_code == 0, result.output
    assert calls == [("DeleteCompShareImageFavorite", {"GroupId": "group-1"})]


def test_platform_image_list_applies_global_limit_across_types(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key, **kwargs):
        image_type = params["ImageType"]
        calls.append(image_type)
        available = [
            {"CompShareImageId": f"{image_type}-{index}", "ImageType": image_type}
            for index in range(2)
        ]
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit")
        selected = available[offset:] if limit is None else available[offset : offset + limit]
        return {
            "ImageSet": selected,
            "TotalCount": 2,
        }

    monkeypatch.setattr(image_module, "collect_pages", fake_pages)
    result = runner.invoke(
        cli.app,
        ["--json", "image", "list", "--source", "platform", "--offset", "1", "--limit", "3"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert calls == ["System", "App", "Game", "Other"]
    assert payload["TotalCount"] == 8
    assert payload["ReturnedCount"] == 3
    assert [item["CompShareImageId"] for item in payload["ImageSet"]] == [
        "System-1",
        "App-0",
        "App-1",
    ]


def test_user_image_source_requires_user_id() -> None:
    result = runner.invoke(cli.app, ["--json", "image", "list", "--source", "user"])

    assert result.exit_code != 0
    assert "--user" in str(result.exception)


def test_read_only_instance_metadata_commands_relax_location(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        instance,
        "invoke",
        lambda state, action, params, **kwargs: calls.append((action, params)),
    )

    assert runner.invoke(cli.app, ["instance", "network"]).exit_code == 0
    assert runner.invoke(cli.app, ["instance", "software", "list"]).exit_code == 0
    assert runner.invoke(cli.app, ["instance", "ports", "list"]).exit_code == 0
    assert runner.invoke(cli.app, ["instance", "models", "--region", "cn-sh2"]).exit_code == 0

    assert calls == [
        ("CheckCompShareNetOptimizer", {}),
        ("DescribeCompShareSoftwarePort", {}),
        ("DescribeCompShareSoftwarePort", {}),
        ("DescribeModelRepositoryModels", {"Region": "cn-sh2"}),
    ]


@pytest.mark.parametrize(
    ("args", "action"),
    [
        (
            ["image", "progress", "image-1", "--region", "cn-sh2"],
            "GetCompShareImageCreateProgress",
        ),
        (
            ["image", "update", "image-1", "--name", "new", "--region", "cn-sh2"],
            "UpdateCompShareImage",
        ),
        (
            ["image", "delete", "image-1", "--region", "cn-sh2", "--yes"],
            "TerminateCompShareCustomImage",
        ),
    ],
)
def test_image_mutation_metadata_commands_do_not_require_zone(monkeypatch, args, action) -> None:
    calls = []
    monkeypatch.setattr(
        image_module,
        "invoke",
        lambda state, current_action, params, **kwargs: calls.append((current_action, params)),
    )

    result = runner.invoke(cli.app, args)

    assert result.exit_code == 0, result.output
    assert calls[0][0] == action
    assert calls[0][1]["Region"] == "cn-sh2"
    assert "Zone" not in calls[0][1]


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
            "--region",
            "cn-wlcb",
            "--zone",
            "cn-wlcb-01",
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
    monkeypatch.setattr(
        instance,
        "supported_locations",
        lambda state, request_region=None: fake_call(
            state,
            "DescribeCompShareSupportZone",
            {"Region": request_region} if request_region is not None else {},
        )["ZoneInfo"],
    )
    monkeypatch.setattr(
        instance,
        "collect_pages",
        lambda state, action, params, list_key: fake_call(state, action, params),
    )
    result = runner.invoke(
        cli.app,
        ["instance", "create", "--yes", "--no-wait"],
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


def test_create_image_fetches_all_api_pages(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key):
        calls.append((action, params, list_key))
        return {
            "ImageSet": [
                {"CompShareImageId": f"image-{index}", "Status": "Available"}
                for index in range(1, 121)
            ]
        }

    monkeypatch.setattr(instance, "collect_pages", fake_pages)
    images = instance._create_images(instance.Runtime(), "cn-wlcb", "cn-wlcb-01", "platform")

    assert len(images) == 120
    assert calls == [
        (
            "DescribeCompShareImages",
            {"Region": "cn-wlcb", "Zone": "cn-wlcb-01"},
            "ImageSet",
        )
    ]


def test_create_image_selection_paginates(monkeypatch, capsys) -> None:
    images = [
        {"CompShareImageId": f"image-{index}", "Name": f"Image {index}"} for index in range(1, 46)
    ]
    answers = iter(["", "f", "f", "5"])
    monkeypatch.setenv("COMPSHARE_LANG", "en")
    monkeypatch.setattr(instance, "_create_images", lambda *args: images)
    monkeypatch.setattr(instance.typer, "prompt", lambda *args, **kwargs: next(answers))

    selected = instance._create_image(instance.Runtime(), "cn-wlcb", "cn-wlcb-01", None, None)

    assert selected == "image-45"
    output = capsys.readouterr().out
    assert "Page 1 of 3 (45 items)" in output
    assert "Page 2 of 3 (45 items)" in output
    assert "Page 3 of 3 (45 items)" in output


def test_create_json_requires_explicit_parameters(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "instance", "create"])
    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "--gpu" in payload["error"]


def test_local_instance_template_crud() -> None:
    created = runner.invoke(
        cli.app,
        [
            "--json",
            "instance",
            "template",
            "create",
            "训练配置",
            "--description",
            "4090 training",
            "--gpu",
            "4090",
            "--count",
            "1",
            "--cpu",
            "16",
            "--memory",
            "64GiB",
            "--image",
            "image-1",
            "--region",
            "cn-sh2",
            "--zone",
            "cn-sh2-02",
            "--disk",
            "100GiB",
            "--us3",
        ],
    )
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)["parameters"]["gpu"] == "4090"

    listed = runner.invoke(cli.app, ["--json", "instance", "template", "list"])
    shown = runner.invoke(
        cli.app,
        ["--json", "instance", "template", "show", "训练配置"],
    )
    assert listed.exit_code == 0, listed.output
    assert shown.exit_code == 0, shown.output
    assert [item["name"] for item in json.loads(listed.stdout)["templates"]] == ["训练配置"]
    assert json.loads(shown.stdout)["description"] == "4090 training"

    deleted = runner.invoke(
        cli.app,
        ["--json", "instance", "template", "delete", "训练配置", "--yes"],
    )
    assert deleted.exit_code == 0, deleted.output
    assert json.loads(deleted.stdout) == {"ok": True, "name": "训练配置"}


def test_instance_create_loads_template_and_explicit_options_override(monkeypatch) -> None:
    saved = runner.invoke(
        cli.app,
        [
            "instance",
            "template",
            "create",
            "training",
            "--gpu",
            "4090",
            "--count",
            "1",
            "--cpu",
            "12",
            "--memory",
            "32GiB",
            "--image",
            "image-1",
            "--region",
            "cn-wlcb",
            "--zone",
            "cn-wlcb-01",
            "--disk",
            "100GiB",
            "--charge",
            "Postpay",
            "--max-count",
            "2",
            "--us3",
        ],
    )
    assert saved.exit_code == 0, saved.output

    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        if action == "CheckCompShareResourceCapacity":
            return {"Specs": [{"Gpu": 1, "Cpu": 16, "Mem": 32, "ResourceEnough": True}]}
        if action == "GetCompShareInstancePrice":
            return {"PriceDetails": [{"ChargeType": "Postpay", "Instance": 0.7}]}
        raise AssertionError(action)

    monkeypatch.setattr(instance, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "instance",
            "create",
            "--template",
            "training",
            "--cpu",
            "16",
            "--no-us3",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["template"] == "training"
    assert payload["request"]["GpuType"] == "4090"
    assert payload["request"]["CPU"] == 16
    assert payload["request"]["MaxCount"] == 2
    assert "EnableUS3" not in payload["request"]
    assert [action for action, _ in calls] == [
        "CheckCompShareResourceCapacity",
        "GetCompShareInstancePrice",
    ]


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
    waits = []
    monkeypatch.setattr(
        instance,
        "_wait_for_instance",
        lambda state, value, **kwargs: (
            waits.append((value, kwargs)) or {"UHostSet": [{"UHostId": value, "State": "Running"}]}
        ),
    )
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
            "--region",
            "cn-wlcb",
            "--zone",
            "cn-wlcb-01",
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
    assert waits == [("uhost-test", {"region": "cn-wlcb", "desired": {"Running"}, "timeout": 600})]


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
            "--region",
            "cn-wlcb",
            "--zone",
            "cn-wlcb-01",
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
            return {"RetCode": 0}, None
        return {"UHostSet": [{"UHostId": "uhost-1", "State": "Running"}]}, None

    monkeypatch.setattr(instance, "call_captured", fake_call)
    monkeypatch.setattr(
        instance,
        "_locate_instances",
        lambda state, values: (
            {
                "uhost-1": (
                    "cn-wlcb",
                    "cn-wlcb-01",
                    {
                        "UHostId": "uhost-1",
                        "Region": "cn-wlcb",
                        "Zone": "cn-wlcb-01",
                    },
                )
            },
            [],
        ),
    )
    result = runner.invoke(
        cli.app,
        ["--json", "instance", "start", "uhost-1", "--wait"],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["StartCompShareInstance", "DescribeCompShareInstance"]
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["succeeded"][0]["final"]["UHostSet"][0]["State"] == "Running"


def test_stop_uses_region_and_zone_reported_by_describe(monkeypatch) -> None:
    submitted = []

    def fake_pages(state, action, params, list_key):
        assert action == "DescribeCompShareInstance"
        assert params == {"UHostIds": ["uhost-1"]}
        return {
            "UHostSet": [
                {
                    "UHostId": "uhost-1",
                    "Region": "cn-sh2",
                    "Zone": "cn-sh2-02",
                }
            ]
        }

    monkeypatch.setattr(instance, "collect_pages", fake_pages)

    def fake_call_captured(state, action, params):
        submitted.append((action, params))
        return {"RetCode": 0}, None

    monkeypatch.setattr(instance, "call_captured", fake_call_captured)

    result = runner.invoke(
        cli.app,
        ["--json", "instance", "stop", "uhost-1", "--yes", "--no-wait"],
    )

    assert result.exit_code == 0, result.output
    assert submitted == [
        (
            "StopCompShareInstance",
            {"Region": "cn-sh2", "Zone": "cn-sh2-02", "UHostId": "uhost-1"},
        )
    ]


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


def test_unavailable_instance_commands_are_not_exposed() -> None:
    instance_help = runner.invoke(cli.app, ["instance", "--help"])
    software_help = runner.invoke(cli.app, ["instance", "software", "--help"])
    show_help = runner.invoke(cli.app, ["instance", "show", "--help"])

    assert instance_help.exit_code == 0, instance_help.output
    assert software_help.exit_code == 0, software_help.output
    assert show_help.exit_code == 0, show_help.output
    assert "monitor" not in instance_help.stdout
    assert "url" not in software_help.stdout
    for option in (
        "--ip",
        "--softwares",
        "--spec",
        "--disks",
        "--billing",
        "--image",
        "--status",
    ):
        assert option in show_help.stdout
    assert "--connection" not in show_help.stdout


def test_instance_show_json_redacts_private_fields_unless_enabled(monkeypatch) -> None:
    host = {
        "UHostId": "uhost-1",
        "Region": "cn-sh2",
        "Zone": "cn-sh2-02",
        "Password": "instance-secret",
        "FileBrowserPassword": "browser-secret",
        "SshLoginCommand": "ssh root@203.0.113.10",
        "IPSet": [{"IP": "203.0.113.10", "IPId": "ip-resource-id"}],
        "Softwares": [{"Name": "JupyterLab", "URL": "https://example.invalid/token"}],
    }
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: ("cn-sh2", "cn-sh2-02", host),
    )

    safe_result = runner.invoke(cli.app, ["--json", "instance", "show", "uhost-1"])
    private_result = runner.invoke(
        cli.app,
        ["--json", "--show-sensitive", "instance", "show", "uhost-1"],
    )

    assert safe_result.exit_code == 0, safe_result.output
    safe_host = json.loads(safe_result.stdout)["UHostSet"][0]
    assert safe_host["Password"] == "***"
    assert safe_host["FileBrowserPassword"] == "***"
    assert safe_host["SshLoginCommand"] == "***"
    assert safe_host["IPSet"] == [{"IP": "***", "IPId": "ip-resource-id"}]
    assert safe_host["Softwares"] == [{"Name": "JupyterLab", "URL": "***"}]

    assert private_result.exit_code == 0, private_result.output
    assert json.loads(private_result.stdout)["UHostSet"][0] == host

    safe_human = runner.invoke(cli.app, ["instance", "show", "uhost-1"])
    private_human = runner.invoke(
        cli.app,
        ["--show-sensitive", "instance", "show", "uhost-1"],
    )
    assert safe_human.exit_code == 0, safe_human.output
    assert "JupyterLab" in safe_human.stdout
    assert "https://example.invalid/token" not in safe_human.stdout
    assert "***" in safe_human.stdout
    assert private_human.exit_code == 0, private_human.output
    assert "https://example.invalid/token" in private_human.stdout


def test_instance_show_focus_flags_return_only_selected_groups(monkeypatch) -> None:
    host = {
        "UHostId": "uhost-1",
        "Region": "cn-sh2",
        "Zone": "cn-sh2-02",
        "Name": "training",
        "Password": "instance-secret",
        "IPSet": [{"Type": "Bgp", "IP": "203.0.113.10"}],
        "Softwares": [{"Name": "JupyterLab", "URL": "https://example.invalid/token"}],
        "InstanceType": "Container",
        "MachineType": "G2",
        "GpuType": "4090",
        "GPU": 1,
        "GraphicsMemory": {"Value": 24, "Unit": "GB"},
        "CPU": 8,
        "Memory": 32768,
        "CpuPlatform": "AMD/Zen4",
        "CpuArch": "x86_64",
        "SupportWithoutGpuStart": True,
        "DiskSet": [{"DiskId": "disk-1", "Size": 100}],
        "UDiskSet": [{"DiskId": "udisk-1", "Size": 50}],
        "VolumeSet": [{"VolumeId": "volume-1", "Size": 200}],
        "TotalDiskSpace": 150,
        "TotalVolumeSpace": 200,
        "ChargeType": "Postpay",
        "InstancePrice": 1.25,
        "CompShareImagePrice": 0.1,
        "DiskPrice": 0.05,
        "DiskPriceInfo": [{"Price": 0.05}],
        "DiscountType": 1,
        "AutoRenew": "No",
        "IsExpire": "No",
        "ExpireTime": 1800000000,
        "PostPayPowerOffBillingResource": [{"Type": "Disk"}],
        "CompShareImageId": "image-1",
        "CompShareImageName": "PyTorch",
        "CompShareImageType": "System",
        "CompShareImageVersionName": "v1",
        "CompShareImageStatus": "Available",
        "CompShareImageAuthor": "Compshare",
        "OsName": "Ubuntu 22.04",
        "OsType": "Linux",
        "BasicImageId": "base-1",
        "BasicImageName": "Ubuntu",
        "State": "Running",
        "CreateTime": 1700000000,
        "StartTime": 1700000100,
        "StopTime": 0,
        "UpdateTime": 1700000200,
        "SchedulerStopTime": 1700000300,
        "ReleaseTime": 0,
    }
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: ("cn-sh2", "cn-sh2-02", host),
    )
    expected = {
        "--ip": {"IPSet"},
        "--softwares": {"Softwares"},
        "--spec": {
            "InstanceType",
            "MachineType",
            "GpuType",
            "GPU",
            "GraphicsMemory",
            "CPU",
            "Memory",
            "CpuPlatform",
            "CpuArch",
            "SupportWithoutGpuStart",
        },
        "--disks": {"DiskSet", "UDiskSet", "VolumeSet", "TotalDiskSpace", "TotalVolumeSpace"},
        "--billing": {
            "ChargeType",
            "InstancePrice",
            "CompShareImagePrice",
            "DiskPrice",
            "DiskPriceInfo",
            "DiscountType",
            "AutoRenew",
            "IsExpire",
            "ExpireTime",
            "PostPayPowerOffBillingResource",
        },
        "--image": {
            "CompShareImageId",
            "CompShareImageName",
            "CompShareImageType",
            "CompShareImageVersionName",
            "CompShareImageStatus",
            "CompShareImageAuthor",
            "OsName",
            "OsType",
            "BasicImageId",
            "BasicImageName",
        },
        "--status": {
            "State",
            "CreateTime",
            "StartTime",
            "StopTime",
            "UpdateTime",
            "SchedulerStopTime",
            "ReleaseTime",
        },
    }

    for option, keys in expected.items():
        result = runner.invoke(cli.app, ["--json", "instance", "show", "uhost-1", option])
        assert result.exit_code == 0, result.output
        assert set(json.loads(result.stdout)["UHostSet"][0]) == keys

    combined = runner.invoke(
        cli.app,
        ["--json", "--show-sensitive", "instance", "show", "uhost-1", "--ip", "--softwares"],
    )
    assert combined.exit_code == 0, combined.output
    assert json.loads(combined.stdout) == {
        "UHostSet": [
            {
                "IPSet": [{"Type": "Bgp", "IP": "203.0.113.10"}],
                "Softwares": [{"Name": "JupyterLab", "URL": "https://example.invalid/token"}],
            }
        ]
    }


def test_instance_show_focused_human_output_still_redacts_sensitive_values(monkeypatch) -> None:
    host = {
        "IPSet": [{"Type": "Bgp", "IP": "203.0.113.10"}],
        "Softwares": [{"Name": "JupyterLab", "URL": "https://example.invalid/token"}],
    }
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: ("cn-sh2", "cn-sh2-02", host),
    )

    safe = runner.invoke(cli.app, ["instance", "show", "uhost-1", "--ip", "--softwares"])
    private = runner.invoke(
        cli.app,
        ["--show-sensitive", "instance", "show", "uhost-1", "--ip", "--softwares"],
    )

    assert safe.exit_code == 0, safe.output
    assert "JupyterLab" in safe.stdout
    assert "203.0.113.10" not in safe.stdout
    assert "https://example.invalid/token" not in safe.stdout
    assert private.exit_code == 0, private.output
    assert "203.0.113.10" in private.stdout
    assert "https://example.invalid/token" in private.stdout


def test_ssh_print_redacts_sensitive_values_by_default(monkeypatch) -> None:
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
        "command": "***",
        "password": "***",
        "credential_source": "api",
    }


def test_ssh_print_includes_sensitive_values_only_with_global_flag(monkeypatch) -> None:
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
        ["--json", "--show-sensitive", "instance", "ssh", "uhost-1", "--print"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "instance": "uhost-1",
        "command": "ssh root@example.invalid",
        "password": "instance-secret",
        "credential_source": "api",
    }


def test_ssh_reuses_cached_connection_data_without_describing_again(monkeypatch) -> None:
    descriptions = []

    def locate(state, value):
        descriptions.append(value)
        return (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "Region": "cn-wlcb",
                "Zone": "cn-wlcb-01",
                "State": "Running",
                "SshLoginCommand": "ssh root@example.invalid",
                "Password": "instance-secret",
            },
        )

    monkeypatch.setattr(instance, "locate_instance", locate)
    args = ["--json", "instance", "ssh", "uhost-1", "--print"]

    first = runner.invoke(cli.app, args)
    second = runner.invoke(cli.app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert json.loads(first.stdout)["credential_source"] == "api"
    assert json.loads(second.stdout)["credential_source"] == "cache"
    assert descriptions == ["uhost-1"]


def test_ssh_automatically_enters_hidden_password_by_default(monkeypatch) -> None:
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
    connections = []
    monkeypatch.setattr(
        instance,
        "connect_with_password",
        lambda argv, password: connections.append((argv, password)) or 0,
    )

    result = runner.invoke(cli.app, ["instance", "ssh", "uhost-1"])

    assert result.exit_code == 0, result.output
    assert "instance-secret" not in result.stdout
    assert connections == [(["ssh", "root@example.invalid"], "instance-secret")]


def test_ssh_decodes_api_password_before_connecting(monkeypatch) -> None:
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
                "Password": "aW5zdGFuY2Utc2VjcmV0",
            },
        ),
    )
    connections = []
    monkeypatch.setattr(
        instance,
        "connect_with_password",
        lambda argv, password: connections.append((argv, password)) or 0,
    )

    result = runner.invoke(cli.app, ["instance", "ssh", "uhost-1"])

    assert result.exit_code == 0, result.output
    assert "instance-secret" not in result.stdout
    assert "aW5zdGFuY2Utc2VjcmV0" not in result.stdout
    assert connections == [(["ssh", "root@example.invalid"], "instance-secret")]


def test_ssh_shows_password_before_connecting_with_global_flag(monkeypatch) -> None:
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
    monkeypatch.setattr(instance, "connect_with_password", lambda argv, password: 0)

    result = runner.invoke(
        cli.app,
        ["--show-sensitive", "instance", "ssh", "uhost-1"],
    )

    assert result.exit_code == 0, result.output
    assert "Password: instance-secret" in result.stdout


def test_ssh_can_disable_automatic_password_entry(monkeypatch) -> None:
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

    result = runner.invoke(
        cli.app,
        ["instance", "ssh", "uhost-1", "--no-auto-password"],
    )

    assert result.exit_code == 0, result.output
    assert "instance-secret" not in result.stdout
    assert "--show-sensitive" in result.stdout
    assert commands == [["ssh", "root@example.invalid"]]


def test_ssh_falls_back_when_password_automation_is_unavailable(monkeypatch) -> None:
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

    def unavailable(argv, password):
        raise instance.PasswordAutomationUnavailable

    commands = []
    monkeypatch.setattr(instance, "connect_with_password", unavailable)
    monkeypatch.setattr(instance.subprocess, "call", lambda argv: commands.append(argv) or 0)

    result = runner.invoke(cli.app, ["instance", "ssh", "uhost-1"])

    assert result.exit_code == 0, result.output
    assert "instance-secret" not in result.stdout
    assert "无法自动填写密码" in result.stdout
    assert commands == [["ssh", "root@example.invalid"]]


def test_ssh_executes_remote_command_with_password_and_returns_its_status(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "Zone": "cn-wlcb-01",
                "SshLoginCommand": "ssh -p 2222 root@example.invalid",
                "Password": "instance-secret",
            },
        ),
    )
    executions = []
    monkeypatch.setattr(
        instance,
        "execute_with_password",
        lambda argv, password: executions.append((argv, password)) or 23,
    )

    result = runner.invoke(
        cli.app,
        [
            "instance",
            "ssh",
            "uhost-1",
            "--",
            "nvidia-smi",
            "--query-gpu=name",
        ],
    )

    assert result.exit_code == 23, result.output
    assert "instance-secret" not in result.stdout
    assert executions == [
        (
            [
                "ssh",
                "-o",
                "ConnectTimeout=30",
                "-p",
                "2222",
                "root@example.invalid",
                "nvidia-smi",
                "--query-gpu=name",
            ],
            "instance-secret",
        )
    ]


def test_ssh_json_executes_and_returns_structured_connection_error(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "State": "Running",
                "SshLoginCommand": "ssh root@example.invalid",
                "Password": "instance-secret",
            },
        ),
    )
    executions = []
    monkeypatch.setattr(
        instance,
        "execute_captured_with_password",
        lambda argv, password: (
            executions.append((argv, password))
            or RemoteExecutionResult(
                255,
                "",
                "ssh: connect to host example.invalid port 22: Connection timed out\n",
                "connection",
                "connection_timeout",
            )
        ),
    )

    result = runner.invoke(
        cli.app,
        ["--json", "instance", "ssh", "uhost-1", "--", "hostname"],
    )

    assert result.exit_code == 255, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "instance": "uhost-1",
        "ok": False,
        "phase": "connection",
        "exit_code": 255,
        "stdout": "",
        "stderr": "ssh: connect to host example.invalid port 22: Connection timed out\n",
        "error": {
            "phase": "connection",
            "code": "connection_timeout",
            "message": "ssh: connect to host example.invalid port 22: Connection timed out",
        },
        "credential_source": "api",
    }
    assert executions == [
        (
            [
                "ssh",
                "-o",
                "ConnectTimeout=30",
                "root@example.invalid",
                "hostname",
            ],
            "instance-secret",
        )
    ]


def test_ssh_print_includes_quoted_remote_command_when_sensitive(monkeypatch) -> None:
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
        [
            "--json",
            "--show-sensitive",
            "instance",
            "ssh",
            "uhost-1",
            "--print",
            "--",
            "cd /workspace && python train.py",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "instance": "uhost-1",
        "command": "ssh root@example.invalid 'cd /workspace && python train.py'",
        "password": "instance-secret",
        "credential_source": "api",
    }


def test_scp_uploads_local_file_with_instance_password(monkeypatch, tmp_path) -> None:
    source = tmp_path / "model.bin"
    source.write_bytes(b"model")
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "Zone": "cn-wlcb-01",
                "SshLoginCommand": "ssh root@example.invalid -p 2222",
                "Password": "instance-secret",
            },
        ),
    )
    copies = []
    monkeypatch.setattr(
        instance,
        "copy_with_password",
        lambda argv, password: copies.append((argv, password)) or 17,
    )

    result = runner.invoke(
        cli.app,
        ["instance", "scp", "uhost-1", str(source), "/workspace/model.bin"],
    )

    assert result.exit_code == 17, result.output
    assert "instance-secret" not in result.stdout
    assert copies == [
        (
            [
                "scp",
                "-P",
                "2222",
                str(source.resolve()),
                "root@example.invalid:/workspace/model.bin",
            ],
            "instance-secret",
        )
    ]


def test_scp_uploads_directory_recursively(monkeypatch, tmp_path) -> None:
    source = tmp_path / "dataset"
    source.mkdir()
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
    copies = []
    monkeypatch.setattr(
        instance,
        "copy_with_password",
        lambda argv, password: copies.append(argv) or 0,
    )

    result = runner.invoke(
        cli.app,
        ["instance", "scp", "uhost-1", str(source), "/workspace/dataset"],
    )

    assert result.exit_code == 0, result.output
    assert copies == [
        [
            "scp",
            "-r",
            str(source.resolve()),
            "root@example.invalid:/workspace/dataset",
        ]
    ]


def test_cp_upload_accepts_explicit_remote_path_marker(monkeypatch, tmp_path) -> None:
    source = tmp_path / "model.bin"
    source.write_bytes(b"model")
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "SshLoginCommand": "ssh root@example.invalid",
                "Password": "instance-secret",
            },
        ),
    )
    copies = []
    monkeypatch.setattr(
        instance,
        "copy_with_password",
        lambda argv, password: copies.append(argv) or 0,
    )

    result = runner.invoke(
        cli.app,
        ["instance", "cp", "uhost-1", str(source), ":/workspace/model.bin"],
    )

    assert result.exit_code == 0, result.output
    assert copies == [["scp", str(source.resolve()), "root@example.invalid:/workspace/model.bin"]]


def test_cp_downloads_remote_file_or_directory_recursively(monkeypatch, tmp_path) -> None:
    destination = tmp_path / "results"
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (
            "cn-wlcb",
            "cn-wlcb-01",
            {
                "UHostId": value,
                "SshLoginCommand": "ssh root@example.invalid -p 2222",
                "Password": "instance-secret",
            },
        ),
    )
    copies = []
    monkeypatch.setattr(
        instance,
        "copy_with_password",
        lambda argv, password: copies.append((argv, password)) or 0,
    )

    result = runner.invoke(
        cli.app,
        ["instance", "cp", "uhost-1", ":/workspace/results", str(destination)],
    )

    assert result.exit_code == 0, result.output
    assert copies == [
        (
            [
                "scp",
                "-P",
                "2222",
                "-r",
                "root@example.invalid:/workspace/results",
                str(destination.absolute()),
            ],
            "instance-secret",
        )
    ]


def test_cp_rejects_two_remote_paths_before_querying_instance(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (_ for _ in ()).throw(AssertionError("should not query instance")),
    )

    result = runner.invoke(
        cli.app,
        ["instance", "cp", "uhost-1", ":/workspace/source", ":/workspace/target"],
    )

    assert result.exit_code != 0
    assert "不能同时位于实例" in str(result.exception)


def test_scp_rejects_missing_local_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        instance,
        "locate_instance",
        lambda state, value: (_ for _ in ()).throw(AssertionError("should not query instance")),
    )

    result = runner.invoke(
        cli.app,
        ["instance", "scp", "uhost-1", str(tmp_path / "missing"), "/workspace"],
    )

    assert result.exit_code != 0
    assert "不存在" in str(result.exception)


def test_scp_print_redacts_command_by_default(monkeypatch, tmp_path) -> None:
    source = tmp_path / "private-model.bin"
    source.write_bytes(b"model")
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
        ["--json", "instance", "scp", "uhost-1", str(source), "/workspace", "--print"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "instance": "uhost-1",
        "command": "***",
    }
    assert str(source) not in result.stdout


def test_json_scp_executes_and_returns_structured_result(monkeypatch, tmp_path) -> None:
    source = tmp_path / "model.bin"
    source.write_bytes(b"model")
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
    copies = []
    monkeypatch.setattr(
        instance,
        "copy_captured_with_password",
        lambda argv, password: (
            copies.append((argv, password))
            or RemoteExecutionResult(0, "uploaded\n", "", "completed")
        ),
    )

    result = runner.invoke(
        cli.app,
        ["--json", "instance", "scp", "uhost-1", str(source), "/workspace/model.bin"],
    )

    assert result.exit_code == 0, result.output
    assert copies == [
        (
            [
                "scp",
                str(source.resolve()),
                "root@example.invalid:/workspace/model.bin",
            ],
            "instance-secret",
        )
    ]
    assert json.loads(result.stdout) == {
        "instance": "uhost-1",
        "ok": True,
        "phase": "completed",
        "exit_code": 0,
        "stdout": "uploaded\n",
        "stderr": "",
        "error": None,
    }


def test_json_scp_propagates_copy_failure(monkeypatch, tmp_path) -> None:
    source = tmp_path / "model.bin"
    source.write_bytes(b"model")
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
    monkeypatch.setattr(
        instance,
        "copy_captured_with_password",
        lambda argv, password: RemoteExecutionResult(
            255,
            "",
            "Permission denied",
            "authentication",
            "authentication_failed",
        ),
    )

    result = runner.invoke(
        cli.app,
        ["--json", "instance", "scp", "uhost-1", str(source), "/workspace/model.bin"],
    )

    assert result.exit_code == 255
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["exit_code"] == 255
    assert payload["error"] == {
        "phase": "authentication",
        "code": "authentication_failed",
        "message": "Permission denied",
    }


def test_instance_list_applies_global_pagination_after_filters(monkeypatch) -> None:
    responses = [
        {"UHostId": "a-1", "State": "Running", "Region": "cn-a"},
        {"UHostId": "a-2", "State": "Stopped", "Region": "cn-a"},
        {"UHostId": "a-3", "State": "Running", "Region": "cn-a"},
        {"UHostId": "b-1", "State": "Running", "Region": "cn-b"},
        {"UHostId": "b-2", "State": "Running", "Region": "cn-b"},
    ]

    def fake_pages(state, action, params, list_key, **kwargs):
        assert action == "DescribeCompShareInstance"
        assert kwargs == {}
        assert "Region" not in params
        return {"UHostSet": responses}

    monkeypatch.setattr(instance, "collect_pages", fake_pages)
    result = runner.invoke(
        cli.app,
        ["--json", "instance", "list", "--status", "Running", "--limit", "2", "--offset", "1"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["TotalCount"] == 5
    assert payload["FilteredCount"] == 4
    assert payload["ReturnedCount"] == 2
    assert [item["UHostId"] for item in payload["UHostSet"]] == ["a-3", "b-1"]


def test_instance_list_requires_region_and_zone_together(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--json", "instance", "list", "--region", "cn-sh2"])

    assert raised.value.code == 2
    assert "--region" in json.loads(capsys.readouterr().out)["error"]


def test_instance_list_passes_explicit_region_and_zone(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key, **kwargs):
        calls.append((action, params, list_key))
        return {"UHostSet": []}

    monkeypatch.setattr(instance, "collect_pages", fake_pages)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "instance",
            "list",
            "--region",
            "cn-sh2",
            "--zone",
            "cn-sh2-02",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "DescribeCompShareInstance",
            {"Region": "cn-sh2", "Zone": "cn-sh2-02"},
            "UHostSet",
        )
    ]


def test_instance_list_all_ignores_display_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "collect_pages",
        lambda *args, **kwargs: {
            "UHostSet": [{"UHostId": f"host-{index}", "Region": "cn-a"} for index in range(25)]
        },
    )
    result = runner.invoke(cli.app, ["--json", "instance", "list", "--all"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["Limit"] is None
    assert payload["ReturnedCount"] == 25


def test_instance_list_does_not_invent_missing_region(monkeypatch) -> None:
    monkeypatch.setattr(
        instance,
        "collect_pages",
        lambda *args, **kwargs: {"UHostSet": [{"UHostId": "host-1", "Zone": "cn-sh2-02"}]},
    )

    result = runner.invoke(cli.app, ["--json", "instance", "list", "--all"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "Region" not in payload["UHostSet"][0]
    assert payload["RegionSet"] == []


def test_batch_lifecycle_reports_partial_failure(monkeypatch) -> None:
    locations = {
        value: ("cn-a", "cn-a-01", {"UHostId": value, "Zone": "cn-a-01"})
        for value in ("host-1", "host-2")
    }
    monkeypatch.setattr(
        instance,
        "_locate_instances",
        lambda state, values: (locations, []),
    )

    def fake_call(state, action, params):
        if params["UHostId"] == "host-2":
            return None, {"message": "capacity unavailable", "ret_code": 1}
        return {"RetCode": 0}, None

    monkeypatch.setattr(instance, "call_captured", fake_call)
    result = runner.invoke(
        cli.app,
        ["--json", "instance", "start", "host-1", "host-2", "--no-wait"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert [item["instance"] for item in payload["succeeded"]] == ["host-1"]
    assert payload["failed"][0]["instance"] == "host-2"


def test_create_max_price_stops_before_create(monkeypatch, capsys) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(action)
        if action == "CheckCompShareResourceCapacity":
            return {"Specs": [{"Gpu": 1, "Cpu": 12, "Mem": 32, "ResourceEnough": True}]}
        if action == "GetCompShareInstancePrice":
            return {"PriceDetails": [{"Instance": 0.7, "SystemDisks": 0}]}
        raise AssertionError(action)

    monkeypatch.setattr(instance, "call", fake_call)
    with pytest.raises(SystemExit) as raised:
        cli.main(
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
                "--region",
                "cn-wlcb",
                "--zone",
                "cn-wlcb-01",
                "--max-price",
                "0.50",
                "--yes",
            ]
        )

    assert raised.value.code == 2
    assert calls == ["CheckCompShareResourceCapacity", "GetCompShareInstancePrice"]
    assert "0.7" in json.loads(capsys.readouterr().out)["error"]


def test_team_invite_builds_user_info(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {"RetCode": 0, "ErrorMap": {}}

    monkeypatch.setattr(team, "call", fake_call)
    result = runner.invoke(
        cli.app,
        ["team", "invite", "send", "1001", "50001:Alice", "50002", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == "CreateCompShareTeamRelation"
    assert calls[0][1]["UserInfo"] == [
        {"UserCompanyId": 50001, "RemarkName": "Alice"},
        {"UserCompanyId": 50002},
    ]


def test_team_invite_reports_partial_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        team,
        "call",
        lambda state, action, params: {
            "RetCode": 0,
            "ErrorMap": {"50002": {"Code": 16001, "Message": "already joined"}},
        },
    )
    result = runner.invoke(
        cli.app,
        ["--json", "team", "invite", "send", "1001", "50001", "50002", "--yes"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["ErrorMap"]["50002"]["Code"] == 16001


def test_team_quota_converts_yuan_to_cents(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append((action, params))
        return {"RetCode": 0, "FailedMembers": {}}

    monkeypatch.setattr(team, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "team",
            "quota",
            "grant",
            "1001",
            "60001",
            "60002",
            "--amount",
            "123.45",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == "SetCompShareTeamAmount"
    assert calls[0][1]["VirtualCompanyId"] == [60001, 60002]
    assert calls[0][1]["Amount"] == 12345
    assert calls[0][1]["OperateType"] == "AllocateAmount"


def test_team_quota_reports_partial_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        team,
        "call",
        lambda state, action, params: {
            "RetCode": 0,
            "FailedMembers": {"60002": {"Code": 17001, "Message": "insufficient quota"}},
        },
    )
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "team",
            "quota",
            "reclaim",
            "1001",
            "60001",
            "60002",
            "--amount",
            "1.00",
            "--yes",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["FailedMembers"]["60002"]["Code"] == 17001


def test_team_billing_uses_api_sort_values(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key, **kwargs):
        calls.append((action, params))
        return {"OrderInfos": []}

    monkeypatch.setattr(team, "collect_pages", fake_pages)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "team",
            "billing",
            "list",
            "1001",
            "60001",
            "--sort",
            "order-start-time",
            "--ascending",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == "DescribeTeamMemberOrder"
    assert calls[0][1]["OrderBy"] == "order_start_time"
    assert calls[0][1]["OrderDir"] == "ASC"


def test_team_unpaid_combines_orders_and_summary(monkeypatch) -> None:
    calls = []

    def fake_pages(state, action, params, list_key, **kwargs):
        calls.append((action, dict(params)))
        return {"OrderInfos": [{"OrderNo": "order-1"}]}

    def fake_call(state, action, params):
        calls.append((action, dict(params)))
        return {"TotalCount": 1, "Amount": "50.00"}

    monkeypatch.setattr(team, "collect_pages", fake_pages)
    monkeypatch.setattr(team, "call", fake_call)
    result = runner.invoke(
        cli.app,
        [
            "--json",
            "team",
            "billing",
            "unpaid",
            "1001",
            "60001",
            "--start",
            "2026-07-01T00:00:00+08:00",
            "--end",
            "2026-07-02T00:00:00+08:00",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["orders"]["OrderInfos"][0]["OrderNo"] == "order-1"
    assert payload["summary"]["Amount"] == "50.00"
    assert calls[0][1] == calls[1][1]
    assert {"BeginTime", "EndTime"} <= calls[1][1].keys()


def test_team_export_writes_csv(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        team,
        "download_file",
        lambda state, action, params: (b"order,amount\n1,10\n", {"Content-Type": "text/csv"}),
    )
    output = tmp_path / "orders.csv"
    result = runner.invoke(
        cli.app,
        ["--json", "team", "billing", "export", "1001", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == b"order,amount\n1,10\n"
    assert json.loads(result.stdout)["path"] == str(output)


def test_doctor_is_read_only_and_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "private")
    monkeypatch.setattr(
        doctor_module,
        "call_captured",
        lambda state, action, params: ({"ZoneInfo": [{"Zone": "cn-a-01"}]}, None),
    )
    monkeypatch.setattr(doctor_module.shutil, "which", lambda value: f"/usr/bin/{value}")
    result = runner.invoke(cli.app, ["--json", "doctor"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert {item["Check"] for item in payload["checks"]} >= {"Credentials", "API", "ssh"}


def test_doctor_does_not_treat_windows_mode_bits_as_posix_permissions(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMPSHARE_CONFIG_FILE", str(path))
    monkeypatch.setenv("COMPSHARE_PUBLIC_KEY", "public")
    monkeypatch.setenv("COMPSHARE_PRIVATE_KEY", "private")
    monkeypatch.setattr(doctor_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        doctor_module,
        "call_captured",
        lambda state, action, params: ({"ZoneInfo": [{"Zone": "cn-a-01"}]}, None),
    )

    result = runner.invoke(cli.app, ["--json", "doctor"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    permissions = next(item for item in payload["checks"] if item["Check"] == "Permissions")
    assert permissions["Status"] == "Warning"
    assert "Windows ACL" in permissions["Detail"]
