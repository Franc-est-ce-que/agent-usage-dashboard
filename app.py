"""
app.py — Claude Code agent usage dashboard. Binds 127.0.0.1:8795 only.

The database always lives in this folder (usage.db), never in
~/.claude/usage.db. A background thread re-scans the Claude Code
projects jsonl folder every 60 seconds; the page asks /api/data for
fresh data every 60 seconds too.

The projects folder defaults to ~/.claude/projects, overridable via the
AGENT_USAGE_PROJECTS_DIR environment variable (see core.py).
"""

import json
import os
import re
import subprocess
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request

import core
import live

app = Flask(__name__)

SCAN_INTERVAL_S = 60
_scan_lock = threading.Lock()
_last_scan_info = {"at": None, "result": None, "error": None}

# ---------------------------------------------------------------------------
# Sidebar "chat with assistant" panel.
#
# This writes/reads a plain 對話_<line>.jsonl text file. It's generic and
# self-contained — nothing here assumes any particular external watcher —
# but if you want some other process to notice a new line the moment it's
# written, that's on you to build (e.g. poll the file, or a filesystem
# watcher), the same way agent-chatroom's bridge.py leaves "waking
# something up" as a pluggable, off-by-default hook.
HERE = os.path.dirname(os.path.abspath(__file__))
CHAT_LINE = os.environ.get("USAGE_CHAT_LINE") or "助理"
NOTIFY_TITLE = CHAT_LINE           # desktop-notification title = the assistant's display name
USER_WHO = "使用者"                # "the user" — the fixed literal used for the human side of the chat
PAGE_NAME = "agent_usage"
CHAT_PATH = os.environ.get("USAGE_CHAT_PATH") or os.path.join(HERE, f"對話_{CHAT_LINE}.jsonl")
CHAT_MAX_CHARS = 2000              # max characters per message you send
CHAT_REPLY_MAX_CHARS = 20000       # max characters per assistant reply
CHAT_NOTIFY_MAX = 120              # max characters shown in a desktop notification
CHAT_LIST_MAX = 200                # max messages returned per GET
CHAT_SEEN_TTL_SEC = 5.0            # heartbeat older than this = page is gone = always notify
CHAT_NOTIFY_CMD = (os.environ.get("USAGE_CHAT_NOTIFY_CMD") or "").strip()  # test hook; osascript (macOS) if unset

_chat_lock = threading.Lock()
_chat_seen = {"t": 0.0, "hidden": None}   # 這一頁最後一次心跳（單調時鐘秒）
_chat_notify_n = {"n": 0}                 # 這個行程叫過幾次「發通知」（只給檢查看）


def _chat_now_text():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def chat_append(row):
    """只准 append；檔不在就建（建出來守信箱才開始守）。"""
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _chat_lock:
        with open(CHAT_PATH, "a", encoding="utf-8") as f:
            f.write(line)


def chat_rows():
    """讀回畫面要的那幾欄；壞行跳過。只給這一頁自己看。"""
    try:
        with open(CHAT_PATH, encoding="utf-8", errors="replace") as f:
            raw = f.read().splitlines()
    except OSError:
        return []
    out = []
    for i, ln in enumerate(raw):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        who = str(d.get("who", ""))
        if who == USER_WHO:
            out.append({"n": i, "me": True, "text": str(d.get("text", "")), "t": d.get("t")})
        elif who == CHAT_LINE or who == NOTIFY_TITLE:
            out.append({"n": i, "me": False, "text": str(d.get("text", "")), "t": d.get("t")})
    return out[-CHAT_LIST_MAX:]


def chat_hidden_arg(v):
    """hidden 參數：1/true → True；0/false → False；沒帶或看不懂 → None（不記心跳）。"""
    s = (v or "").strip().lower()
    if s in ("1", "true", "yes", "hidden"):
        return True
    if s in ("0", "false", "no", "visible"):
        return False
    return None


def chat_seen_note(hidden):
    if hidden is not None:
        _chat_seen["t"] = time.monotonic()
        _chat_seen["hidden"] = bool(hidden)


