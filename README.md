# CompShare CLI

在终端管理优云智算 GPU 实例、镜像、云盘、US3 挂载和团队资源。

- 交互式创建实例，实时查询规格、库存和价格
- 支持批量生命周期操作、等待状态和跨地域查询
- 支持可断线恢复的远程任务、状态查询和增量日志读取
- 支持社区/自定义镜像、云盘、团队额度与账单
- 默认中文帮助，可切换英文；所有命令支持 JSON 输出
- 可通过 `compshare ask` 查询产品使用和计费知识
- 可通过 `compshare feedback` 反馈 CLI 问题和建议

## 安装

```bash
pip install compshare-cli
pip install --upgrade compshare-cli
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
# 查询、创建和查看实例
compshare instance search --region cn-sh2 --zone cn-sh2-02
compshare instance create
compshare instance list --all

# 连接实例
compshare instance ssh INSTANCE_ID

# 查看帮助
compshare -h
compshare instance -h
```

## 命令概览

```text
compshare config     API 凭证配置
compshare feedback   反馈 CLI 问题或建议
compshare doctor     配置、鉴权、网络与 SSH 环境诊断
compshare ask        产品使用和计费问答
compshare instance   GPU 实例、规格、库存、价格和生命周期
compshare image      平台、自定义、社区及共享镜像
compshare storage    云盘和 US3 挂载
compshare team       团队、邀请、成员额度、账单和审计
```

## Skill

为 Codex、Claude Code、Cursor 等 AI Agent 安装 CompShare CLI Skill：

```bash
npx skills add compshare-cn/compshare-cli --skill compshare-cli
```

完整说明见 [CompShare CLI Skill](skills/compshare-cli/SKILL.md)。

## SDK

如需通过 SDK 集成 CompShare API，可参考独立的
[CompShare Developer Examples](https://github.com/ucloud/compshare-developer-examples) 仓库。
其中包含 Python、Go、Java、JavaScript 和 PHP 示例，覆盖 API 鉴权、GPU 实例创建、规格配置和状态查询。
