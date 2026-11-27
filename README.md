# CompShare CLI

在终端管理优云智算 GPU 实例、镜像、云盘、US3 / CFS 存储、独享带宽、团队资源和 MiniMax H3 视频、图片、语音任务。

- 交互式创建实例，实时查询规格、库存和价格
- 支持批量生命周期操作、等待状态和跨地域查询
- 支持可断线恢复的远程任务、状态查询和增量日志读取
- 支持社区/自定义镜像、云盘、CFS 文件存储、团队额度与账单
- 支持独享带宽询价、购买、改配、退款预估及实例 EIP 切换
- 支持 MiniMax H3 视频、Qwen-Image 与 MiniMax-H3-Image 图片、IndexTTS 2.5 与 IndexTTS2 语音任务，以及素材上传、视频 Skill 和积分查询
- 默认中文帮助，可切换英文；所有命令支持 JSON 输出

## 安装

```bash
pip install compshare-cli
pip install --upgrade compshare-cli
```

## Skill

为 Codex、Claude Code、Cursor 等 AI Agent 安装 CompShare CLI Skill：

```bash
npx skills add compshare-cn/compshare-cli --skill compshare-cli
```

完整说明见 [CompShare CLI Skill](skills/compshare-cli/SKILL.md)。

## 配置

在控制台的「账户中心 → API 密钥」创建 GPU OpenAPI 公钥和私钥，再运行以下命令。[管理 GPU API 密钥](https://console.compshare.cn/uaccount/api_manage)

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

# 视频、图片和语音任务使用视频工作台的模型 API Key
export COMPSHARE_MINIMAX_API_KEY='sk-ml-...'
```

在视频工作台的左侧「API」入口创建 `sk-ml-` 密钥。[获取工作台 API Key](https://compshare.cn/docs/minimax-h3/api/minimax-h3-video-api#获取-api-key)

## 快速开始

```bash
# 查询、创建和查看实例
compshare instance search --region cn-sh2 --zone cn-sh2-02
compshare instance create
compshare instance list --all

# 连接实例
compshare instance ssh INSTANCE_ID
compshare --json instance ssh INSTANCE_ID -- nvidia-smi
compshare --json instance ssh INSTANCE_ID -- sh -lc 'cd /workspace && pwd'

# MiniMax H3：先预演，再创建
compshare --json minimax create '一只猫在海边奔跑' --dry-run
compshare --json minimax create '一只猫在海边奔跑' --yes
compshare --json minimax points

# 查看帮助
compshare -h
compshare instance -h
```

容器实例可用 `compshare --json instance exec cpod-xxx 'nvidia-smi'` 通过 OpenAPI 提交命令，再用 `compshare --json instance exec-result TASK_ID` 查询结果。[容器命令 OpenAPI](https://compshare.cn/docs/gpus/instance/runcompshareinstancecommand)

生成原生 1080P 视频时，使用 `minimax create --resolution 1080P` 并将 `--duration` 设为 4–15 秒。视频提示词最长 10,000 字符。[H3 视频 API](https://compshare.cn/docs/minimax-h3/api/minimax-h3-video-api)

图片任务可用 `minimax image create --model MiniMax-H3-Image` 选用 H3，语音任务可用 `minimax audio create --model indextts2` 选用 IndexTTS2。[H3 图片 API](https://compshare.cn/docs/minimax-h3/api/minimax-h3-image-api) · [IndexTTS2 API](https://compshare.cn/docs/minimax-h3/api/indextts2-api)

## 命令概览

```text
compshare config     API 凭证配置
compshare doctor     配置、鉴权、网络与 SSH 环境诊断
compshare instance   GPU 实例、规格、库存、价格和生命周期
compshare image      平台、自定义、社区及共享镜像
compshare storage    云盘、US3 挂载和 CFS 文件存储
compshare bandwidth  独享带宽和实例 EIP 带宽归属
compshare minimax    MiniMax H3 视频、图片、语音、Skill 和积分
compshare team       团队、邀请、成员额度、账单和审计
```

## 云存储 Pro（CFS）

通过 `storage cfs` 管理容器可用区的文件存储，支持 50–2048 GiB。`create --dry-run` 会返回购买报价，`attach --dry-run` 会显示挂载计划。

```bash
compshare --json storage cfs list
compshare --json storage cfs create --name training --size 100GiB \
  --region cn-bj2 --zone cn-bj2-03 --dry-run
compshare --json storage cfs attach --instance CPOD_ID --dry-run
```

同可用区没有 CFS 时，`storage cfs attach` 和针对 `cpod-` 实例的 `storage us3 attach` 会自动购买 50 GiB 的月付存储。挂载或卸载可能重启运行中的实例，也可用 `--project` 指定实例所属项目。创建实例时使用 `instance create --cfs` 只关联同可用区已有的 CFS。[云存储 Pro 接口](https://compshare.cn/docs/gpus/data/cfs)

## WorkBuddy Connector

仓库内置符合 WorkBuddy 规范的 `MCP + Skill` Token 连接器，提交目录为
[`connector/compshare`](connector/compshare)。用户在 WorkBuddy 表单中填写 API 公钥和
私钥后，连接器通过本地 stdio MCP 注入凭证，不需要 OAuth，也不会修改已有 CLI 配置。

WorkBuddy 配置固定使用 Python 3.11；本地开发需 Python 3.10 或更高版本，可安装 MCP 可选
依赖并启动服务：

```bash
pip install -e '.[mcp]'
compshare-mcp
```

正式 Connector 使用 `uvx` 从 PyPI 安装固定版本，并将只读、预演和需要明确确认的写操作
分开暴露。MiniMax H3 使用表单中可选的独立模型 API Key。

## Codex Plugin

仓库内置符合 [OpenAI 插件规范](https://developers.openai.com/plugins/build/plugins) 的
Skill 插件，直接复用 `skills/compshare-cli`，通过本地 `compshare` 命令管理资源。
先安装 CLI 并按「配置」说明设置凭证，再在仓库根目录执行：

```bash
codex plugin marketplace add .
codex plugin add compshare-cli@compshare
codex plugin list --marketplace compshare --json
```

也可以从任意目录通过 GitHub 安装：

```bash
codex plugin marketplace add compshare-cn/compshare-cli
codex plugin add compshare-cli@compshare
```

## SDK

如需通过 SDK 集成 CompShare API，可参考独立的
[CompShare Developer Examples](https://github.com/ucloud/compshare-developer-examples) 仓库。
其中包含 Python、Go、Java、JavaScript 和 PHP 示例，覆盖 API 鉴权、GPU 实例创建、规格配置和状态查询。