def chat_notify_decide():
    """要不要發？回 (發不發, 為什麼)。沒心跳／心跳過期＝頁面關掉＝判斷不了＝一律發。"""
    if _chat_seen["hidden"] is None:
        return True, "沒收到過這一頁的心跳（判斷不了，一律發）"
    age = time.monotonic() - _chat_seen["t"]
    if age > CHAT_SEEN_TTL_SEC:
        return True, "頁面 %.1f 秒沒心跳（超過 %.1f 秒＝當頁面關掉，判斷不了，一律發）" % (age, CHAT_SEEN_TTL_SEC)
    if _chat_seen["hidden"]:
        return True, "他沒在看這一頁（hidden=1，%.1f 秒前）" % age
    return False, "他正在看這一頁（hidden=0，%.1f 秒前）" % age


def chat_notify_line(text):
    """一句話重點：空白壓成一個半角空格 → 切到第一個句末符號 → 超過 CHAT_NOTIFY_MAX 字截掉。"""
    s = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(r"[。！？!?]", s)
    if m:
        s = s[:m.end()]
    if len(s) > CHAT_NOTIFY_MAX:
        s = s[:CHAT_NOTIFY_MAX - 1] + "…"
    return s


def chat_notify_send(title, body):
    """真的發那一步。USAGE_CHAT_NOTIFY_CMD 有設就跑它（argv＝標題、內容），沒設才跑 osascript。"""
    _chat_notify_n["n"] += 1
    try:
        if CHAT_NOTIFY_CMD:
            subprocess.run([CHAT_NOTIFY_CMD, title, body], timeout=10, check=False)
        else:
            def esc(x):
                return x.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e",
                            'display notification "%s" with title "%s"' % (esc(body), esc(title))],
                           timeout=10, check=False)
        return True
    except Exception:   # noqa: BLE001
        return False


def chat_from_local():
    """只准本機直接連進來；經代理或通道進來的一律不算本機（抄 VP 的 from_local）。"""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return False
    for h in ("X-Forwarded-For", "X-Real-Ip", "Forwarded", "Cf-Connecting-Ip", "Cf-Ray"):
        if request.headers.get(h):
            return False
    return True


def chat_err(msg, code=400):
    return jsonify({"ok": False, "msg": msg}), code


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _iso_minus(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def background_scanner():
    while True:
        try:
            result = core.full_scan()
            _last_scan_info["at"] = _now_iso()
            _last_scan_info["result"] = result
            _last_scan_info["error"] = None
        except Exception as e:  # noqa: BLE001
            _last_scan_info["error"] = str(e)
        time.sleep(SCAN_INTERVAL_S)


# ---------------------------------------------------------------------------
# 查詢小工具
# ---------------------------------------------------------------------------

def find_session_jsonl_candidates_by_cwd(conn, cwd):
    if not cwd:
        return []
    rows = conn.execute(
        "SELECT se.session_id, s.first_timestamp, s.last_timestamp "
        "FROM session_entrypoint se JOIN sessions s ON s.session_id = se.session_id "
        "WHERE se.cwd = ?",
        (cwd,),
    ).fetchall()
    return [dict(r) for r in rows]


def session_exists(conn, session_id):
    row = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row is not None


def resolve_proc_session(conn, proc, name_to_sid8):
    """回 session_id 或 None。"""
    # 2026-10-28：Claude Code 自己在 ~/.claude/sessions/<pid>.json 記了這個程序對到哪個 sessionId，最準，先查它
    #（只讀 sessionId 一個欄位；同資料夾的 .key 檔不准碰）
    try:
        _f = os.path.expanduser("~/.claude/sessions/%d.json" % int(proc["pid"]))
        if os.path.isfile(_f):
            _sid = json.load(open(_f)).get("sessionId")
            if _sid and session_exists(conn, _sid):
                return _sid
    except Exception:
        pass
    sid = live.resolve_session_id_from_arg(proc["resume_arg"])
    if sid and session_exists(conn, sid):
        return sid

    # --resume 給的是線名別名（像 "VP"），直接查現任登記表，不用猜 cwd
    arg = proc["resume_arg"]
    if arg and arg in name_to_sid8:
        sid8 = name_to_sid8[arg]
        row = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id LIKE ?", (sid8 + "%",)
        ).fetchone()
        if row:
            return row[0]

    cwd = live.pid_cwd(proc["pid"])
    candidates = find_session_jsonl_candidates_by_cwd(conn, cwd)
    if not candidates:
        return None

    if proc["resume_arg"] is None:
        # 空白開視窗：挑 first_timestamp 在啟動後最近的那個新 session
        start_iso = live.epoch_to_iso(proc["start_epoch"] - 5)
        after = [c for c in candidates if c["first_timestamp"] >= start_iso]
        if not after:
            return None
        after.sort(key=lambda c: c["first_timestamp"])
        return after[0]["session_id"]
    else:
        # --resume 給了一個不是 UUID／路徑的別名：挑啟動前就存在、
        # 最近被動過的那個 session（最可能是被接續的那個）
        start_iso = live.epoch_to_iso(proc["start_epoch"] + 5)
        before = [c for c in candidates if c["first_timestamp"] <= start_iso]
        pool = before if before else candidates
        pool.sort(key=lambda c: c["last_timestamp"], reverse=True)
        return pool[0]["session_id"]


