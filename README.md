# CompShare CLI

在终端管理优云智算 GPU 实例、镜像、云盘、US3 挂载和团队资源。

- 交互式创建实例，实时查询规格、库存和价格
- 支持批量生命周期操作、等待状态和跨地域查询
- 支持可断线恢复的远程任务、状态查询和增量日志读取
- 支持社区/自定义镜像、云盘、团队额度与账单
- 默认中文帮助，可切换英文；所有命令支持 JSON 输出
- 可通过 `compshare ask` 查询产品使用和计费知识
- 可通过 `compshare feedback` 反馈 CLI 问题和建议
- 基于官方 [`ucloud-sdk-python3`](https://github.com/ucloud/ucloud-sdk-python3)

当前版本：`0.3.4`，要求 Python 3.9 或更高版本。

## 安装

```bash
pip install compshare-cli
compshare -h
compshare --version
```

本地开发：

```bash
git clone https://github.com/BennielAllan/compshare-cli.git
cd compshare-cli
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Windows PowerShell 中可先激活虚拟环境，再直接调用 `compshare`：

```powershell
.\.venv\Scripts\Activate.ps1
compshare -h
compshare config --name default
```

不激活虚拟环境时，使用 PowerShell 调用运算符 `&` 直接执行虚拟环境内的入口：

```powershell
& '.\.venv\Scripts\compshare.exe' -h
& '.\.venv\Scripts\compshare.exe' config --name default
```

PowerShell 会把单引号中的路径解析为字符串，所以带参数执行时不能省略 `&`。路径包含空格时必须保留引号；从当前目录运行可执行文件时要使用 `.\` 前缀。若 `Activate.ps1` 被本机执行策略拦截，可直接使用上述不激活的写法，无需修改系统策略。

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

`config list` 会明确标注当前凭证来自配置文件、环境变量或两者混合；JSON 输出还会分别说明
公钥和私钥的来源，但不会显示凭证内容。

也可以使用环境变量：

```bash
export COMPSHARE_PUBLIC_KEY='...'
export COMPSHARE_PRIVATE_KEY='...'
```

## 快速开始

```bash
# 查规格、库存和实例
compshare instance search --region cn-sh2 --zone cn-sh2-02
compshare instance search --region cn-sh2 --zone cn-sh2-02 \
  --gpu 4090 --image IMAGE_ID --available
compshare instance list --all

# 聚焦查看实例信息；多个分组可组合
compshare instance show INSTANCE_ID --ip --softwares
compshare instance show INSTANCE_ID --spec --disks --billing
compshare instance show INSTANCE_ID --image --status

# 交互式创建
compshare instance create

# 批量操作与等待
compshare instance stop INSTANCE_1 INSTANCE_2
compshare instance start INSTANCE_1 INSTANCE_2
compshare instance wait INSTANCE_1 INSTANCE_2 --state Running

# 设置、查询和延期定时关机
compshare instance schedule set INSTANCE_ID --at 2h
compshare instance schedule show INSTANCE_ID
compshare instance schedule extend INSTANCE_ID --by 1h

# SSH
compshare instance ssh INSTANCE_ID
# 默认自动填写 API 返回的密码；需要手动输入时可关闭
compshare instance ssh INSTANCE_ID --no-auto-password
# 自动登录后执行远程命令；远程参数用 -- 与 CLI 选项分隔
compshare instance ssh INSTANCE_ID -- nvidia-smi --query-gpu=name
compshare instance ssh INSTANCE_ID -- 'cd /workspace && python train.py'
# Agent/脚本：在统一 JSON 契约的 data 中返回 phase、exit_code、stdout、stderr
compshare --json instance ssh INSTANCE_ID -- nvidia-smi
# 强制刷新或禁用本地 SSH 连接缓存
compshare instance ssh INSTANCE_ID --refresh
compshare instance ssh INSTANCE_ID --no-cache
# 在本地与实例间双向复制；实例路径以 : 开头，目录会自动递归复制
compshare instance cp INSTANCE_ID ./model.bin :/workspace/model.bin
compshare instance cp INSTANCE_ID ./dataset :/workspace/dataset
compshare instance cp INSTANCE_ID :/workspace/result ./result

# 长时间运行的远程任务；提交后立即返回 Job ID
compshare instance job submit INSTANCE_ID --name build --cwd /workspace/project -- make -j8
compshare instance job show INSTANCE_ID JOB_ID
compshare instance job logs INSTANCE_ID JOB_ID --follow
compshare instance job wait INSTANCE_ID JOB_ID --timeout 300

# 产品问答
compshare ask "按量实例关机以后，云硬盘还收费吗？"
```

自动化创建示例：

```bash
compshare instance create \
  --region cn-sh2 \
  --zone cn-sh2-02 \
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

本地实例模板可以保存常用创建参数，不依赖控制台或后端模板接口：

```bash
compshare instance template create training-4090 \
  --description '4090 训练环境' \
  --gpu 4090 \
  --count 1 \
  --cpu 16 \
  --memory 64GiB \
  --image IMAGE_ID \
  --region cn-sh2 \
  --zone cn-sh2-02 \
  --disk 100GiB \
  --charge Postpay

compshare instance template list
compshare instance template show training-4090
compshare instance create --template training-4090 --yes

# 本次显式参数优先于模板值
compshare instance create --template training-4090 --cpu 32 --memory 128GiB --yes
```

模板存放在 `~/.config/compshare/instance-templates.json`；可用
`compshare instance template path` 查看实际路径。模板只保存实例创建参数，不保存 API
凭证、`--yes`、`--show-sensitive` 或其他执行控制选项。

## 远程任务

`instance ssh INSTANCE_ID -- COMMAND` 适合需要同步获取结果的短命令。安装、编译和计算等
长任务可通过 `instance job` 在实例上脱离 SSH 运行，本地终端关闭或网络中断不会终止任务：

```bash
# 普通命令及参数会被安全转义
compshare instance job submit INSTANCE_ID \
  --name training \
  --cwd /workspace/project \
  -- python train.py --epochs 100

# 管道、重定向等 Shell 语法应显式使用 sh -lc
compshare instance job submit INSTANCE_ID --name install -- \
  sh -lc 'apt-get update && apt-get install -y ffmpeg'

compshare instance job list INSTANCE_ID
compshare instance job show INSTANCE_ID JOB_ID
compshare instance job logs INSTANCE_ID JOB_ID --tail 200
compshare instance job logs INSTANCE_ID JOB_ID --follow
compshare instance job wait INSTANCE_ID JOB_ID --timeout 300
compshare instance job cancel INSTANCE_ID JOB_ID --yes
compshare instance job prune INSTANCE_ID --older-than 7d --yes
```

Agent 可按字节偏移增量读取 stdout 和 stderr；响应中的 `StdoutNextOffset`、
`StderrNextOffset` 可直接用于下一次请求：

```bash
compshare --json instance job logs INSTANCE_ID JOB_ID \
  --stdout-offset 0 --stderr-offset 0 --limit 65536
```

任务记录遵循 XDG Base Directory 规范，保存在实例 SSH 用户的
`${XDG_STATE_HOME:-$HOME/.local/state}/compshare/jobs/JOB_ID/`。目录权限为 `0700`，文件权限为
`0600`。任务可以抵抗本地断线，但实例关机或重启会将未完成任务标记为 `Interrupted`；实例重装
或删除会移除系统盘上的任务记录和日志，重要产物应写入数据盘或共享存储。

## 功能入口

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

## 产品问答

```bash
compshare ask "按量实例关机以后，云硬盘还收费吗？"
compshare --json ask "如何创建自定义镜像？"
```

普通输出显示答案和引用资料标题；`--json` 返回完整的答案、引用、请求 ID 和检索元数据。
命令只向内置问答服务发送 `question` 字段，不会附带 API 凭证、配置文件或其他命令上下文。

## 反馈

```bash
compshare feedback bug "创建实例时发生错误"
compshare feedback suggest "希望支持保存默认创建规格"
```

反馈会直接发送到内置的 CompShare Insights 服务地址。开发环境可使用
`COMPSHARE_INSIGHTS_URL=http://127.0.0.1:18080` 覆盖服务地址。

CLI 会异步统计指令使用情况，且仅发送指令名称、CLI 版本、操作系统和发生时间；不会发送
命令参数、凭证、资源 ID 或命令输出。

查看完整命令和参数：

```bash
compshare -h
compshare instance -h
compshare instance create -h
```

## 命令补全

CLI 支持 Bash、Zsh、Fish 和 PowerShell 命令补全。为当前 Shell 自动安装：

```bash
compshare --install-completion
```

## 脚本调用

`--json`、`--profile` 和 `--show-sensitive` 可以放在命令前，也可以放在常见的子命令参数位置；
`--` 之后的同名参数始终原样传给远程命令：

```bash
compshare --json instance list --status Running --all
compshare image list --source community --profile production
compshare instance show uhost-xxxxxxxx --json --show-sensitive
```

JSON 模式不会启动交互向导。生命周期操作可使用 `--wait`、`--no-wait` 和
`--timeout` 控制等待行为；部分批量操作失败时，CLI 返回非零退出码。默认输出会递归隐藏
密码、IP、访问 URL 和登录命令；只有显式指定 `--show-sensitive` 才会输出原值。
`instance show` 可使用 `--ip`、`--softwares`、`--spec`、`--disks`、`--billing`、
`--image` 和 `--status` 聚焦输出一个或多个信息分组；不传这些选项时保持完整摘要。

所有 JSON 命令只输出一个 UTF-8 文档，并使用相同的顶层契约。成功响应如下：

```json
{
  "ok": true,
  "schema_version": "1",
  "data": {"version": "0.3.4"}
}
```

错误响应中的 `code` 稳定且不受语言设置影响，适合 Agent 分支判断；`message` 用于显示，
接口错误的 Action、RetCode 和请求 ID 放在 `details` 中：

```json
{
  "ok": false,
  "schema_version": "1",
  "error": {
    "code": "api_error",
    "message": "...",
    "details": {
      "action": "DescribeCompShareInstance",
      "ret_code": 171,
      "request_uuid": "..."
    }
  }
}
```

列表响应使用 `data.items`，总数、过滤数、偏移量和是否返回全部结果位于 `meta`；列表只返回
表格对应的摘要字段，完整 README、镜像详情和实例详情应通过相应的 `show` 命令读取。
API 的 Action、RetCode 和请求 ID 也会移到 `meta`。发生默认脱敏时，
`meta.redacted_fields` 会列出被替换为 `***` 的 JSON 路径。业务字段本身仍沿用 API 返回的名称、
类型和单位，本版本不做语义转换。

`--json --version` 和 `--json --help` 同样遵循上述契约；JSON 帮助直接返回命令、参数和子命令
结构，不输出 Rich 终端表格。

Region 和 Zone 是资源参数，放在对应子命令后：

```bash
compshare instance list --region cn-sh2 --zone cn-sh2-02
compshare instance create --region cn-sh2 --zone cn-sh2-02
compshare image list --source custom
compshare storage disk list
```

镜像列表、网络检测和软件端口列表可进行全局查询，Region/Zone 只是可选过滤条件。CLI
不保存或自动注入默认 Region/Zone；确实依赖地域的资源操作仍需显式传入。按实例 ID
执行的生命周期操作使用 `DescribeCompShareInstance` 响应中的 Region 和 Zone；响应缺少任一
字段时会停止操作，不会从 Zone 推导或用请求 Region 补齐。

## 语言

```bash
compshare --lang en --help
compshare --lang zh --help
```

`--lang` 会保存所选语言，后续命令继续使用；也可以通过 `COMPSHARE_LANG=en` 临时覆盖。

## 安全说明

- 配置目录和文件分别使用 `0700`、`0600` 权限。
- 本地实例模板文件同样使用 `0600` 权限，所在目录使用 `0700` 权限。
- API 私钥不会出现在命令输出中。
- 默认使用 `***` 隐藏密码、私钥、IP、访问 URL、令牌和登录命令，包括嵌套 JSON 字段。
- `instance ssh` 在支持的交互式终端中通过伪终端自动填写登录密码，不会打印密码或将其放入进程参数。
- 自动登录会接受首次出现的 SSH 主机密钥；已记录主机的密钥发生变化时仍会拒绝连接。
- `instance ssh INSTANCE_ID -- COMMAND` 可非交互执行远程命令，透传命令输出和退出码。
- `instance job submit` 使用 `nohup` 和独立进程会话在远端运行长任务，任务状态和日志不依赖
  本地 CLI 进程；取消任务和清理历史记录需要显式确认。
- `--json instance ssh INSTANCE_ID -- COMMAND` 会真实执行命令；成功信息位于 `data`，连接或认证失败使用统一的 `error` 对象。
- `--json` 始终以 UTF-8 字节输出，不依赖 Windows 活动代码页或终端编码。
- `instance ssh` 默认将 API 返回的 SSH 命令和密码按 profile/实例缓存 1 小时；Windows 使用当前用户的 DPAPI 加密密码，其他平台将缓存文件权限限制为当前用户。可用 `--refresh` 强制更新、`--no-cache` 禁用；重置密码和重装实例会清除对应缓存。
- 实例创建是异步操作；`instance create` 默认等待到 `Running`，显式使用 `--no-wait` 才会在创建接口返回后立即退出。`instance ssh` 也会默认等待实例运行后再连接。
- `instance cp INSTANCE_ID SOURCE DESTINATION` 可自动认证并双向复制文件或目录；实例侧路径
  使用 `:/path` 表示。旧的 `instance scp INSTANCE_ID LOCAL_PATH REMOTE_PATH` 上传语法继续兼容。
- `--json instance cp ...` 会真实执行复制，并在统一契约中返回 `phase`、`exit_code`、
  `stdout` 和 `stderr`；只有显式使用 `--print` 才仅输出命令。
- `--show-sensitive` 会恢复这些字段的原始值；请勿在共享终端、CI 日志或 Agent 会话中使用。
- 删除、关机、重启、重装和改配等操作默认要求输入 `y` 或 `n` 确认；空输入或无效输入
  最多重试三次。JSON 模式不启动确认提示，执行这类操作必须显式使用 `--yes`。

## 开发校验

```bash
ruff check .
ruff format --check .
pytest
```

公开 API 覆盖范围和版本变化见 [CHANGELOG.md](CHANGELOG.md)，维护者发布流程见
[RELEASING.md](RELEASING.md)。
