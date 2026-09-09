---
name: compshare
description: Manage CompShare GPU cloud resources and MiniMax H3 tasks through the controlled CompShare MCP bridge.
description_zh: 通过受控 CompShare MCP 桥接查询和管理优云智算 GPU 云资源及 MiniMax H3 任务。
description_en: Manage CompShare GPU cloud resources and MiniMax H3 tasks through the controlled CompShare MCP bridge.
version: "0.4.4"
author: "CompShare"
---

# CompShare 优云智算

通过本 Connector 提供的 MCP 工具查询和管理 GPU 实例、镜像、云盘、US3、独享带宽、
团队资源与 MiniMax H3 视频任务。凭证由 WorkBuddy Token 表单注入；不要要求用户在对话中
发送公钥、私钥或模型 API Key。

本 Connector 不提供产品知识库问答。用户询问产品文档或政策时，不要猜测，也不要尝试调用
已移除的 `ask` 命令。

## 总规则

1. 每个新会话先调用 `compshare_status`，确认 `ok: true`、CLI 版本和 API 连通性。
2. 参数或命令不确定时先调用 `compshare_help`，不要猜测当前 CLI 的选项、枚举或位置参数。
3. 查询、结构化帮助、`--dry-run` 和 `--print` 只调用 `compshare_read`。
4. 创建、付费、修改、删除、远程执行和文件传输只调用 `compshare_write`。
5. 调用写工具前，向用户展示准确对象、参数、价格或影响，并取得本次明确同意。参数变化后
   旧确认失效，必须重新确认。
6. 删除、重装、缩容相关操作和磁盘数据处置属于高风险操作。说明不可逆影响，并在读取当前
   资源后再确认。
7. 写操作只执行一次。超时或连接中断时结果可能已经生效；先查询资源状态，禁止直接重试。
8. 不使用 `--show-sensitive`，不展示密码、IP、访问 URL、登录命令或任何 Token。需要连接
   实例时，优先让连接器直接执行用户批准的远程命令。
9. 列表默认可能分页。需要全集时使用 `--all`，或根据 `meta.total`、`meta.returned`、
   `meta.offset` 继续读取，不能把第一页当作全部。

## MCP 工具

### `compshare_status`

检查 WorkBuddy 是否注入 GPU API 公钥/私钥、当前 CLI 版本和 API 连通性。`minimaxApiKey`
为 `false` 只影响 MiniMax H3，不影响 GPU 资源。认证失败时，让用户在 Connector 设置中更新
凭证；不要改用 `compshare config`，也不要索取聊天中的明文密钥。

```json
{"timeout_seconds": 30}
```

### `compshare_help`

读取 CLI 的结构化真源帮助。`command` 是零到三个命令名，不包含开头的 `compshare`；
空数组读取根帮助。

```json
{"command": ["instance", "create"]}
```

重点读取 `result.data.command_path`、`result.data.parameters` 和 `result.data.commands`。

### `compshare_read`

执行白名单内的只读命令、安全预演或仅打印操作。`args` 是 CLI 参数数组，不包含开头的
`compshare`，也不要加入 `--json`。默认超时 30 秒，最长 900 秒。

```json
{"args": ["instance", "list", "--all"], "timeout_seconds": 30}
```

对原本会写入的命令，只有受支持的 `--dry-run` 或 `--print` 形式才会被只读工具接受。

### `compshare_write`

执行白名单内的写入、付费、远程命令或文件传输。调用前必须已取得真实用户确认；字段本身
不能替代确认。

```json
{
  "args": ["instance", "stop", "uhost-example", "--yes", "--timeout", "600"],
  "user_confirmed": true,
  "confirmation_summary": "用户确认停止 uhost-example，并了解运行任务会中断",
  "timeout_seconds": 660
}
```

CLI 本身要求确认的操作仍需在 `args` 中加入 `--yes`。若返回 `outcome: "unknown"`，按
`error.action: "check_existing"` 读取资源状态，不要重放写命令。

## 返回值

成功执行的桥接响应包含：

```json
{
  "ok": true,
  "exitCode": 0,
  "result": {
    "ok": true,
    "schema_version": "1",
    "data": {},
    "meta": {}
  }
}
```

同时检查桥接层 `ok`、`exitCode` 和 CLI `result.ok`。CLI 失败时，读取
`result.error.code`、`result.error.message` 和可选的 `result.error.details`。空 `items` 是
有效结果，不等于工具故障。

