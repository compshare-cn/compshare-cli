# CompShare CLI

在终端中管理优云智算 GPU 实例、实例镜像、云盘与 US3 挂载。

第一阶段覆盖 `compshare-docs` 中三个公开 API 目录的 51 个 Action：

- GPU 实例：27 个 Action
- 实例镜像：17 个 Action
- 磁盘与云存储：7 个 Action

CLI 使用官方 [`ucloud-sdk-python3`](https://github.com/ucloud/ucloud-sdk-python3) 完成鉴权、参数编码、请求传输与重试。调用层使用 SDK 的通用 `invoke` 接口，因为 CompShare 的公开 API 更新可能早于 SDK 的生成式请求模型；这样不会静默丢弃新参数。

## 安装

要求 Python 3.9 或更高版本。

```bash
python -m pip install .
compshare --help
```

开发环境：

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
```

## 配置

交互式保存 API 密钥：

```bash
compshare config --name production
```

每个凭证 profile 只保存名称、公钥和私钥，不绑定地域、可用区或项目。配置默认保存到 `~/.config/compshare/config.json`，目录权限为 `0700`，文件权限为 `0600`。支持多个凭证 profile：

```bash
compshare --profile production instance list
```

也可以完全通过环境变量运行：

```bash
export COMPSHARE_PUBLIC_KEY='...'
export COMPSHARE_PRIVATE_KEY='...'
export COMPSHARE_REGION='cn-wlcb'
export COMPSHARE_ZONE='cn-wlcb-01'
```

其中公私钥属于凭证；Region 和 Zone 只是请求位置。支持的环境变量还有 `COMPSHARE_PROFILE` 和 `COMPSHARE_CONFIG_FILE`。

## 全局参数

```text
--profile       选择凭证 profile
--region        指定本次请求的地域，不写入凭证
--zone          指定本次请求的可用区，不写入凭证
--json          输出适合脚本处理的 JSON
```

例如临时查询上海地域：

```bash
compshare --region cn-sh2 --zone cn-sh2-02 instance list
```

`ProjectId` 不是账户凭证的一部分。只有实例列表筛选、定时关机等需要项目范围的命令才提供自己的 `--project-id` 参数。

`--json` 可以放在命令前或命令后：

```bash
compshare --json instance list
compshare instance list --json
```

成功时 JSON 模式直接输出 API 响应；失败时输出 `{"ok":false,"error":"..."}` 并返回非零退出码。实例密码和 FileBrowser 密码保留 API 原值，API 私钥仍会脱敏。

CLI 默认显示中文帮助描述。使用一级命令持久切换语言，配置会写入本地配置文件，但不属于任何凭证 profile：

```bash
compshare --help
compshare lang en
compshare instance create --help
compshare lang zh
compshare lang       # 查看当前语言
```

也可以通过 `COMPSHARE_LANG=en` 覆盖当前终端会话的帮助语言。当前版本不安装 Shell completion，仅提供 `-h/--help`。

## 实例

### 查规格和库存

不带镜像时，`search` 展示合法的 GPU、CPU 和内存组合：

```bash
compshare instance search
compshare instance search --gpu 4090 --gpu A100
```

库存不是机型的固定属性。它还取决于镜像、磁盘、计费方式和 CPU 平台，因此检查真实库存时需要指定镜像：

```bash
compshare instance search \
  --gpu 4090 \
  --image compshareImage-xxxx \
  --disk 100GiB \
  --disk-type CLOUD_SSD \
  --charge Postpay \
  --available
```

该命令先调用 `DescribeAvailableCompShareInstanceTypes` 获取合法规格，再按匹配的 GPU 型号调用 `CheckCompShareResourceCapacity`。`--available` 不会用 Describe 接口的状态冒充库存。

### 创建

直接运行不带规格参数的命令会进入交互向导：

```bash
compshare instance create
```

向导会依次读取可用区、GPU 机型和镜像；选择计费方式与磁盘后，调用真实库存接口，只展示当前可创建的 GPU、CPU、内存组合。最后查询完整价格并要求确认。镜像来源支持 `platform`、`custom`、`community` 和 `shared`。

也可以预先指定部分选项，让向导只补齐剩余内容：

```bash
compshare instance create --gpu 3080Ti --image-source platform
```

自动化场景使用完整参数模式：

```bash
compshare instance create \
  --gpu 4090 \
  --count 1 \
  --cpu 16 \
  --memory 64GiB \
  --image compshareImage-xxxx \
  --disk 100GiB \
  --data-disk 200GiB:CLOUD_SSD \
  --charge Postpay
```

创建前会依次检查目标组合库存和价格，得到确认后才创建。自动化中可使用 `--yes` 跳过最终确认。`--json` 不会启动交互向导，因此必须同时提供 `--gpu`、`--count`、`--cpu`、`--memory` 和 `--image`。

### 命令概览

```text
compshare instance search
compshare instance zones
compshare instance families
compshare instance list
compshare instance show INSTANCE
compshare instance create
compshare instance start INSTANCE
compshare instance stop INSTANCE
compshare instance reboot INSTANCE
compshare instance delete INSTANCE
compshare instance rename INSTANCE NAME
compshare instance password INSTANCE
compshare instance reinstall INSTANCE
compshare instance resize INSTANCE
compshare instance price
compshare instance upgrade-price INSTANCE
compshare instance billing
compshare instance refund INSTANCE...
compshare instance monitor [INSTANCE...]
compshare instance charge INSTANCE --to Month
compshare instance network
compshare instance models
compshare instance ssh INSTANCE
compshare instance ports list
compshare instance ports update INSTANCE
compshare instance schedule set INSTANCE --at 2026-07-16T12:00:00+08:00 --project-id PROJECT
compshare instance schedule cancel INSTANCE --project-id PROJECT
compshare instance software list
compshare instance software url INSTANCE JupyterLab
```

`ssh` 会在连接前显示 API 返回的实例密码；使用 `ssh INSTANCE --print` 时会同时输出 SSH 命令和密码。

`resize` 明确区分计算规格调整和磁盘扩容，两者不能放在同一次请求中。执行删除、关机、重启、重装、改配等高影响操作时默认要求确认。

## 镜像

用 `--source` 在不同镜像来源间切换：

```bash
compshare image list --source platform
compshare image list --source custom
compshare image list --source community --query pytorch --tag LLM
compshare image list --source shared
compshare image list --source published
compshare image list --source user --user 12345
```

完整命令：

```text
compshare image list
compshare image show IMAGE
compshare image create --instance INSTANCE --name NAME
compshare image progress IMAGE
compshare image update IMAGE
compshare image delete IMAGE
compshare image shares IMAGE
compshare image share IMAGE ACCOUNT...
compshare image unshare IMAGE ACCOUNT...
compshare image publish IMAGE --version v1.0
compshare image favorite IMAGE
compshare image unfavorite IMAGE
compshare image tags
```

社区镜像列表支持名称、作者、模糊查询、标签、免费/付费、官方/非官方、自启动和排序筛选。封面文件由 CLI 转成 Base64，README 文件按 UTF-8 读取。

## 磁盘与云存储

```text
compshare storage disk list
compshare storage disk create --instance INSTANCE --size 100GiB --name DATA
compshare storage disk attach DISK --instance INSTANCE
compshare storage disk detach DISK --instance INSTANCE --device /dev/vdb
compshare storage disk price DISK --instance INSTANCE --size 200GiB
compshare storage disk resize DISK --size 200GiB
compshare storage disk delete DISK
compshare storage us3 attach --instance INSTANCE
```

`storage us3 attach` 覆盖 CompShare 的 US3 挂载 Action。对象上传、下载、Bucket 管理继续使用独立的 `us3cli`，避免在本 CLI 中复制另一套成熟工具的能力。

## 开发校验

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest
```

公开 Action 清单维护在 `compshare_cli.actions` 中，测试会校验 27/17/7 的领域数量以及命令实现是否包含全部 51 个 Action。
