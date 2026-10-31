"""
live.py — 找出「現在開著」的 Claude 視窗，並盡量把每個 pid 對到一個 session_id。

只用 ps / lsof 看行程表與 pid 的 cwd；對不上 session 的留在「認不出是誰」，
不丟掉、不瞎猜硬塞一個名字。
"""

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# Optional, pluggable: a path to a script you run yourself that prints
# lines like "<line name>：<anything>（<8-hex session id>，...報到）" — used
# to label an open window with a human-chosen name instead of its raw
# 8-character session id. Empty by default (off); nothing is called and
# every window just shows its session id.
INBOX_CLAIM = os.environ.get("AGENT_USAGE_LINE_NAMES_CMD", "")


def _parse_etime(s):
    """ps 的 ELAPSED 欄位，格式 [[dd-]hh:]mm:ss，回傳秒數。"""
    s = s.strip()
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = s.split(":")
    parts = [int(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts[-3], parts[-2], parts[-1]
    return days * 86400 + h * 3600 + m * 60 + sec


def list_claude_processes():
    """回傳現在在跑、有終端機（tty != ??）、執行檔是 claude/claude.exe 的行程。
    每筆：{pid, elapsed_s, start_epoch, tty, command, resume_arg}"""
    out = subprocess.run(
        ["ps", "-eo", "pid,etime,tty,command"],
        capture_output=True, text=True, check=False,
    ).stdout
    lines = out.splitlines()[1:]
    now = datetime.now().timestamp()
    procs = []
    for line in lines:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_s, etime_s, tty, command = parts
        if tty == "??":
            continue
        first_tok = command.split()[0] if command.split() else ""
        base = os.path.basename(first_tok)
        if base not in ("claude", "claude.exe"):
            continue
        # 2026-10-28 他選 3：bg-spare / bg-pty-host / daemon 是 Claude 的備用與背景殼，不是他的視窗，別算成一列
        if re.search(r"\s--?(bg-spare|bg-pty-host)\b|\sbg-spare\b|\sbg-pty-host\b|\sdaemon\s", command):
            continue
        try:
            pid = int(pid_s)
            elapsed = _parse_etime(etime_s)
        except ValueError:
            continue
        start_epoch = now - elapsed
        resume_arg = None
        flag = "--session-id"
        m = re.search(r"--session-id\s+(\S+)", command)
        if not m:
            m = re.search(r"--resume\s+(\S+)", command)
            flag = "--resume"
        if m:
            resume_arg = m.group(1)
        procs.append({
            "pid": pid,
            "elapsed_s": elapsed,
            "start_epoch": start_epoch,
            "tty": tty,
            "command": command,
            "resume_flag": flag if resume_arg else None,
            "resume_arg": resume_arg,
        })
    return procs


def pid_cwd(pid):
    """用 lsof 查一個 pid 現在的工作目錄；查不到回 None。"""
    try:
        out = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, check=False, timeout=5,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def resolve_session_id_from_arg(resume_arg):
    """--resume / --session-id 的值：UUID 就直接當 session_id；
    結尾 .jsonl 的路徑就取檔名當 session_id；其餘（像別名 "VP"）回 None。"""
    if not resume_arg:
        return None
    if UUID_RE.match(resume_arg):
        return resume_arg
    if resume_arg.endswith(".jsonl"):
        return os.path.splitext(os.path.basename(resume_arg))[0]
    return None


def epoch_to_iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def load_line_names():
    """Runs AGENT_USAGE_LINE_NAMES_CMD --show (if configured) and parses its
    output into (sid-prefix -> line name, line name -> sid-prefix). Returns
    two empty dicts when the hook isn't configured, or fails, or times out
    — this is optional labeling, never required for the dashboard to work."""
    if not INBOX_CLAIM:
        return {}, {}
    try:
        out = subprocess.run(
            ["python3", INBOX_CLAIM, "--show"],
            capture_output=True, text=True, check=False, timeout=10,
        ).stdout
    except Exception:
        return {}, {}
    sid_to_name = {}
    name_to_sid = {}
    pattern = re.compile(r"^(.*?)：(.*?)（([0-9a-f]{8})，.*報到）$")
    for line in out.splitlines():
        m = pattern.match(line.strip())
        if m:
            line_name, _inner_name, sid8 = m.groups()
            sid_to_name[sid8] = line_name
            name_to_sid[line_name] = sid8
    return sid_to_name, name_to_sid
