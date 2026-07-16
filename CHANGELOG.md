# Changelog

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
