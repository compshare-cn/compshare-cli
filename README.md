# CompShare CLI

在终端管理优云智算 GPU 实例、镜像、云盘、US3 挂载和团队资源。

- 交互式创建实例，实时查询规格、库存和价格
- 支持批量生命周期操作、等待状态和跨地域查询
- 支持社区/自定义镜像、云盘、团队额度与账单
- 默认中文帮助，可切换英文；所有命令支持 JSON 输出
- 基于官方 [`ucloud-sdk-python3`](https://github.com/ucloud/ucloud-sdk-python3)

当前版本：`0.2.1`，要求 Python 3.9 或更高版本。

## 安装

```bash
python -m pip install "git+https://github.com/BennielAllan/compshare-cli.git"
compshare -h
```

本地开发：

```bash
git clone https://github.com/BennielAllan/compshare-cli.git
cd compshare-cli
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Windows 激活虚拟环境时使用：

```powershell
.\.venv\Scripts\Activate.ps1
```

## 配置

```bash
compshare config --name default
```

凭证保存在 `~/.config/compshare/config.json`，支持多个配置：

```bash
compshare config list
compshare config use production
compshare --profile production instance list
```

也可以使用环境变量：

```bash
export COMPSHARE_PUBLIC_KEY='...'
export COMPSHARE_PRIVATE_KEY='...'
```

## 快速开始

```bash
# 查规格、库存和实例
compshare instance search
compshare instance search --gpu 4090 --image IMAGE_ID --available
compshare instance list --all

# 交互式创建
compshare instance create

# 批量操作与等待
compshare instance stop INSTANCE_1 INSTANCE_2
compshare instance start INSTANCE_1 INSTANCE_2
compshare instance wait INSTANCE_1 INSTANCE_2 --state Running

# SSH
compshare instance ssh INSTANCE_ID
```

自动化创建示例：

```bash
compshare instance create \
  --gpu 4090 \
  --count 1 \
  --cpu 16 \
  --memory 64GiB \
  --image IMAGE_ID \
  --disk 100GiB \
  --charge Postpay \
  --max-price 20 \
  --yes
```

使用 `--dry-run` 只检查库存、价格和请求，不创建资源。

## 功能入口

```text
compshare instance   GPU 实例、规格、库存、价格和生命周期
compshare image      平台、自定义、社区及共享镜像
compshare storage    云盘和 US3 挂载
compshare team       团队、邀请、成员额度、账单和审计
compshare doctor     配置、鉴权、网络与 SSH 环境诊断
```

查看完整命令和参数：

```bash
compshare -h
compshare instance -h
compshare instance create -h
```

## 脚本调用

`--json` 和 `--profile` 是全局选项，必须放在子命令前：

```bash
compshare --json instance list --status Running --all
compshare --profile production image list --source community
```

JSON 模式不会启动交互向导。生命周期操作可使用 `--wait`、`--no-wait` 和
`--timeout` 控制等待行为；部分批量操作失败时，CLI 返回非零退出码。

Region 和 Zone 是资源参数，放在对应子命令后：

```bash
compshare instance list --region cn-sh2
compshare instance create --zone cn-sh2-02
```

## 语言

```bash
compshare lang en
compshare lang zh
compshare lang       # 查看当前语言
```

也可以通过 `COMPSHARE_LANG=en` 临时覆盖。

## 安全说明

- 配置目录和文件分别使用 `0700`、`0600` 权限。
- API 私钥不会出现在命令输出中。
- `instance create` 和 `instance ssh` 会显示 API 返回的实例登录密码，请妥善保管终端输出。
- 删除、关机、重启、重装和改配等操作默认要求确认。

## 开发校验

```bash
ruff check .
ruff format --check .
pytest
```

公开 API 覆盖范围和版本变化见 [CHANGELOG.md](CHANGELOG.md)。