## 查询与创建实例

先查询可用区、镜像与真实库存：

```jsonl
{"args":["instance","zones"]}
{"args":["image","list","--source","platform","--region","cn-sh2","--zone","cn-sh2-02","--all"]}
{"args":["instance","search","--region","cn-sh2","--zone","cn-sh2-02","--gpu","4090","--image","IMAGE_ID","--available"]}
```

`instance search` 只有带 `--image` 时才检查真实库存。创建前必须通过只读工具调用
`instance create --dry-run`，展示选中的规格、库存、价格和请求参数。用户确认后，使用完全
相同的参数移除 `--dry-run`，加入 `--yes`，再调用写工具。不要在没有用户给定价格保护时
自行猜测 `--max-price`。

JSON 创建至少提供 GPU、每实例 GPU 数、CPU、内存、镜像、Region 和 Zone；不要触发交互
向导。创建超时后先 `instance list/show`，按幂等标识或创建时间核对，不能立即再次购买。

## 实例生命周期和远程任务

列表、详情、价格、账单、退款预估和等待状态使用只读工具。启动、停止、重启、删除、改名、
密码重置、重装、改配、计费变更、端口和定时关机变更使用写工具。

远程同步命令必须放在 `--` 后，并按写操作确认：

```json
{
  "args": ["instance", "ssh", "INSTANCE_ID", "--", "nvidia-smi"],
  "user_confirmed": true,
  "confirmation_summary": "用户确认在 INSTANCE_ID 上执行只读的 nvidia-smi",
  "timeout_seconds": 60
}
```

交互式 SSH 不受 MCP 支持。需要长时间运行的安装、训练或编译任务时，用
`instance job submit`，不要用同步 SSH。提交后通过 `job show` 或短轮询读取状态；日志使用
`job logs --tail` 或字节偏移读取，禁止 `--follow`。等待超时不会取消远程任务。

文件传输使用 `instance cp`，实例路径以 `:` 开头。它会读写 WorkBuddy 可访问的本地路径，
调用前必须确认源、目标和覆盖影响。

## 镜像、存储、带宽和团队

- 镜像 `list/show/progress/shares/tags` 为只读；`create/update/delete/share/unshare/publish`、
  收藏变更为写操作。发布社区镜像前确认其中不含密钥、密码或用户数据。
- 云盘 `list/price` 为只读；创建、挂载、卸载、扩容和删除为写操作。卸载前提醒用户先在
  实例内卸载文件系统；云盘只能扩容，不能缩容。
- 独享带宽 `list/instances` 为只读。购买、改配和删除先通过 `--dry-run` 询价或查看退款，
  再确认执行。购买后已有实例不会自动切换带宽。
- 团队列表、详情、成员、账单和审计为只读；团队、邀请、成员备注和额度变更为写操作。
  账单 CSV 导出不通过 MCP 提供；改为读取分页后的结构化账单数据。

## MiniMax H3

MiniMax 使用 Token 表单中的独立 `COMPSHARE_MINIMAX_API_KEY`。缺失时让用户编辑 Connector
凭证，不要把 GPU API 私钥当作模型 Key。

创建前先读取积分、套餐、已有任务，再通过只读工具调用 `minimax create --dry-run`。展示
分辨率、时长、比例、素材 URL 和费用影响后确认，使用相同幂等键调用写工具正式创建。
重试不确定请求时必须复用原幂等键。取消未完成任务也属于写操作。

所有图片、视频和音频输入必须是公开可访问 URL。生成视频 URL 默认脱敏；不要为了显示它
而绕过连接器的敏感输出限制。

## 故障恢复

- `authentication` 或 `configuration_error`：让用户在 WorkBuddy Connector 设置中更新两把
  GPU API 密钥；MiniMax 单独检查可选模型 Key。
- `invalid_usage`：调用 `compshare_help` 核对参数、位置和枚举后再试。
- 无库存：带准确镜像重新搜索，并有意识地放宽 GPU、Region、Zone、CPU、内存、计费或
  磁盘条件。
- 读取超时：可以在等待后有限重试；写入超时：先读回，绝不直接重试。
- 返回部分失败：逐项报告成功与失败对象，只对明确未执行且用户重新确认的对象继续操作。
