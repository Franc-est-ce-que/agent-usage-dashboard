"""
core.py — Agent 用量頁的掃描與算帳邏輯。

資料來源只讀這些欄位（不准多讀）：
usage（input/output/cache_read/cache_creation tokens）、model、timestamp、
type、customTitle/agentName、entrypoint、cwd，以及判斷觸發來源要用的
開頭關鍵字比對（cross-session-message / Another Claude session /
Stop hook feedback / idle notice / system-reminder / <<autonomous）。

不准把任何對話內容存進資料庫、印到頁面、寫進 log —— 本檔只把「比對後
得到的標籤」寫進資料庫，從不寫原始文字。
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / "vendor_claude_usage"
DB_PATH = BASE_DIR / "usage.db"

# 一定要在 import vendor scanner 之前設好，scanner.DB_PATH 是 import 時算的常數。
os.environ["CLAUDE_USAGE_DB"] = str(DB_PATH)
sys.path.insert(0, str(VENDOR_DIR))
import scanner as vscanner  # noqa: E402  (vendor claude-usage, MIT)

# Defaults to ~/.claude/projects; override with AGENT_USAGE_PROJECTS_DIR
# (e.g. for a test fixture folder, or a non-default Claude Code data dir).
_projects_override = os.environ.get("AGENT_USAGE_PROJECTS_DIR")
PROJECTS_DIRS = [Path(_projects_override).expanduser()] if _projects_override else [Path.home() / ".claude" / "projects"]

# ---------------------------------------------------------------------------
# 單價表（每百萬 token，USD；進 / 出）。放在檔頭常數，改價只改這裡一處。
# ---------------------------------------------------------------------------
PRICE_OPUS_5 = (5.0, 25.0)
PRICE_OPUS_5_5 = (4.0, 20.0)
PRICE_SONNET = (2.0, 10.0)
CACHE_READ_MULT = 0.1   # 讀快取 = 進價 × 0.1
CACHE_WRITE_MULT = 1.25  # 寫快取 = 進價 × 1.25


def price_for_model(model):
    """回傳 (進價, 出價)；不在定價表裡的模型回 None（不估價，不是 0 元）。"""
    m = (model or "").lower()
    if "opus" in m:
        if "5-5" in m or "5.5" in m:
            return PRICE_OPUS_5_5
        return PRICE_OPUS_5
    if "sonnet" in m:
        return PRICE_SONNET
    return None


def pretty_model_name(model):
    """102802 使用者定：模型欄不要 claude、不要連字號 → 「Opus 5.5」「Opus 5」「Sonnet 5」
    這種。認不出的模型照原樣顯示（不瞎猜）。"""
    m = (model or "").lower()
    if "opus" in m:
        return "Opus 5.5" if ("5-5" in m or "5.5" in m) else "Opus 5"
    if "sonnet" in m:
        return "Sonnet 5"
    if "haiku" in m:
        return "Haiku 5"
    return model or "未知"


def _fmt_money(x):
    """$4 不要 $4.0；$0.4 保留小數。"""
    s = ("%g" % x)
    return s


def price_display(model):
    """102802 第二輪使用者定：收費方式欄只顯示「入 $4／出 $20」，不加任何解釋文字、
    不加（每百萬）、不加讀快取；不在定價表裡的模型回「未在定價表」。"""
    p = price_for_model(model)
    if p is None:
        return "未在定價表"
    price_in, price_out = p
    return "入 $%s／出 $%s" % (_fmt_money(price_in), _fmt_money(price_out))


# ---------------------------------------------------------------------------
# 標紅門檻（102802 第三輪使用者定）：超過這些數字，頁面把那一格文字標紅。
# 只在這裡放一次；/api/data 把這張表原樣回給前端，前端不准自己重複定義一份數字
# （design-principles.md 第 1 條：一個事實只准有一個聲音）。
# ---------------------------------------------------------------------------
RED_COST_USD = 0.2          # 問一次約多少錢 > $0.2 標紅
LONG_CONTEXT_RED = 400000   # 對話長度(token) > 這個數字標紅
RED_AUTO_RATIO_PCT = 30     # 自動佔比(近24小時) > 30% 標紅
RED_OPEN_HOURS = 3 * 24     # 開了多久 > 3 天（小時數）標紅
RED_LAST_ACTION_HOURS = 24  # 最後一次動距現在 > 24 小時標紅


def red_thresholds():
    return {
        "cost_usd": RED_COST_USD,
        "conv_len": LONG_CONTEXT_RED,
        "auto_ratio_pct": RED_AUTO_RATIO_PCT,
        "open_hours": RED_OPEN_HOURS,
        "last_action_hours": RED_LAST_ACTION_HOURS,
    }


def turn_cost(model, input_tokens, output_tokens, cache_read, cache_creation):
    """回傳 (估計費用 USD, 是否有定價)。沒有定價的模型費用算 0 但標記未估。"""
    p = price_for_model(model)
    if p is None:
        return 0.0, False
    price_in, price_out = p
    cost = (
        input_tokens * price_in
        + output_tokens * price_out
        + cache_read * price_in * CACHE_READ_MULT
        + cache_creation * price_in * CACHE_WRITE_MULT
    ) / 1_000_000.0
    return cost, True


# ---------------------------------------------------------------------------
# 觸發來源分類：只看開頭關鍵字，回傳的是標籤，不是原文。
# ---------------------------------------------------------------------------
AUTO_LABELS = ("別扇來信", "鎖擋下", "閒置通知", "system-reminder", "排程")
USER_LABEL = "使用者"


def classify_trigger_text(text):
    """text 是這則 user 訊息的純文字。回傳標籤字串，不回傳文字本身。"""
    if text is None:
        text = ""
    t = text.lstrip()
    if "cross-session-message" in text or "Another Claude session" in text:
        return "別扇來信"
    if "Stop hook feedback" in text:
        return "鎖擋下"
    if re.search(r"idle notice", text, re.IGNORECASE):
        return "閒置通知"
    if t[:20].lower().startswith("<system-reminder"):
        return "system-reminder"
    if t.startswith("<<autonomous"):
        return "排程"
    return USER_LABEL


def _extract_user_text_or_skip(record):
    """回 (text, is_tool_result)。is_tool_result=True 時 text 必為 None，
    呼叫端要跳過這筆、繼續往前找上一筆。"""
    msg = record.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
            return None, True
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text") or "", False
        return "", False
    if isinstance(content, str):
        return content, False
    return "", False


# ---------------------------------------------------------------------------
# 自己的擴充表：vendor scanner 沒有 entrypoint / agentName / customTitle(限定
# custom-title 這個 type，不混 ai-title) / 觸發標籤，自己掃一遍補上。
# ---------------------------------------------------------------------------

def init_extra_tables(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trigger_meta (
            message_id TEXT PRIMARY KEY,
            label      TEXT
        );
        CREATE TABLE IF NOT EXISTS session_custom_title (
            session_id   TEXT PRIMARY KEY,
            custom_title TEXT
        );
        CREATE TABLE IF NOT EXISTS session_agent_name (
            session_id TEXT PRIMARY KEY,
            agent_name TEXT
        );
        CREATE TABLE IF NOT EXISTS session_entrypoint (
            session_id       TEXT PRIMARY KEY,
            entrypoint        TEXT,
            cwd               TEXT,
            first_user_label  TEXT
        );
        CREATE TABLE IF NOT EXISTS file_aug_state (
            path       TEXT PRIMARY KEY,
            mtime      REAL,
            lines      INTEGER,
            last_label TEXT
        );
        """
    )
    conn.commit()


