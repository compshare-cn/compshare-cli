# Changelog

## 0.3.0

- `instance ssh` 默认自动填写 API 返回的登录密码，并提供 `--no-auto-password` 手动输入开关。
- 修正 `instance ssh` 和 `instance scp` 将 API 的 Base64 密码字段误当作明文密码的问题。
- 自动 SSH 登录现在接受首次出现的主机密钥，同时继续拒绝已记录主机的密钥变更。
- `instance ssh INSTANCE_ID -- COMMAND` 支持自动认证后非交互执行远程命令并透传退出码。
- 增加 `instance scp INSTANCE_ID LOCAL_PATH REMOTE_PATH`，支持自动认证上传文件及递归上传目录。
- 增加 `compshare ask QUESTION` 产品问答命令，支持引用来源和完整 JSON 响应。
- 增加 `compshare feedback bug|suggest MESSAGE`，直接向 Insights 服务提交分类反馈。
- 增加只包含指令名称、CLI 版本、操作系统和发生时间的异步使用统计。
- 移除全局默认 Region/Zone；资源位置仅使用请求参数或 API 响应，生命周期操作不再混用查询地域与实例实际可用区。
- 创建实例时的镜像选择支持完整 API 分页，并使用 `f`/`b` 前后翻页，不再因匹配超过 50 项而中止。
- 地域型镜像、网络、模型和软件接口会在 CLI 层要求其必需的 Region/Zone，全局接口不再携带无意义的地域参数。
- 默认递归隐藏密码、IP、访问 URL、令牌和登录命令；新增全局 `--show-sensitive` 以显式显示原始敏感字段。

## 0.2.1

- 兼容 API 将空列表返回为 `null` 的情况，空结果不再导致命令异常。
- 凭证配置改用权限受限的唯一临时文件原子写入，并清理写入失败的临时文件。
- 损坏的凭证配置和空配置名称现在会返回明确的 CLI 错误。
- 分页兼容 `TotalCount` 和 `Total` 两种总数字段。
- 非 UTF-8 镜像 README 文件现在会返回可读错误。

## 0.2.0

- 覆盖团队、邀请、成员额度、团队账单和操作日志的 17 个公开 Action。
- 支持批量启动、停止、重启、删除实例，并提供独立的 `instance wait`。
- 修正跨地域实例聚合后的筛选和分页语义，实例与镜像列表支持 `--all`。
- 增加只读的 `doctor` 环境诊断。
- 增加 `instance create --max-price` 价格保护。
- 最低运行版本继续保持 Python 3.9。

## 0.1.3

- 兼容新版 Typer 与 Click，直接运行 `compshare` 时显示帮助。

## 0.1.0

- 首次公开版本，支持 GPU 实例、实例镜像、云盘和 US3 挂载。
