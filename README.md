# agent-usage-dashboard

🔗 [Live demo / 線上示範](https://franc-est-ce-que.github.io/agent-usage-dashboard/demo/)

[English](#agent-usage-dashboard) | [繁體中文](#繁體中文) | [简体中文](#简体中文)

Based on [claude-usage](https://github.com/phuryn/claude-usage) (by Pawel Huryn, MIT license), modified.

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

## 繁體中文

本專案基於 [claude-usage](https://github.com/phuryn/claude-usage)（作者 Pawel Huryn，MIT 授權）修改。

亮點：AI 助手是照用量收費的，這張表讓你一眼看出誰在偷偷花你的錢。

它解決什麼問題：

AI 助手每回一句話都要錢，對話越長，每句越貴。開了很多個之後，你很難知道是哪一個在花錢、花了多少；有的助手你早就沒在用，它卻還開著，一直在花。常常到月底看帳單才嚇一跳。

它做什麼：

1. 一張表列出每一個助手：用的是哪個模型、問一次大概多少錢、對話已經多長。
2. 看得到最近 1 小時、6 小時、24 小時各用了多少，哪段時間花最兇一清二楚。
3. 花太多、對話太長、或開很久都沒動的，會用紅字標出來，提醒你該關掉或重開。
4. 會分辨「你親手問的」和「助手自己跑的」各占多少，知道錢是不是花在你要的事上。
5. 數字用 K、M 縮寫，看得懂；會跟著電腦的深色或淺色模式換顏色。
6. 旁邊有對話框，可以直接問「為什麼這個這麼貴？」

適合誰：每個月 AI 帳單不便宜、想知道錢花去哪裡的人。

---

## 简体中文

本项目基于 [claude-usage](https://github.com/phuryn/claude-usage)（作者 Pawel Huryn，MIT 授权）修改。

亮点：AI 助手是照用量收费的，这张表让你一眼看出谁在偷偷花你的钱。

它解决什么问题：

AI 助手每回一句话都要钱，对话越长，每句越贵。开了很多个之后，你很难知道是哪一个在花钱、花了多少；有的助手你早就没在用，它却还开著，一直在花。常常到月底看帐单才吓一跳。

它做什么：

1. 一张表列出每一个助手：用的是哪个模型、问一次大概多少钱、对话已经多长。
2. 看得到最近 1 小时、6 小时、24 小时各用了多少，哪段时间花最凶一清二楚。
3. 花太多、对话太长、或开很久都没动的，会用红字标出来，提醒你该关掉或重开。
4. 会分辨「你亲手问的」和「助手自己跑的」各占多少，知道钱是不是花在你要的事上。
5. 数字用 K、M 缩写，看得懂；会跟著电脑的深色或浅色模式换颜色。
6. 旁边有对话框，可以直接问「为什么这个这么贵？」

适合谁：每个月 AI 帐单不便宜、想知道钱花去哪里的人。
