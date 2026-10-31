# agent-usage-dashboard

🔗 [Live demo / 線上示範](https://franc-est-ce-que.github.io/agent-usage-dashboard/demo/)

[English](#agent-usage-dashboard) | [简体中文](#简体中文)

A local web dashboard that watches Claude Code's own usage logs
(`~/.claude/projects/**/*.jsonl`) and turns them into: which windows are
open right now, how many tokens and roughly how much money each one has
spent, a 24-hour chart, and a pie chart of who's spending the most. Runs
entirely on your machine — it only reads log files that Claude Code
already writes locally, never reads what you actually typed, and sends
nothing anywhere.

## What this is

- **`app.py` / `core.py` / `live.py`** — a small Flask app. `core.py`
  wraps a vendored copy of [claude-usage](https://github.com/phuryn/claude-usage)
  (see "Credit" below) to parse the jsonl logs into a local SQLite
  database, then adds a few extra things on top: which window a running
  `claude` process belongs to, a simple price estimate per model, and a
  24-hour token chart / pie chart.
- **`templates/index.html`** — the page itself: a table of open windows,
  a table of windows the dashboard couldn't identify, a background-jobs
  summary, two charts, and a small "chat with assistant" side panel (see
  below).
- The "chat with assistant" panel is a generic, self-contained feature:
  it writes what you type to a local `對話_<name>.jsonl` text file, and
  shows whatever gets appended back to that file as a reply. Nothing
  about it assumes any particular bot or AI backend — wiring something up
  to actually read and answer that file is on you.

## Screenshot

*(left blank on purpose — add your own screenshot here before publishing)*

## Install

Requires Python 3.9+ and Flask (no other pip packages — the vendored
`scanner.py` is pure standard library):

```bash
pip install flask
```

## How to run

```bash
python3 app.py
```

This binds `127.0.0.1:8795` and starts a background thread that re-scans
`~/.claude/projects` every 60 seconds. Open `http://127.0.0.1:8795/` in a
browser.

To point it at a different projects folder (for testing, or if your
Claude Code data lives somewhere non-default), set
`AGENT_USAGE_PROJECTS_DIR` before starting it — see `config.example`.

## Configuration

See `config.example` for every environment variable this code reads —
nothing is hardcoded to a particular machine, user account, or timezone.
Notably:

- `AGENT_USAGE_PROJECTS_DIR` — which folder of Claude Code jsonl logs to
  read (default: `~/.claude/projects`).
- `AGENT_USAGE_UTC_OFFSET_HOURS` — what timezone offset to display times
  in on the hourly chart and the "last active" column (default: `0`,
  i.e. UTC). Set it to your own offset, e.g. `-5` or `5.5`.
- `AGENT_USAGE_LINE_NAMES_CMD` — optional, pluggable: path to a script
  that prints lines like `<name>：...（<8-hex session id>，...報到）`, used
  to label an open window with a name you chose instead of its raw
  session id. Off by default; nothing is called unless you set this.
- `USAGE_CHAT_LINE` / `USAGE_CHAT_PATH` / `USAGE_CHAT_NOTIFY_CMD` — the
  "chat with assistant" panel's display name, the jsonl file it reads
  and writes, and (optional) a command to run instead of a macOS desktop
  notification when a reply arrives while the page isn't visible.

## Known limitations

- Desktop notifications use `osascript`, so that feature only does
  anything on macOS (unless you set `USAGE_CHAT_NOTIFY_CMD` to something
  else). The rest of the dashboard is plain Python/Flask and isn't
  macOS-specific.
- Pricing in `core.py` is a small hardcoded table for a few known models;
  anything not in that table shows "not in the pricing table" rather than
  a wrong number. Prices will drift out of date — check them yourself
  before trusting a cost total.
- The "which window is this" matching in `live.py` is best-effort (it
  reads `ps`/`lsof` and a process's `--resume`/`--session-id` argument);
  a window it can't confidently match lands in the "unknown" table rather
  than being guessed at.
- Not tested on Windows (`ps`/`lsof` are assumed).

## Credit

The jsonl-to-SQLite scanning logic is
[claude-usage](https://github.com/phuryn/claude-usage) by Pawel Huryn,
vendored here under `vendor_claude_usage/` and used unmodified, under its
own MIT license (`vendor_claude_usage/LICENSE`). `core.py` imports its
`scanner.py` directly and adds its own tables/queries on top (entrypoint
and agent-name tracking, trigger-source labeling, pricing) without
touching the vendored file.

`app.py`, `core.py`, `live.py` and `templates/index.html` are our own
code, MIT-licensed (see `LICENSE`).

---

## 繁體中文簡介

這是一個看 Claude Code 自己寫在本機的用量 log（`~/.claude/projects` 底下的
jsonl 檔）、整理成一個網頁的小工具：現在開著哪些視窗、每個視窗花了多少
token、大概多少錢、過去 24 小時的折線圖與各視窗佔比圓餅圖。全部都在你自己
的電腦上跑，只讀 Claude Code 本來就會寫在本機的 log 檔，不會讀你實際打的
內容，也不會把任何東西傳到別的地方。

核心的「讀 jsonl、算 token」邏輯借用了開源專案
[claude-usage](https://github.com/phuryn/claude-usage)（細節見上面「Credit」），
我們在它上面加了：認出哪個視窗對到哪個 Claude 行程、簡單的計價表、24 小時
圖表。頁面右側還有一個「跟助理聊天」小面板，純粹是寫讀一個文字檔，要接什麼
樣的機器人或 AI 都可以自己接。

---

## 简体中文

[English](#agent-usage-dashboard) | [简体中文](#简体中文)

一个本机网页仪表盘，看 Claude Code 自己写在本机的用量日志（`~/.claude/projects` 下的 jsonl 文件），整理成：现在开着哪些窗口、每个窗口花了多少 token、大概多少钱、过去 24 小时的折线图、各窗口占比的饼图。全部在你自己的电脑上跑，只读 Claude Code 本来就会写在本机的日志文件，不读你实际打的内容，也不会把任何东西传到别的地方。

### 这是什么

- **`app.py` / `core.py` / `live.py`** —— 一个小型 Flask 应用。`core.py` 包了一份收录进来的 [claude-usage](https://github.com/phuryn/claude-usage)（见下面“鸣谢”），把 jsonl 日志解析进本地 SQLite 数据库，再在上面加了几样东西：一个正在跑的 `claude` 进程属于哪个窗口、按模型估的简单价格、24 小时 token 折线图/饼图。
- **`templates/index.html`** —— 页面本身：开着的窗口表格、认不出的窗口表格、后台任务汇总、两张图表，还有一个小的“跟助理聊天”侧边面板（见下面）。
- “跟助理聊天”面板是一个通用、自包含的功能：把你打的字写进本地文本文件 `對話_<name>.jsonl`，再把写回这个文件里的内容当作回复显示出来。它不假设任何特定的机器人或 AI 后端——要接什么样的东西读这个文件、回答它，是你自己的事。

### 截图

*（故意留空——发布前请自己加截图）*

### 安装

需要 Python 3.9 以上和 Flask（不需要其他 pip 包——收录进来的 `scanner.py` 是纯标准库写的）：

```bash
pip install flask
```

### 怎么运行

```bash
python3 app.py
```

这会绑定 `127.0.0.1:8795`，并启动一个后台线程每 60 秒重新扫描一次 `~/.claude/projects`。在浏览器打开 `http://127.0.0.1:8795/`。

要指向别的 projects 文件夹（测试用，或者你的 Claude Code 数据不在默认位置），在启动前设置 `AGENT_USAGE_PROJECTS_DIR`——见 `config.example`。

### 配置

每一个会用到的环境变量都列在 `config.example` 里——没有任何东西写死成某台机器、某个账号或某个时区。值得一提的几个：

- `AGENT_USAGE_PROJECTS_DIR` —— 要读哪个文件夹的 Claude Code jsonl 日志（默认：`~/.claude/projects`）。
- `AGENT_USAGE_UTC_OFFSET_HOURS` —— 折线图和“最后动作”这一栏要显示哪个时区的时间（默认 `0`，也就是 UTC）。设成你自己的时区偏移，比如 `-5` 或 `5.5`。
- `AGENT_USAGE_LINE_NAMES_CMD` —— 可选、可插拔：一个脚本的路径，打印形如 `<名字>：...（<8 位十六进制 session id>，...報到）` 的行，用来给窗口标一个你自己选的名字，而不是只显示一串 session id。默认关闭，不设就什么都不会被调用。
- `USAGE_CHAT_LINE` / `USAGE_CHAT_PATH` / `USAGE_CHAT_NOTIFY_CMD` —— “跟助理聊天”面板的显示名字、它读写的 jsonl 文件，以及（可选）页面不在前台时，收到回复要触发桌面通知时改跑哪个命令，而不是 macOS 的系统通知。

### 已知限制

- 桌面通知用的是 `osascript`，所以这个功能只在 macOS 上有用（除非你把 `USAGE_CHAT_NOTIFY_CMD` 设成别的东西）。仪表盘其余部分就是普通的 Python/Flask，不限 macOS。
- `core.py` 里的计价表是写死的一小张表，只覆盖几个已知模型；不在表里的模型会显示“未在定价表”，不会给错误的数字。价格会过时，用之前自己核对一下。
- `live.py` 里“这是哪个窗口”的匹配是尽力而为（读 `ps`/`lsof` 和进程的 `--resume`/`--session-id` 参数）；匹配不到就落进“认不出”那张表，不会硬猜一个名字。
- 没有在 Windows 上测试过（假设有 `ps`/`lsof`）。

### 鸣谢

把 jsonl 解析进 SQLite 的核心逻辑是 Pawel Huryn 写的 [claude-usage](https://github.com/phuryn/claude-usage)，收录在 `vendor_claude_usage/` 下，原样未改，用它自己的 MIT 授权（`vendor_claude_usage/LICENSE`）。`core.py` 直接 import 它的 `scanner.py`，在不碰那个文件的前提下，在它外面加了自己的表和查询（entrypoint/agent 名字追踪、触发来源标签、计价）。

`app.py`、`core.py`、`live.py` 和 `templates/index.html` 是我们自己写的代码，MIT 授权（见 `LICENSE`）。