def get_name(conn, session_id, line_names):
    """102802 使用者定：名字欄只放名字，編號另外一欄（呼叫端自己接 session_id[:8]）。"""
    sid8 = session_id[:8]
    if sid8 in line_names:
        return line_names[sid8]
    row = conn.execute(
        "SELECT custom_title FROM session_custom_title WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    name = None
    if row and row[0]:
        name = row[0]
    else:
        row = conn.execute(
            "SELECT agent_name FROM session_agent_name WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row and row[0]:
            name = row[0]
    if not name:
        return sid8
    # 2026-10-30：不在報到表上、名字卻跟某條線的現任撞名＝被換下來的舊扇，標「舊」免得看錯
    norm = lambda s: s.replace("鎖", "锁")
    if norm(name) in {norm(v) for v in line_names.values()}:
        return "舊" + name
    return name


def window_token_sum(conn, session_id, start_iso):
    """主對話＋分身合計。"""
    row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens), 0) "
        "FROM turns WHERE session_id = ? AND timestamp >= ?",
        (session_id, start_iso),
    ).fetchone()
    return row[0] or 0


def window_token_sum_subagent(conn, session_id, start_iso):
    """只算分身（is_subagent=1）那部分，給「其中分身花的」欄位用。"""
    row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens), 0) "
        "FROM turns WHERE session_id = ? AND is_subagent = 1 AND timestamp >= ?",
        (session_id, start_iso),
    ).fetchone()
    return row[0] or 0


