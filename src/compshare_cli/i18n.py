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
    "Get instance monitoring data (currently unavailable in production).": (
        "获取实例监控数据（生产环境当前不可用）。"
    ),
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
    "Get an instance software access URL (currently unavailable in production).": (
        "获取实例软件的访问地址（生产环境当前不可用）。"
    ),
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
    "No results. Try adjusting the filters or checking the selected region.": (
        "没有结果，请调整筛选条件或检查所选地域。"
    ),
    "Error": "错误",
    "yes": "是",
    "no": "否",
    "Public key": "公钥",
    "Private key": "私钥",
    "New password": "新密码",
    "Select": "请选择",
    "Aborted": "操作已取消",
    "Attach US3 during container creation.": "创建容器实例时挂载 US3。",
    "Attached instance ID.": "已挂载的实例 ID。",
    "Backup mode: NONE, DATAARK or SNAPSHOT.": "备份模式：NONE、DATAARK 或 SNAPSHOT。",
    "Billing duration for prepaid modes.": "预付费模式的购买时长。",
    "Boot disk type used for stock checks.": "库存检查使用的系统盘类型。",
    "CPU core count.": "CPU 核数。",
    "Community image description.": "社区镜像描述。",
    "Community image name.": "社区镜像名称。",
    "Community version group ID.": "社区镜像版本组 ID。",
    "Community version name.": "社区镜像版本名称。",
    "Complete HTTP port list; repeatable.": "完整 HTTP 端口列表，可重复指定。",
    "Complete TCP port list; repeatable.": "完整 TCP 端口列表，可重复指定。",
    "Coupon ID.": "代金券 ID。",
    "Cover image file encoded as Base64.": "封面图片文件，将编码为 Base64。",
    "Custom image description.": "自制镜像描述。",
    "Custom image name.": "自制镜像名称。",
    "Data disk type.": "数据盘类型。",
    "Delete attached data disks with the instance.": "删除实例时同时删除已挂载的数据盘。",
    "Disk ID to resize.": "要扩容的磁盘 ID。",
    "Disk name.": "磁盘名称。",
    "Disk type.": "磁盘类型。",
    "Existing community version group ID.": "已有社区镜像版本组 ID。",
    "Filter by VPC ID.": "按 VPC ID 筛选。",
    "Filter by automatic startup support.": "按是否支持自动启动筛选。",
    "Filter by availability zone.": "按可用区筛选。",
    "Filter by exact image name.": "按镜像完整名称筛选。",
    "Filter by image ID.": "按镜像 ID 筛选。",
    "Filter by image author.": "按镜像作者筛选。",
    "Filter by image type.": "按镜像类型筛选。",
    "Filter by instance ID.": "按实例 ID 筛选。",
    "Filter by instance tag.": "按实例标签筛选。",
    "Filter by model name.": "按模型名称筛选。",
    "Filter by model tags.": "按模型标签筛选。",
    "Filter by subnet ID.": "按子网 ID 筛选。",
    "Filter by tag; repeatable.": "按标签筛选，可重复指定。",
    "Filter by version group ID.": "按版本组 ID 筛选。",
    "Filter free or paid community images.": "筛选免费或付费社区镜像。",
    "Filter official or community-authored images.": "筛选官方或社区作者镜像。",
    "GPU type.": "GPU 型号。",
    "Hourly image price.": "镜像每小时价格。",
    "Hourly image price; 0 means free.": "镜像每小时价格，0 表示免费。",
    "Image ID for image pricing.": "用于镜像计价的镜像 ID。",
    "Image source.": "镜像来源。",
    "Image source: platform, custom, community, shared, published or user.": (
        "镜像来源：platform、custom、community、shared、published 或 user。"
    ),
    "Image tag; repeatable.": "镜像标签，可重复指定。",
    "Instance name.": "实例名称。",
    "Instance remark.": "实例备注。",
    "List no-GPU instances.": "列出无 GPU 实例。",
    "Maximum number of results.": "最多返回的结果数量。",
    "Minimum CPU platform.": "最低 CPU 平台。",
    "New image description.": "新的镜像描述。",
    "New image name.": "新的镜像名称。",
    "No-GPU specification: A or B.": "无卡规格：A 或 B。",
    "Number of instances.": "实例数量。",
    "Number of results to skip.": "跳过的结果数量。",
    "Replacement image ID.": "重装使用的镜像 ID。",
    "Security group ID.": "安全组 ID。",
    "Sort in ascending order.": "按升序排列。",
    "Source instance ID.": "源实例 ID。",
    "Supported GPU type; repeatable.": "支持的 GPU 型号，可重复指定。",
    "Target CPU core count.": "目标 CPU 核数。",
    "Target GPU count.": "目标 GPU 数量。",
    "Target disk size, for example 200GiB.": "目标磁盘大小，例如 200GiB。",
    "Target instance ID.": "目标实例 ID。",
    "Target memory, for example 64GiB.": "目标内存，例如 64GiB。",
    "Target no-GPU specification: A or B.": "目标无卡规格：A 或 B。",
    "Target running instance ID.": "目标运行中实例 ID。",
    "UTF-8 README file.": "UTF-8 编码的 README 文件。",
    "Version description.": "版本描述。",
    "Version name.": "版本名称。",
    "Visibility: 0 private, 1 public.": "可见性：0 私有，1 公开。",
    "Whether the image supports automatic startup.": "镜像是否支持自动启动。",
    "Saved credential profile {name}": "已保存凭证配置 {name}",
    "Invalid memory size: {value}. Example: 64GiB": "无效的内存大小：{value}。示例：64GiB",
    "Memory must be positive and resolve to whole GiB.": "内存必须大于 0，且换算后为整数 GiB。",
    "Invalid disk size: {value}. Example: 100GiB": "无效的磁盘大小：{value}。示例：100GiB",
    "Disk MiB must resolve to whole GiB.": "磁盘 MiB 数必须能换算成整数 GiB。",
    "Disk size must be positive.": "磁盘大小必须大于 0。",
    "Time must be a Unix timestamp, ISO 8601 value, or relative value like 30m or 2h.": (
        "时间必须是 Unix 时间戳、ISO 8601 时间，或 30m、2h 这样的相对时间。"
    ),
    "Unable to read file {path}: {error}": "无法读取文件 {path}：{error}",
    "Wait for the operation to reach a stable state.": "等待操作进入稳定状态。",
    "Maximum wait time in seconds.": "最长等待时间（秒）。",
    "Validate and show the request without changing resources.": "仅校验并显示请求，不变更资源。",
    "Operation plan": "操作计划",
    "Create plan": "创建计划",
    "Instance details": "实例详情",
    "Image details": "镜像详情",
    "Storage details": "存储详情",
    "Confirm this operation?": "确认执行该操作？",
    "Dry run completed; no resources were changed.": "预演完成，未变更任何资源。",
    "Waiting for {instance}: {state}": "正在等待 {instance}：{state}",
    "Timed out after {timeout}s while waiting for {instance}.": (
        "等待 {instance} 超过 {timeout} 秒。可以用 `compshare instance show {instance}` 检查状态。"
    ),
    "Operation submitted": "操作已提交",
    "Operation completed": "操作已完成",
    "No selectable options": "没有可选项",
    "Automatically selected the only option.": "已自动选择唯一选项。",
    "Please enter a number from 1 to {count}.": "请输入 1 到 {count} 之间的数字。",
    "Availability zone": "可用区",
    "GPU type": "GPU 型号",
    "Image source": "镜像来源",
    "Image": "镜像",
    "Billing type": "计费方式",
    "Available specification": "可用规格",
    "Filter images by name or ID (blank shows all)": "按名称或 ID 筛选镜像（留空显示全部）",
    "Boot disk size": "系统盘大小",
    "Boot disk type": "系统盘类型",
    "Password": "密码",
    "PROFILE": "配置",
    "ACTIVE": "当前",
    "ID": "ID",
    "NAME": "名称",
    "STATE": "状态",
    "GPU": "GPU",
    "COUNT": "数量",
    "CPU": "CPU",
    "MEMORY": "内存",
    "ZONE": "可用区",
    "REGION": "地域",
    "CHARGE": "计费",
    "PRICE/H": "每小时价格",
    "VRAM": "显存",
    "IN STOCK": "有库存",
    "CPU PLATFORM": "CPU 平台",
    "DESCRIPTION": "描述",
    "INSTANCE": "实例",
    "IMAGE": "镜像",
    "SYSTEM DISK": "系统盘",
    "DATA DISKS": "数据盘",
    "REFUND": "退款",
    "CODE": "代码",
    "MESSAGE": "信息",
    "PATH": "路径",
    "TAG": "标签",
    "SIZE": "大小",
    "CREATED": "创建时间",
    "SOFTWARE": "软件",
    "PORT": "端口",
    "TYPE": "类型",
    "AUTHOR": "作者",
    "STATUS": "状态",
    "VERSION": "版本",
    "TAGS": "标签",
    "ACCOUNT ID": "账户 ID",
    "ACCOUNT": "账户",
    "DISK ID": "云盘 ID",
    "BOOT": "系统盘",
    "DEVICE": "设备",
    "Manage credential profiles.": "管理 API 凭证配置。",
    "Create or update a credential profile.": "创建或更新凭证配置。",
    "List credential profiles.": "列出凭证配置。",
    "Set the default credential profile.": "设置默认凭证配置。",
    "Delete a credential profile.": "删除凭证配置。",
    "Show the configuration file path.": "显示配置文件路径。",
    "Filter by instance name.": "按实例名称筛选。",
    "Filter by instance state.": "按实例状态筛选。",
    "Filter by GPU type.": "按 GPU 型号筛选。",
    "Filter by billing type.": "按计费方式筛选。",
    "Filter by region.": "按地域筛选。",
    "Region for this request.": "本次请求的地域。",
    "Unix timestamp, ISO 8601, or relative time.": "Unix 时间戳、ISO 8601 或相对时间。",
    "Override the automatically detected project ID.": "覆盖自动检测的项目 ID。",
    "Using credential profile {name}": "已切换到凭证配置 {name}",
    "Delete credential profile {name}?": "删除凭证配置 {name}？",
    "Deleted credential profile {name}": "已删除凭证配置 {name}",
    "--available requires --image because inventory depends on the image and disks.": (
        "--available 需要同时指定 --image，库存取决于镜像和磁盘组合。"
    ),
    "--disk and --disk-size must be used together.": "--disk 和 --disk-size 必须同时使用。",
    "--image-source must be platform, custom, community, or shared.": (
        "--image-source 必须是 platform、custom、community 或 shared。"
    ),
    "--source must be platform, custom, community, shared, published, or user.": (
        "--source 必须是 platform、custom、community、shared、published 或 user。"
    ),
    "--without-gpu cannot be combined with --cpu, --memory, or --gpu.": (
        "--without-gpu 不能与 --cpu、--memory 或 --gpu 同时使用。"
    ),
    "Hint": "建议",
    "The machine type API returned an unnamed GPU.": "机型接口返回了未命名的 GPU。",
    "More than 50 images matched; use a more specific filter.": (
        "匹配到超过 50 个镜像，请输入更具体的筛选词。"
    ),
    "Unnamed": "未命名",
    "Instance {instance} was not found.": "未找到实例 {instance}。",
    "Instance {instance} was not found in any supported region.": (
        "在所有支持的地域中都未找到实例 {instance}。"
    ),
    "Attached disk {disk} was not found in any supported region; pass --zone if it is detached.": (
        "在所有支持的地域中都未找到已挂载云盘 {disk}；如果它已卸载，请指定 --zone。"
    ),
    "Image {image} was not found.": "未找到镜像 {image}。",
    "No project was returned by GetProjectList; pass --project-id explicitly.": (
        "GetProjectList 未返回项目，请显式指定 --project-id。"
    ),
    (
        "JSON mode cannot start the interactive wizard; pass --gpu, --count, --cpu, "
        "--memory, and --image."
    ): ("JSON 模式不会启动交互向导，请指定 --gpu、--count、--cpu、--memory 和 --image。"),
    (
        "No inventory is available for the selected GPU, CPU, memory, image, billing, "
        "and disk combination."
    ): ("所选 GPU、CPU、内存、镜像、计费方式和磁盘组合当前无库存。"),
    "Stop instance": "停止实例",
    "Reboot instance": "重启实例",
    "Permanently delete instance": "永久删除实例",
    "Permanently delete instance and attached data disks": "永久删除实例及其数据盘",
    "Reset instance password": "重置实例密码",
    "Reinstall instance; all system disk data will be lost": "重装实例，系统盘数据将全部丢失",
    "Resize instance": "调整实例规格",
    "Change instance billing type": "变更实例计费方式",
    "Renamed {instance}": "已重命名实例 {instance}",
    "Specify a compute target or both --disk and --disk-size.": (
        "请指定计算规格，或同时指定 --disk 和 --disk-size。"
    ),
    "Compute resizing and disk resizing must be separate operations.": (
        "计算规格调整和磁盘扩容必须分开执行。"
    ),
    "Compute resizing requires --cpu, --memory, and --gpu together.": (
        "调整计算规格时必须同时指定 --cpu、--memory 和 --gpu。"
    ),
    "Specify at least one of --cpu, --memory, or --gpu.": (
        "至少指定 --cpu、--memory 或 --gpu 中的一项。"
    ),
    "Specify at least one --http or --tcp port.": "至少指定一个 --http 或 --tcp 端口。",
    "Replace port mappings for {instance}?": "替换实例 {instance} 的端口映射？",
    "Updated port mappings": "已更新端口映射",
    "Scheduled shutdown must be at least five minutes from now.": (
        "定时关机时间必须至少晚于当前时间 5 分钟。"
    ),
    "Scheduled shutdown": "已设置定时关机",
    "Cancel scheduled shutdown for {instance}?": "取消实例 {instance} 的定时关机？",
    "Cancelled shutdown": "已取消定时关机",
    "Instance {instance} has no SSH login command.": "实例 {instance} 没有可用的 SSH 登录命令。",
    "The API did not return a password. Run `compshare instance password {instance}` to set one.": (
        "API 未返回密码。请运行 `compshare instance password {instance}` 设置密码。"
    ),
    "Platform image search supports only one --tag.": "平台镜像查询只支持一个 --tag。",
    "Image source {source} does not support: {options}": "镜像来源 {source} 不支持：{options}",
    "Image source {source} cannot be queried by ID.": "镜像来源 {source} 不支持按 ID 查询。",
    "Create custom image {name} from instance {instance}?": (
        "从实例 {instance} 创建自制镜像 {name}？"
    ),
    "Creating image {name}": "正在创建镜像 {name}",
    "Specify at least one field to update.": "至少指定一个要更新的字段。",
    "Updated image {image}": "已更新镜像 {image}",
    "Permanently delete custom image {image}?": "永久删除自制镜像 {image}？",
    "Deleted image {image}": "已删除镜像 {image}",
    "Shared image {image}": "已共享镜像 {image}",
    "Unshared image {image}": "已取消共享镜像 {image}",
    "Remove {count} share(s) from image {image}?": "从镜像 {image} 移除 {count} 个共享账户？",
    "Publish image {image} as community version {version}?": (
        "将镜像 {image} 发布为社区版本 {version}？"
    ),
    "Published image {image}": "已发布镜像 {image}",
    "Favorited image {image}": "已收藏镜像 {image}",
    "Unfavorited image {image}": "已取消收藏镜像 {image}",
    "Create {size} disk {name} and attach it to {instance}?": (
        "创建 {size} 云盘 {name} 并挂载到 {instance}？"
    ),
    "Created and attached disk {name}": "已创建并挂载云盘 {name}",
    "Attached {disk} to {instance}": "已将云盘 {disk} 挂载到 {instance}",
    "Detach disk {disk} from {instance}? Ensure it is unmounted first.": (
        "从 {instance} 卸载云盘 {disk}？请先在操作系统内卸载文件系统。"
    ),
    "Detached disk {disk}": "已卸载云盘 {disk}",
    "Resize disk {disk} to {size}? Disks cannot be shrunk.": (
        "将云盘 {disk} 扩容到 {size}？云盘不能缩容。"
    ),
    "Resized disk {disk}": "已扩容云盘 {disk}",
    "Permanently delete disk {disk} and all its data?": "永久删除云盘 {disk} 及其全部数据？",
    "Deleted disk {disk}": "已删除云盘 {disk}",
    "Attached US3 to {instance}": "已将 US3 挂载到 {instance}",
    "Resource is still detaching; retrying ({attempt}/{total})...": (
        "资源仍在卸载，正在重试（{attempt}/{total}）……"
    ),
    "The disk is still detaching. Wait a moment and retry.": "云盘仍在卸载，请稍后重试。",
    "Confirm that US3 is enabled for the selected region and account.": (
        "请确认所选地域和账户已开通 US3。"
    ),
    "This production endpoint currently rejects instance IDs; use the console for monitoring.": (
        "生产环境的该接口当前会拒绝实例 ID，请暂时在控制台查看监控。"
    ),
    "This production endpoint is currently incompatible; use the console for monitoring.": (
        "生产环境的该接口当前不兼容，请暂时在控制台查看监控。"
    ),
    "This production endpoint currently rejects its action; use instance show or the console.": (
        "生产环境的该接口当前拒绝请求，请使用 instance show 或控制台。"
    ),
    "PRICE": "价格",
    "ACTION": "操作",
    "REQUEST": "请求",
    "SSH": "SSH",
    "Waiting for image {image}: {state}": "正在等待镜像 {image}：{state}",
    "Image creation failed: {status}": "镜像创建失败：{status}",
    "Timed out after {timeout}s while waiting for image {image}.": (
        "等待镜像 {image} 超过 {timeout} 秒。"
    ),
}


def normalize_language(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"zh", "zh-cn", "cn"}:
        return "zh"
    if normalized in {"en", "en-us", "en-gb"}:
        return "en"
    raise UsageError("Language must be zh or en.")


def configured_language() -> str:
    value = os.environ.get("COMPSHARE_LANG")
    if value is None:
        try:
            value = ConfigStore().load_language()
        except ConfigError:
            value = None
    return normalize_language(value or DEFAULT_LANGUAGE)


def tr(message: str, **values: object) -> str:
    """Translate a user-facing string and interpolate named values."""
    template = ZH_TRANSLATIONS.get(message, message) if configured_language() == "zh" else message
    return template.format(**values)


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