def _iter_new_lines(filepath, start_line):
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i <= start_line:
                continue
            yield i, line


def augment_scan_file(conn, filepath, old_lines, old_last_label):
    """處理一個 jsonl 檔案裡「比 old_lines 新」的那些行，回 (新 line_count, 新 last_label)。"""
    last_label = old_last_label or USER_LABEL
    session_id = None
    line_count = old_lines
    had_first_label = False

    for i, raw in _iter_new_lines(filepath, old_lines):
        line_count = i
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue

        rtype = record.get("type")
        sid = record.get("sessionId")
        if sid:
            session_id = sid

        entrypoint = record.get("entrypoint")
        cwd = record.get("cwd")
        if sid and (entrypoint or cwd):
            conn.execute(
                "INSERT INTO session_entrypoint (session_id, entrypoint, cwd, first_user_label) "
                "VALUES (?, ?, ?, NULL) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "entrypoint = COALESCE(excluded.entrypoint, session_entrypoint.entrypoint), "
                "cwd = COALESCE(excluded.cwd, session_entrypoint.cwd)",
                (sid, entrypoint, cwd),
            )

        if rtype == "custom-title":
            title = record.get("customTitle")
            if sid and title:
                conn.execute(
                    "INSERT INTO session_custom_title (session_id, custom_title) VALUES (?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET custom_title = excluded.custom_title",
                    (sid, title),
                )
            continue

        if rtype == "agent-name":
            name = record.get("agentName")
            if sid and name:
                conn.execute(
                    "INSERT INTO session_agent_name (session_id, agent_name) VALUES (?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET agent_name = excluded.agent_name",
                    (sid, name),
                )
            continue

        if rtype == "user":
            text, is_tool_result = _extract_user_text_or_skip(record)
            if is_tool_result:
                continue
            last_label = classify_trigger_text(text)
            if sid:
                row = conn.execute(
                    "SELECT first_user_label FROM session_entrypoint WHERE session_id = ?",
                    (sid,),
                ).fetchone()
                if row is not None and row[0] is None:
                    conn.execute(
                        "UPDATE session_entrypoint SET first_user_label = ? WHERE session_id = ?",
                        (last_label, sid),
                    )
            continue

        if rtype == "assistant":
            msg = record.get("message") or {}
            message_id = msg.get("id")
            if message_id:
                conn.execute(
                    "INSERT INTO trigger_meta (message_id, label) VALUES (?, ?) "
                    "ON CONFLICT(message_id) DO UPDATE SET label = excluded.label",
                    (message_id, last_label),
                )
            continue

    return line_count, last_label