def build_open_row(conn, session_id, proc, line_names):
    name = get_name(conn, session_id, line_names)

    # 總框退件：模型／對話長度／最後動作時間只看主對話檔，不看 subagents/
    # （is_subagent=0），否則會被分身自己的 model／usage 蓋過去。
    last_turn = conn.execute(
        "SELECT model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, timestamp "
        "FROM turns WHERE session_id = ? AND is_subagent = 0 ORDER BY timestamp DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    model = last_turn["model"] if last_turn else None
    conv_len = (
        (last_turn["input_tokens"] or 0)
        + (last_turn["cache_read_tokens"] or 0)
        + (last_turn["cache_creation_tokens"] or 0)
        if last_turn else 0
    )
    last_ts = last_turn["timestamp"] if last_turn else None

    # 102802 追加：最後一則 assistant 之後有沒有 /model 切換紀錄，有就顯示切到哪個
    # （「問一次約多少錢」也照新模型的單價算，未來的回話都是這個價）。
    # 102802 第三輪使用者定：模型欄只顯示現在的模型名，拿掉「（已換，還沒回過話）」註記、
    # 拿掉「(1M context)」這類括號註記；換成什麼就原樣顯示那個名字，不准自己改寫數字。
    switched_to = core.model_switch_after_last_assistant(session_id)
    if switched_to:
        model_display = re.sub(r"\s*\([^)]*\)", "", switched_to).strip()
    else:
        model_display = core.pretty_model_name(model)

    # 「問一次約多少錢」也只看主對話檔（同一條退件理由）。
    last5 = conn.execute(
        "SELECT model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM turns WHERE session_id = ? AND is_subagent = 0 ORDER BY timestamp DESC LIMIT 5",
        (session_id,),
    ).fetchall()
    costs = []
    any_priced = False
    for t in last5:
        cost_model = switched_to if switched_to else t["model"]
        c, priced = core.turn_cost(
            cost_model, t["input_tokens"], t["output_tokens"],
            t["cache_read_tokens"], t["cache_creation_tokens"],
        )
        costs.append(c)
        any_priced = any_priced or priced
    avg_cost = sum(costs) / len(costs) if costs else 0.0

    # 102802 第二輪使用者定：收費方式欄改成單價數字本身，拿掉「訂閱 Max…估計」那類解釋文字。
    charge_model = switched_to if switched_to else model
    charge_display = core.price_display(charge_model)

    sums = {}
    for label, secs in (("1h", 3600), ("6h", 21600), ("24h", 86400)):
        sums[label] = window_token_sum(conn, session_id, _iso_minus(secs))
    since_open_iso = live.epoch_to_iso(proc["start_epoch"])
    since_open = window_token_sum(conn, session_id, since_open_iso)

    # 「其中分身花的」：只要近24小時跟開窗以來這兩格（退件單只要這兩個）
    sub_24h = window_token_sum_subagent(conn, session_id, _iso_minus(86400))
    sub_since_open = window_token_sum_subagent(conn, session_id, since_open_iso)

    # 自動佔比／被什麼叫醒最多：改成只算近24小時、只看主對話檔
    last24h_iso = _iso_minus(86400)
    trig_rows = conn.execute(
        "SELECT tm.label FROM turns t LEFT JOIN trigger_meta tm ON t.message_id = tm.message_id "
        "WHERE t.session_id = ? AND t.is_subagent = 0 AND t.timestamp >= ? "
        "AND t.message_id IS NOT NULL AND t.message_id != ''",
        (session_id, last24h_iso),
    ).fetchall()
    total_turns = len(trig_rows)
    labels = [r[0] or core.USER_LABEL for r in trig_rows]
    auto_count = sum(1 for l in labels if l in core.AUTO_LABELS)
    auto_ratio = (auto_count / total_turns * 100.0) if total_turns else 0.0
    auto_only = [l for l in labels if l in core.AUTO_LABELS]
    woken_by = Counter(auto_only).most_common(1)[0][0] if auto_only else "無"

    last_local = "無"
    last_age_s = None
    if last_ts:
        try:
            dt_utc = datetime.strptime(last_ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            last_local = (dt_utc + LOCAL_OFFSET).strftime("%Y-%m-%d %H:%M")
            last_age_s = (datetime.now(timezone.utc) - dt_utc).total_seconds()
        except ValueError:
            last_local = last_ts

    # 102802 第二輪使用者定：開了多久滿 24 小時進位成天數（X 天 Y 小時），不滿照舊（Y 小時 Z 分）。
    elapsed_s = proc["elapsed_s"]
    days = elapsed_s // 86400
    hh = (elapsed_s % 86400) // 3600
    mm = (elapsed_s % 3600) // 60
    if days:
        opened_for = f"{days} 天 {hh} 小時"
    else:
        opened_for = f"{hh} 小時 {mm} 分" if hh else f"{mm} 分"

    return {
        "名字": name,
        "編號": session_id[:8],
        "模型": model_display,
        "收費方式": charge_display,
        "問一次約多少錢_USD": round(avg_cost, 4) if any_priced else None,
        "問一次約多少錢_備註": None if any_priced else "模型不在定價表，未估價",
        "對話長度_tokens": conv_len,
        "近1小時總token": sums["1h"],
        "近6小時總token": sums["6h"],
        "近24小時總token": sums["24h"],
        "近24小時其中分身花的token": sub_24h,
        "開窗以來總token": since_open,
        "開窗以來其中分身花的token": sub_since_open,
        "自動佔比_近24小時": round(auto_ratio, 1),
        "被什麼叫醒最多_近24小時": woken_by,
        "開了多久": opened_for,
        "開了多久_秒": elapsed_s,
        "最後一次動_本地時間": last_local,
        "最後一次動_距今秒": last_age_s,
        "pid": proc["pid"],
        "tty": proc["tty"],
        "session_id": session_id,
    }


# Display timezone for the hourly chart / "last active" column, as an
# offset from UTC in hours. Defaults to 0 (UTC) — set
# AGENT_USAGE_UTC_OFFSET_HOURS (can be negative, can have a fraction like
# 5.5) to show times in your own local time instead.
LOCAL_OFFSET = timedelta(hours=float(os.environ.get("AGENT_USAGE_UTC_OFFSET_HOURS", "0") or 0))


def token_window_bounds(now_utc, hours=24):
    """The hourly chart, the pie chart and any standalone verification
    script all need to use the exact same cutoff to agree with each
    other, so it's computed once, here. Returns (window_start_utc,
    hour_starts): hour_starts is `hours` local-time hour boundaries, oldest
    to newest (the last one is the current, still-incomplete hour);
    window_start_utc is the earliest of those converted back to UTC — any
    SQL "WHERE timestamp >= ?" should use this, not "now minus 24 hours",
    which wouldn't align to hour boundaries and would make the hourly
    chart's edge bucket disagree with the pie chart's total."""
    now_local = now_utc + LOCAL_OFFSET
    cur_hour = now_local.replace(minute=0, second=0, microsecond=0)
    hour_starts = [cur_hour - timedelta(hours=i) for i in range(hours - 1, -1, -1)]
    window_start_utc = hour_starts[0] - LOCAL_OFFSET
    return window_start_utc, hour_starts


def hourly_token_series(conn, window_start_utc, hour_starts):
    """Past `hours` hours, one bucket per hour (in the display timezone),
    y = all tokens added up for that hour — open windows, closed windows,
    subagents and background processes all counted. The turns table is
    already deduplicated by message.id (unique index idx_turns_message_id),
    so this can sum directly without deduplicating again."""
    rows = conn.execute(
        "SELECT timestamp, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM turns WHERE timestamp >= ?",
        (window_start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),),
    ).fetchall()

    idx = {h: i for i, h in enumerate(hour_starts)}
    sums = [0] * len(hour_starts)
    for r in rows:
        ts = r["timestamp"]
        if not ts:
            continue
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        hour_key = (dt + LOCAL_OFFSET).replace(minute=0, second=0, microsecond=0)
        i = idx.get(hour_key)
        if i is not None:
            sums[i] += (
                (r["input_tokens"] or 0) + (r["output_tokens"] or 0)
                + (r["cache_read_tokens"] or 0) + (r["cache_creation_tokens"] or 0)
            )
    return [{"hour_local": h.strftime("%Y-%m-%d %H:00"), "tokens": t} for h, t in zip(hour_starts, sums)]


def agent_pie_data(conn, line_names, window_start_utc, small_pct=2.0):
    """過去（跟折線同一個切點 window_start_utc）各 agent 佔比。依名字分組，用跟
    get_name 一樣的認名規則（報到表名／customTitle／agentName／8碼編號），已關掉的
    視窗也算（直接查 turns，不靠現在還在跑的 ps 行程）；分身的 session_id 跟主視窗同一
    個，SUM 自然就把分身算進主視窗。背景程式（entrypoint='sdk-cli'）全部合成一片
    「背景程式」。小於 small_pct% 的併成「其他」。"""
    start_iso = window_start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = conn.execute(
        "SELECT t.session_id AS sid, se.entrypoint AS entrypoint, "
        "SUM(t.input_tokens+t.output_tokens+t.cache_read_tokens+t.cache_creation_tokens) AS tok "
        "FROM turns t LEFT JOIN session_entrypoint se ON se.session_id = t.session_id "
        "WHERE t.timestamp >= ? GROUP BY t.session_id",
        (start_iso,),
    ).fetchall()

    by_name = defaultdict(int)
    for r in rows:
        tok = r["tok"] or 0
        if tok <= 0:
            continue
        if r["entrypoint"] == "sdk-cli":
            by_name["背景程式"] += tok
        else:
            by_name[get_name(conn, r["sid"], line_names)] += tok

    total = sum(by_name.values())
    if total <= 0:
        return []
    items = sorted(by_name.items(), key=lambda kv: kv[1], reverse=True)
    big, other = [], 0
    for name, tok in items:
        pct = tok / total * 100.0
        if pct < small_pct:
            other += tok
        else:
            big.append((name, tok, pct))
    out = [{"名字": n, "tokens": t, "pct": round(p, 2)} for n, t, p in big]
    if other > 0:
        out.append({"名字": "其他", "tokens": other, "pct": round(other / total * 100.0, 2)})
    return out


def build_background_summary(conn):
    buckets = {}
    for label, secs in (("1h", 3600), ("6h", 21600), ("24h", 86400)):
        start_iso = _iso_minus(secs)
        rows = conn.execute(
            "SELECT COALESCE(se.first_user_label, '其他開場') AS bucket, "
            "COUNT(DISTINCT t.session_id) AS n, "
            "COALESCE(SUM(t.input_tokens+t.output_tokens+t.cache_read_tokens+t.cache_creation_tokens), 0) AS tok "
            "FROM turns t JOIN session_entrypoint se ON t.session_id = se.session_id "
            "WHERE se.entrypoint = 'sdk-cli' AND t.timestamp >= ? "
            "GROUP BY bucket",
            (start_iso,),
        ).fetchall()
        for r in rows:
            b = buckets.setdefault(r["bucket"], {"bucket": r["bucket"]})
            b[f"sessions_{label}"] = r["n"]
            b[f"tokens_{label}"] = r["tok"]
    return list(buckets.values())


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    conn = core.get_db()
    try:
        line_names, name_to_sid8 = live.load_line_names()
        procs = live.list_claude_processes()

        open_rows = []
        unknown_rows = []
        for proc in procs:
            sid = resolve_proc_session(conn, proc, name_to_sid8)
            if sid:
                open_rows.append(build_open_row(conn, sid, proc, line_names))
            else:
                unknown_rows.append({
                    "pid": proc["pid"],
                    "tty": proc["tty"],
                    "elapsed_s": proc["elapsed_s"],
                    "note": "ps 看得到這個視窗，但對不到任何 session 檔",
                })

        background = build_background_summary(conn)

        # 102802 第四輪：折線（長條）＋圓餅都用同一個切點算過去 24 小時，兩邊加總才會
        # 對得上（跟獨立腳本核對也用 token_window_start_utc 這個切點）。
        now_utc = datetime.now(timezone.utc)
        window_start_utc, hour_starts = token_window_bounds(now_utc, hours=24)
        hourly_tokens = hourly_token_series(conn, window_start_utc, hour_starts)
        agent_pie = agent_pie_data(conn, line_names, window_start_utc)
        token_window_start_utc = window_start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        return jsonify({
            "generated_at": _now_iso(),
            "last_scan": _last_scan_info,
            "ps_window_count": len(procs),
            "matched_count": len(open_rows),
            "unknown_count": len(unknown_rows),
            "open_windows": open_rows,
            "unknown_windows": unknown_rows,
            "background": background,
            "red_thresholds": core.red_thresholds(),
            "hourly_tokens": hourly_tokens,
            "agent_pie": agent_pie,
            "token_window_start_utc": token_window_start_utc,
        })
    finally:
        conn.close()


@app.get("/api/chat")
def api_chat_list():
    """回對話；同時記心跳（hidden=0|1，44a 用）。"""
    chat_seen_note(chat_hidden_arg(request.args.get("hidden")))
    return jsonify({"ok": True, "msgs": chat_rows()})


@app.post("/api/chat")
def api_chat_send():
    """他送一句話 → append 一行（who＝使用者、line＝CHAT_LINE）→ 守信箱 5 秒內敲總框。"""
    d = request.get_json(silent=True) or {}
    text = d.get("text")
    if not isinstance(text, str) or not text.strip():
        return chat_err("沒有字")
    if len(text) > CHAT_MAX_CHARS:
        return chat_err("一則最多 %d 字（這則 %d 字）" % (CHAT_MAX_CHARS, len(text)))
    chat_append({"who": USER_WHO, "line": CHAT_LINE, "page": PAGE_NAME, "frame": None,
                 "text": text, "t": _chat_now_text()})
    return jsonify({"ok": True, "msgs": chat_rows()})


@app.post("/api/chat/reply")
def api_chat_reply():
    """總框回話：只准本機。body {"text": 回話}。一次做完寫檔＋判斷他在不在看＋該發就發（44a）。"""
    if not chat_from_local():
        return chat_err("只准本機呼叫", 403)
    d = request.get_json(silent=True) or {}
    text = d.get("text")
    if not isinstance(text, str) or not text.strip():
        return chat_err("沒有字")
    if len(text) > CHAT_REPLY_MAX_CHARS:
        return chat_err("一則回話最多 %d 字" % CHAT_REPLY_MAX_CHARS)
    chat_append({"who": CHAT_LINE, "line": CHAT_LINE, "page": PAGE_NAME, "frame": None,
                 "text": text, "t": _chat_now_text()})
    send, why = chat_notify_decide()
    body = chat_notify_line(text)
    notified = chat_notify_send(NOTIFY_TITLE, body) if send else False
    return jsonify({"ok": True, "notified": notified, "why": why, "title": NOTIFY_TITLE,
                    "body": body if send else "", "calls": _chat_notify_n["n"]})


if __name__ == "__main__":
    t = threading.Thread(target=background_scanner, daemon=True)
    t.start()
    app.run(host="127.0.0.1", port=8795, debug=False)
