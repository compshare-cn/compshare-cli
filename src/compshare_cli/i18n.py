from __future__ import annotations

import os
from typing import Dict

import click

from compshare_cli.config import ConfigStore
from compshare_cli.errors import ConfigError, UsageError

DEFAULT_LANGUAGE = "zh"

ZH_TRANSLATIONS: Dict[str, str] = {
    "Manage CompShare GPU compute from the terminal.": "在终端管理优云智算 GPU 计算资源。",
    "Emit machine-readable JSON.": "输出机器可读的 JSON。",
    "Credential profile.": "凭证配置名称。",
    "Credential profile name.": "凭证配置的名称。",
    "API public key.": "API 公钥。",
    "Make this profile the default.": "将此凭证设为默认配置。",
    "Region for this request; not part of the credential profile.": (
        "本次请求的地域，不属于凭证配置。"
    ),
    "Availability zone for this request; not part of the credential profile.": (
        "本次请求的可用区，不属于凭证配置。"
    ),
    "Set or show the default help language.": "设置或查看默认帮助语言。",
    "Language: zh or en.": "语言：zh 或 en。",
    "Save a CompShare API credential profile.": "保存优云智算 API 凭证配置。",
    "Print the CLI version.": "显示 CLI 版本。",
    "Manage GPU instances.": "管理 GPU 实例。",
    "Search legal specifications and, with --image, real inventory.": (
        "查询合法规格；指定 --image 时检查真实库存。"
    ),
    "GPU type; repeatable.": "GPU 型号，可重复指定。",
    "Search interruptible instances.": "查询抢占式实例。",
    "Image ID. When set, check real inventory for every matched GPU type.": (
        "镜像 ID；指定后检查每个匹配 GPU 型号的真实库存。"
    ),
    "Show only in-stock specs.": "只显示有库存的规格。",
    "Availability zone.": "可用区。",
    "Availability zone for this request.": "本次请求的可用区。",
    "CPU platform for stock checks.": "库存检查使用的 CPU 平台。",
    "Billing type for stock checks.": "库存检查使用的计费方式。",
    "Boot disk size for stock checks.": "库存检查使用的系统盘大小。",
    "List supported regions and availability zones.": "列出支持的地域和可用区。",
    "List GPU machine families.": "列出 GPU 机型族。",
    "List instances.": "列出实例。",
    "Instance ID; repeatable.": "实例 ID，可重复指定。",
    "Filter hosts compatible with a disk.": "筛选可挂载指定云盘的实例。",
    "Project ID for this request.": "本次请求使用的项目 ID。",
    "Show full instance details.": "显示实例完整信息。",
    "Instance ID.": "实例 ID。",
    "Create instances interactively, or use explicit options for automation.": (
        "通过交互向导创建实例，也可显式传参用于自动化。"
    ),
    "GPU type, for example 4090.": "GPU 型号，例如 4090。",
    "GPU count.": "GPU 数量。",
    "Memory, for example 64GiB.": "内存大小，例如 64GiB。",
    "CompShare image ID.": "优云智算镜像 ID。",
    "Image source: platform, custom, community or shared.": (
        "镜像来源：platform、custom、community 或 shared。"
    ),
    "Boot disk size.": "系统盘大小。",
    "Boot disk type.": "系统盘类型。",
    "Data disk as SIZE[:TYPE]; repeatable.": "数据盘，格式为 SIZE[:TYPE]，可重复指定。",
    "Billing type.": "计费方式。",
    "Skip confirmation.": "跳过确认。",
    "A or B.": "无卡规格 A 或 B。",
    "Start an instance.": "启动实例。",
    "Stop an instance.": "停止实例。",
    "Reboot an instance.": "重启实例。",
    "Permanently delete an instance.": "永久删除实例。",
    "Rename an instance.": "修改实例名称。",
    "Reset an instance password.": "重置实例密码。",
    "Reinstall an instance from an image.": "使用镜像重装实例。",
    "Change instance CPU, memory, GPU or disk size.": "调整实例的 CPU、内存、GPU 或磁盘大小。",
    "Query a new instance price.": "查询新实例价格。",
    "Query the price of an instance upgrade.": "查询实例升配价格。",
    "Query current instance pricing.": "查询实例当前计费价格。",
    "Query instance refund amounts.": "查询实例退款金额。",
    "Get instance monitoring data.": "获取实例监控数据。",
    "Change an instance billing type.": "变更实例计费方式。",
    "Check network accelerator status.": "检查网络加速状态。",
    "List models in the model repository.": "列出模型仓库中的模型。",
    "Shared storage as SIZE[:TYPE]; repeatable.": "共享存储，格式为 SIZE[:TYPE]，可重复指定。",
    "Month, Day, Dynamic or Postpay.": "目标计费方式：Month、Day、Dynamic 或 Postpay。",
    "Print instead of executing SSH.": "只显示 SSH 命令，不执行连接。",
    "Open or print an instance SSH command.": "连接实例 SSH，或仅显示 SSH 命令。",
    "Manage container port mappings.": "管理容器端口映射。",
    "List supported software ports.": "列出平台支持的软件端口。",
    "Replace an instance's container port mappings.": "替换实例的容器端口映射。",
    "Manage scheduled shutdowns.": "管理定时关机。",
    "Schedule an instance shutdown.": "设置实例定时关机。",
    "Cancel an instance scheduled shutdown.": "取消实例定时关机。",
    "Unix timestamp or ISO 8601 time.": "Unix 时间戳或 ISO 8601 时间。",
    "Discover software exposed by instances.": "查询实例提供的软件入口。",
    "List supported instance software.": "列出实例支持的软件。",
    "Get an instance software access URL.": "获取实例软件的访问地址。",
    "Manage instance images.": "管理实例镜像。",
    "List platform, custom, community, shared or published images.": (
        "列出平台、自制、社区、共享或已发布镜像。"
    ),
    "Fuzzy name or author search.": "按名称或作者模糊搜索。",
    "Community sort field.": "社区镜像排序字段。",
    "Organization ID for source=user.": "source=user 时使用的组织 ID。",
    "Create a custom image from an instance.": "从实例创建自制镜像。",
    "Show image details.": "显示镜像详情。",
    "Get custom image creation progress.": "查询自制镜像创建进度。",
    "Update image metadata.": "更新镜像元数据。",
    "Permanently delete a custom image.": "永久删除自制镜像。",
    "List accounts an image is shared with.": "列出镜像已共享的账户。",
    "Share an image with accounts.": "将镜像共享给指定账户。",
    "Remove image sharing from accounts.": "取消向指定账户共享镜像。",
    "Publish an image to the community.": "将镜像发布到社区。",
    "Add an image to favorites.": "收藏镜像。",
    "Remove an image from favorites.": "取消收藏镜像。",
    "List available image tags.": "列出可用的镜像标签。",
    "Manage disks and cloud storage.": "管理磁盘和云存储。",
    "Manage instance disks.": "管理实例云盘。",
    "List disks reported by one or all instances.": "列出一个或全部实例的磁盘。",
    "Create a disk and attach it to an instance.": "创建云盘并挂载到实例。",
    "Disk size, for example 100GiB.": "磁盘大小，例如 100GiB。",
    "Device path, for example /dev/vdb.": "设备路径，例如 /dev/vdb。",
    "Attach an existing disk to an instance.": "将已有云盘挂载到实例。",
    "Detach a disk from an instance.": "从实例卸载云盘。",
    "Query a disk expansion price.": "查询云盘扩容价格。",
    "Resize a disk.": "扩容云盘。",
    "Permanently delete a disk.": "永久删除云盘。",
    "Manage US3 attachments.": "管理 US3 挂载。",
    "Attach US3 object storage to an instance.": "将 US3 对象存储挂载到实例。",
}


def normalize_language(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"zh", "zh-cn", "cn"}:
        return "zh"
    if normalized in {"en", "en-us", "en-gb"}:
        return "en"
    raise UsageError("语言只支持 zh 或 en")


def configured_language() -> str:
    value = os.environ.get("COMPSHARE_LANG")
    if value is None:
        try:
            value = ConfigStore().load_language()
        except ConfigError:
            value = None
    return normalize_language(value or DEFAULT_LANGUAGE)


def localize_command(command: click.Command, language: str) -> click.Command:
    if language == "en":
        return command

    def translate(value: str) -> str:
        return ZH_TRANSLATIONS.get(value, value)

    if command.help:
        command.help = translate(command.help)
    if command.short_help:
        command.short_help = translate(command.short_help)
    for parameter in command.params:
        help_text = getattr(parameter, "help", None)
        if help_text:
            parameter.help = translate(help_text)
    original_help_option = command.get_help_option

    def localized_help_option(context: click.Context) -> click.Option:
        option = original_help_option(context)
        if option is not None:
            option.help = "显示帮助并退出。"
        return option

    command.get_help_option = localized_help_option  # type: ignore[method-assign]
    if isinstance(command, click.Group):
        for child in command.commands.values():
            localize_command(child, language)
    return command
