# mail agent

mail agent 是一个本地运行的只读邮件分析 MCP Server，用于让 Codex 读取邮箱中的邮件线程，并辅助分析一封邮件或完整邮件线程里不同人员提出的需求、问题、待确认事项，最后整理“应该回复谁、回复哪些点”。

第一版适配网易企业邮箱 IMAP。

## 项目目标

第一版 MVP 只做一条链路：

邮箱 IMAP 只读读取 -> 搜索邮件 -> 读取单封邮件 -> 尽量重建完整邮件线程 -> 输出稳定 thread JSON -> 交给 Codex 根据固定 prompt 做邮件需求拆解。

同时支持读取收件箱和已发送目录，用于判断收件箱邮件是否已经回复、回复过几次，以及命中的已发送邮件是什么。

它不是完整邮箱客户端，也不是自动回复系统。

## 第一版交付形态

第一版的正式交付物是本地只读 MCP Server，供 Codex 调用邮箱读取和线程分析能力。

CLI 是随项目提供的调试和运维入口，用于测试连接、发现邮箱目录、检查搜索结果和排查问题；日常分析流程建议通过 MCP 在 Codex 中调用。

## 安全边界

- 第一版只读，不实现 SMTP。
- 不允许发送邮件。
- 不允许删除邮件。
- 不允许移动、归档邮件。
- 不允许标记已读/未读。
- 不默认下载附件内容，只读取附件文件名、大小、MIME type、Content-ID 等元信息。
- 邮箱账号、密码、授权码、API Key 不写死在代码里，必须通过环境变量或 `.env` 配置。
- README、测试、日志和示例输出不包含真实邮箱信息。
- 日志不打印完整邮件正文，最多打印 message id、subject、from、date 等调试信息。
- 第一版只支持单用户本地运行，不做多用户系统、不做 Web UI、不做数据库。

## 安装方式

建议使用虚拟环境：

```bash
cd /path/to/mail-agent
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[test]"
```

当前项目已迁移到 Python 3.14 环境；本地 `.venv/bin/python` 应输出 `Python 3.14.x`。

## .env 配置说明

复制示例文件：

```bash
cp .env.example .env
```

填写：

```bash
NETEASE_EMAIL_ADDRESS=
NETEASE_EMAIL_USERNAME=
NETEASE_EMAIL_PASSWORD=
NETEASE_IMAP_HOST=imap.qiye.163.com
NETEASE_IMAP_PORT=993
NETEASE_IMAP_SSL=true
EMAIL_SEARCH_DEFAULT_DAYS=30
EMAIL_THREAD_LOOKBACK_DAYS=90
NETEASE_INBOX_MAILBOX=INBOX
NETEASE_SENT_MAILBOX=Sent
LOG_LEVEL=INFO
```

说明：

- `NETEASE_EMAIL_USERNAME` 通常是完整邮箱地址，也可能取决于企业邮箱管理员配置。
- `NETEASE_EMAIL_PASSWORD` 建议使用客户端授权码或企业邮箱允许的客户端密码。
- 国内 IMAP 默认使用 `imap.qiye.163.com:993`。
- 海外环境可改为 `hwimap.qiye.163.com:993`。
- `NETEASE_INBOX_MAILBOX` 默认是 `INBOX`。
- `NETEASE_SENT_MAILBOX` 需要按真实 IMAP 目录填写；建议先运行 `list-mailboxes`，使用返回的 `select_name`。
- 不要把真实 `.env` 提交到 git。

## CLI 使用方式

测试 IMAP 连接：

```bash
mail-agent test-connection
```

列出邮箱目录：

```bash
mail-agent list-mailboxes
```

输出里：

- `name` 是给人看的目录名。
- `select_name` 是传给 `--mailbox`、`--sent-mailbox` 或 `.env` 的真实 IMAP 目录名。
- `role` 会尽量标识 `inbox`、`sent`、`drafts`、`trash`、`junk`。

搜索邮件：

```bash
mail-agent search --from customer@example.com --subject "CES" --limit 10
```

读取单封邮件：

```bash
mail-agent read --email-id "12345"
```

拉取完整线程：

```bash
mail-agent thread --email-id "12345" --output thread.json
```

判断收件箱邮件是否已经回复：

```bash
mail-agent reply-status --since 2026-06-01 --limit 50 --output reply-status.json
```

如果已发送目录不是 `Sent`，先用 `list-mailboxes` 找到已发送目录的 `select_name`，然后：

```bash
mail-agent reply-status --sent-mailbox "&XfJT0ZAB-" --since 2026-06-01
```

输出固定分析 prompt：

```bash
mail-agent print-prompt
```

## Codex MCP 配置方式

配置示例在：

```text
examples/codex_config.example.toml
```

示例：

```toml
[mcp_servers.mail_agent]
command = "python"
args = ["-m", "netease_mail_mcp.mcp_server"]
cwd = "/path/to/mail-agent"
startup_timeout_sec = 20
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
enabled_tools = ["list_mailboxes", "search_email", "read_email", "get_full_thread", "get_inbox_reply_status", "extract_reply_tasks"]
```

