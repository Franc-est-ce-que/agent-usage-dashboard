# agent-usage-dashboard

🔗 [Live demo / 線上示範](https://franc-est-ce-que.github.io/agent-usage-dashboard/demo/)

[English](#agent-usage-dashboard) | 简体中文（Simplified Chinese 版本待定案，之後補上）

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