def augment_scan(conn):
    """對所有 jsonl 跑一次自己的擴充掃描（entrypoint/agentName/customTitle/觸發標籤）。
    跟 vendor scanner 一樣用 mtime 增量，只讀沒讀過的新行。"""
    init_extra_tables(conn)
    files = []
    for d in PROJECTS_DIRS:
        if d.exists():
            files.extend(str(p) for p in d.glob("**/*.jsonl"))
    files.sort()

    for filepath in files:
        try:
            mtime = os.path.getmtime(filepath)
        except OSError:
            continue
        row = conn.execute(
            "SELECT mtime, lines, last_label FROM file_aug_state WHERE path = ?",
            (filepath,),
        ).fetchone()
        if row and abs(row[0] - mtime) < 0.01:
            continue
        old_lines = row[1] if row else 0
        old_label = row[2] if row else None
        new_lines, new_label = augment_scan_file(conn, filepath, old_lines, old_label)
        conn.execute(
            "INSERT INTO file_aug_state (path, mtime, lines, last_label) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, lines=excluded.lines, last_label=excluded.last_label",
            (filepath, mtime, new_lines, new_label),
        )
        conn.commit()


def full_scan():
    """跑一次完整掃描：先用 vendor scanner 建 sessions/turns（token 去重用
    message.id，沿用它的邏輯），再跑自己的擴充掃描補 entrypoint/agentName/
    customTitle/觸發標籤。回傳 vendor scan 的統計字典。

    projects_dirs=PROJECTS_DIRS is passed explicitly — without it, vendor
    scanner.scan() falls back to ITS OWN hardcoded default
    (~/.claude/projects + the Xcode assistant's projects folder) and
    AGENT_USAGE_PROJECTS_DIR would silently do nothing for the main scan
    (it would still only affect this file's own augment_scan()/
    find_session_jsonl(), which do already use PROJECTS_DIRS)."""
    result = vscanner.scan(verbose=False, projects_dirs=[str(d) for d in PROJECTS_DIRS])
    conn = vscanner.get_db(vscanner.DB_PATH)
    try:
        augment_scan(conn)
    finally:
        conn.close()
    return result


def get_db():
    return vscanner.get_db(DB_PATH)


# ---------------------------------------------------------------------------
# 模型欄追加（102802）：最後一則 assistant 之後，有沒有 /model 留下的切換紀錄。
# 只比對這一個固定句型「Set model to `X`」，只回 X 這一小段；不回傳、不印、
# 不存其他對話文字——跟本檔檔頭那條規矩（從不寫原始文字）一致。
# ---------------------------------------------------------------------------
MODEL_SWITCH_RE = re.compile(r"Set model to `([^`]+)`")


def find_session_jsonl(session_id):
    """session_id → 它的 jsonl 絕對路徑字串；找不到回 None。"""
    for d in PROJECTS_DIRS:
        if not d.exists():
            continue
        for p in d.glob(f"*/{session_id}.jsonl"):
            return str(p)
    return None


def _text_blocks(content):
    """從 message.content 撈出純文字片段，只供正則比對，不對外回傳整段。"""
    texts = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                texts.append(item.get("text") or "")
            elif item.get("type") == "tool_result":
                c2 = item.get("content")
                if isinstance(c2, str):
                    texts.append(c2)
                elif isinstance(c2, list):
                    for it2 in c2:
                        if isinstance(it2, dict) and it2.get("type") == "text":
                            texts.append(it2.get("text") or "")
    return texts


def model_switch_after_last_assistant(session_id):
    """這段對話最後一則 assistant 之後，有沒有使用者打 /model 留下
    「Set model to `X`」的紀錄；有就回 X（切到哪個模型），沒有回 None。"""
    path = find_session_jsonl(session_id)
    if not path:
        return None
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return None
    last_assistant_idx = -1
    for i, d in enumerate(rows):
        if d.get("type") == "assistant":
            last_assistant_idx = i
    switched_to = None
    for d in rows[last_assistant_idx + 1:]:
        if d.get("type") != "user":
            continue
        msg = d.get("message") or {}
        for t in _text_blocks(msg.get("content")):
            m = MODEL_SWITCH_RE.search(t)
            if m:
                switched_to = m.group(1)
    return switched_to