如果使用虚拟环境，可以把 `command` 改为：

```toml
command = "/path/to/mail-agent/.venv/bin/python"
```

配置可以通过项目根目录 `.env` 加载，也可以在启动 Codex 前通过 shell 环境变量注入。

## 如何在 Codex 中使用

典型流程：

1. 首次使用先调用 `list_mailboxes`，确认收件箱和已发送目录的 `select_name`。
2. 调用 `search_email` 搜索客户、主题或关键词。
3. 从结果中选择目标 `email_id`。
4. 调用 `get_full_thread` 拉取线程 JSON。
5. 调用 `extract_reply_tasks` 获取固定分析 prompt。
6. 让 Codex 基于 thread JSON 和 prompt 输出“应该回复谁、回复哪些点”。

判断是否已回复的典型流程：

1. 调用 `list_mailboxes` 找到已发送目录。
2. 调用 `get_inbox_reply_status`，它会读取收件箱和已发送目录。
3. 查看每封收件箱邮件的 `replied`、`reply_count`、`latest_reply_date` 和 `replies`。

回复状态判断优先使用 `Message-ID`、`In-Reply-To`、`References` 这些邮件标准头；如果头信息缺失，会退回到“同主题 + 已发送收件人包含原发件人 + 时间在原邮件之后”的弱规则，并在 `warnings` 中提示需要人工复核。

## MCP Tools

### list_mailboxes

列出邮箱目录，返回展示名、IMAP `select_name`、目录分隔符、flags 和推断 role。

### search_email

按关键词、发件人、主题、日期范围搜索邮件。默认不返回完整正文。

参数：

- `query`
- `from_email`
- `subject`
- `since`
- `before`
- `mailbox`
- `limit`

### read_email

读取单封邮件的结构化内容。

参数：

- `email_id`
- `mailbox`
- `include_body`
- `include_attachment_metadata`

### get_full_thread

根据一封邮件尽量拉取完整邮件线程，并按时间升序输出稳定 JSON。

参数：

- `email_id`
- `mailbox`
- `lookback_days`
- `include_attachment_metadata`

### get_inbox_reply_status

读取收件箱和已发送目录，判断收件箱邮件是否已经回复。

参数：

- `inbox_mailbox`
- `sent_mailbox`
- `query`
- `from_email`
- `subject`
- `since`
- `before`
- `sent_since`
- `sent_before`
- `limit`
- `sent_scan_limit`

核心输出：

- `checked_count`：检查了多少封收件箱邮件。
- `replied_count`：其中多少封已回复。
- `unreplied_count`：其中多少封未识别到回复。
- `items[].replied`：单封邮件是否已回复。
- `items[].reply_count`：识别到的回复次数。
- `items[].replies`：命中的已发送邮件列表。

### extract_reply_tasks

第一版不调用外部 LLM API，只返回固定分析 prompt、thread 摘要和结构化输出要求。

## 常见问题

### IMAP 登录失败怎么办？

优先检查：

- 企业邮箱是否开启 IMAP。
- 是否需要客户端授权码，而不是网页登录密码。
- `NETEASE_EMAIL_USERNAME` 是否需要填写完整邮箱地址。
- 国内和海外 IMAP host 是否选对。

### 为什么搜索结果不完整？

第一版默认按最近 `EMAIL_SEARCH_DEFAULT_DAYS` 天搜索，并对返回数量做限制，避免一次读取过多邮件。可以通过 `--since`、`--before` 和 `--limit` 调整。

### 为什么线程不完整？

线程重建优先依赖 `Message-ID`、`References`、`In-Reply-To`。如果邮件客户端没有正确保留这些头，只能靠主题和参与人推断，可能漏判或误判。

### 附件内容会被分析吗？

不会。第一版只读取附件元信息，不下载附件内容。如果关键需求在附件里，需要人工查看附件。

## 当前限制

1. 第一版不发邮件。
2. 第一版不删除/移动邮件。
3. 第一版不下载附件内容。
4. 线程重建可能不完整。
5. HTML 邮件解析可能不完美。
6. 邮件引用历史可能存在重复。
7. 如果邮件客户端没有正确保留 Message-ID / References / In-Reply-To，线程识别和回复状态判断可能只能靠主题、参与人和时间推断。
8. `get_full_thread` 目前仍以单个目录为主；跨收件箱和已发送的映射由 `get_inbox_reply_status` 提供。

## 后续可扩展功能

- 支持更多邮箱目录角色自动识别。
- 支持更强的跨收件箱/已发送线程合并。
- 支持更强的 IMAP BODYSTRUCTURE 解析。
- 支持更准确的引用历史识别。
- 支持附件白名单下载和本地临时解析。
- 支持本地缓存索引，但仍保持只读邮箱操作。
- 支持更细的线程置信度评分。

## 测试

运行：

```bash
python -m pytest
```

如果没有真实邮箱配置，也可以先运行解析单元测试；测试 fixture 不包含真实邮箱信息。
