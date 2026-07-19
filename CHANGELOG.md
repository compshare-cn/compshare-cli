# Changelog

## Unreleased

## 0.3.5

- 精简 README 的安装和快速开始内容，新增 CompShare SDK 多语言示例入口。
- 新增可通过 `npx skills` 安装的 CompShare CLI Agent Skill，覆盖实例、镜像、存储、团队、
  SSH、文件传输和远程任务等主要工作流。
- 发布版本校验不再依赖 README 中的硬编码版本号，并修正发布文档中的版本更新位置。

## 0.3.4

- 统一 JSON 顶层契约为 `ok/schema_version/data/meta/error`：错误提供稳定代码，列表使用精简的
  `data.items` 和一致分页元数据，脱敏时返回字段路径；`--json --version` 与 `--json --help`
  也输出 JSON。实例聚焦查询保留资源身份，并为缺失集合返回空数组。
- `--json`、`--profile` 和 `--show-sensitive` 支持出现在常见的子命令参数位置；参数预解析
  不会跨越 `--`，避免截取远程命令的同名参数。
- `config list` 明确显示凭证来自配置文件、环境变量或混合来源；仅使用环境变量时不再把空的
  `default` profile 显示为当前凭证。
- 包版本改为由 `compshare_cli.__version__` 生成，并在发布前统一校验构建元数据、运行时版本、
  README 和 Changelog。
- 移除用途有限的 `--show-completion`，保留 `--install-completion` 自动安装命令补全。
- 增加 `instance schedule show` 定时关机查询和 `instance schedule extend --by` 延期能力；
  延期以原计划为基准，并在更新后重新查询验证。
- 增加纯客户端的 `instance job` 持久化远程任务管理，支持提交、列表、详情、双路日志及字节
  偏移、等待、取消和历史清理；任务使用远端 XDG state 目录，可在本地终端或网络断开后继续
  运行。

## 0.3.3

- 将语言设置从 `lang` 子命令调整为全局 `--lang zh|en` 选项，并将 `feedback` 在根命令
  帮助中的位置调整到 `config` 与 `doctor` 之间。
- 增加 `instance cp` 双向复制；使用 `:/path` 标记实例路径，支持本地与实例之间自动认证、
  自动递归的上传和下载，并保留原有 `instance scp` 上传语法兼容性。
- `--json instance scp` 现在会真实上传，并返回结构化执行结果；`--print` 保持为仅预览。
- JSON 模式不再启动凭证或危险操作确认提示；需要确认的操作必须显式传入 `--yes`。
- 交互确认在空输入或无效输入时最多重试三次。
- 增加标准 `--version` 选项，并改进全局 `--json` 位置错误提示。
- 实例列表按地域筛选时要求同时指定 `--region` 和 `--zone`，确保调用正确的 Zone 接口。
- `instance show` 显示实例软件入口；URL 默认脱敏，使用 `--show-sensitive` 后显示。
- `instance show` 支持按 IP、软件、规格、磁盘、计费、镜像和状态分组聚焦输出，并允许组合查询。
- 增加纯客户端的实例配置模板；支持本地创建、列表、查看、删除，以及通过
  `instance create --template NAME` 加载并用显式参数覆盖模板值。
- 移除当前不可用的 `instance monitor` 和独立 `instance software url` 命令。
- 修正云盘列表误用实例接口的问题，改用 `DescribeCompshareDisk` 并完整显示
  `ResourceId`；已卸载云盘也可被自动定位。
- 镜像收藏迁移到 `Create/DeleteCompShareImageFavorite`，使用社区镜像 `GroupId`；平台镜像
  列表按类型执行正确的全局分页。
- 放宽镜像列表、网络检测、软件端口和模型查询中接口不需要的 Region/Zone 限制。
- 修正团队账单排序字段/方向的接口值，并让欠费汇总沿用列表的时间范围。
- 开放 Typer 内置的 Bash、Zsh、Fish 和 PowerShell 命令补全安装选项。

## 0.3.2

- JSON 模式远程命令返回结构化的退出码、标准输出、标准错误及连接/认证错误，不再只打印 SSH 命令。
- 实例创建默认等待到 `Running`，SSH 连接也会先等待实例运行，避免把创建接口成功误判为实例已就绪。
- `--json` 固定输出 UTF-8 字节，不再受 Windows GBK 活动代码页影响。
- `instance ssh` 增加按 profile 和实例隔离的一小时连接信息缓存，减少重复的实例查询。

## 0.3.1

- 补充 Windows PowerShell 虚拟环境的激活与未激活调用示例，说明 `&`、`.\` 和路径引号的使用条件。
- `doctor` 在 Windows 上不再将无效的 POSIX 权限位当作配置泄露，改为提示由 Windows ACL 管理权限。
- Windows 上的交互式 `instance ssh` 使用 OpenSSH askpass 自动填写 API 返回的密码，不再降级为手动输入。

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
