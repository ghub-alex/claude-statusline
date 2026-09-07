#!/usr/bin/env python3
"""Claude Code status line: model, directory/git branch, context usage, plan rate limits."""
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CACHE_MAX_AGE_SEC = 5
BAR_WIDTH = 10
PEAK_TZ = ZoneInfo("America/New_York")
PEAK_START_HOUR = 8
PEAK_END_HOUR = 14

RESET = "\033[0m"
GRAY = "\033[38;2;153;153;153m"
COLORS = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[38;2;167;171;237m",
    "magenta": "\033[38;2;177;73;184m",
}


def color_for_pct(pct):
    if pct >= 90:
        return COLORS["red"]
    if pct >= 70:
        return COLORS["yellow"]
    return COLORS["green"]


def format_tokens(n):
    if n is None:
        return "?"
    for div, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= div:
            val = f"{n / div:.1f}".rstrip("0").rstrip(".")
            return f"{val}{suffix}"
    return str(n)


def bar(pct, color):
    filled = int(pct * BAR_WIDTH / 100)
    filled = max(0, min(BAR_WIDTH, filled))
    return f"{color}{'▓' * filled}{GRAY}{'░' * (BAR_WIDTH - filled)}"


def format_duration(delta_sec):
    hours, rem = divmod(int(delta_sec), 3600)
    minutes = rem // 60
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def format_resets_at(epoch_sec):
    if epoch_sec is None:
        return None
    delta = epoch_sec - time.time()
    if delta <= 0:
        return "now"
    hours = int(delta) // 3600
    if hours >= 24:
        return time.strftime("%a %H:%M", time.localtime(epoch_sec))
    return format_duration(delta)


def peak_hours_status():
    now = datetime.now(PEAK_TZ)
    
    # Peak hours only exist on weekdays (Mon=0 … Fri=4)
    is_weekday = now.weekday() < 5
    
    start = now.replace(hour=PEAK_START_HOUR, minute=0, second=0, microsecond=0)
    end = now.replace(hour=PEAK_END_HOUR, minute=0, second=0, microsecond=0)
    
    # Currently in peak hours?
    if is_weekday and start <= now < end:
        remaining = (end - now).total_seconds()
        return f"{COLORS['blue']}Peak Hours{GRAY} (ends {format_duration(remaining)})"
    
    # Find the next peak start
    if is_weekday and now < start:
        # Still before today's peak
        next_start = start
    else:
        # After today's peak (or weekend) → go to the next weekday's peak
        next_start = start + timedelta(days=1)
        # Skip Saturday/Sunday
        while next_start.weekday() >= 5:
            next_start += timedelta(days=1)
    
    remaining = (next_start - now).total_seconds()
    return f"{COLORS['blue']}Off Peak{GRAY} (ends {format_duration(remaining)})"


def git_info(cwd, session_id):
    cache_file = Path(tempfile.gettempdir()) / f"statusline-git-{session_id}"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_MAX_AGE_SEC:
        try:
            branch, staged, modified = cache_file.read_text().split("|")
            return branch, int(staged), int(modified)
        except ValueError:
            pass  # cache file was read mid-write by a concurrent invocation; recompute

    branch, staged, modified = "", 0, 0
    try:
        subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--is-inside-work-tree"],
            check=True, capture_output=True, text=True,
        )
        branch = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        staged_out = subprocess.run(
            ["git", "-C", cwd, "diff", "--cached", "--numstat"],
            capture_output=True, text=True,
        ).stdout.strip()
        modified_out = subprocess.run(
            ["git", "-C", cwd, "diff", "--numstat"],
            capture_output=True, text=True,
        ).stdout.strip()
        staged = len(staged_out.splitlines()) if staged_out else 0
        modified = len(modified_out.splitlines()) if modified_out else 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    tmp_file = cache_file.with_suffix(f".{os.getpid()}.tmp")
    tmp_file.write_text(f"{branch}|{staged}|{modified}")
    tmp_file.replace(cache_file)
    return branch, staged, modified


def cached_rate_limits(session_id, rate_limits):
    cache_file = Path(tempfile.gettempdir()) / f"statusline-ratelimits-{session_id}"
    five_hour = rate_limits.get("five_hour") or {}
    seven_day = rate_limits.get("seven_day") or {}

    five_pct = five_hour.get("used_percentage")
    five_resets = five_hour.get("resets_at")
    week_pct = seven_day.get("used_percentage")
    week_resets = seven_day.get("resets_at")
    fresh = five_pct is not None or week_pct is not None

    if not fresh and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            five_pct, five_resets = cached.get("five_pct"), cached.get("five_resets")
            week_pct, week_resets = cached.get("week_pct"), cached.get("week_resets")
        except (ValueError, OSError):
            pass  # cache file missing/corrupt or read mid-write; fall back to placeholder

    if fresh:
        tmp_file = cache_file.with_suffix(f".{os.getpid()}.tmp")
        tmp_file.write_text(json.dumps({
            "five_pct": five_pct, "five_resets": five_resets,
            "week_pct": week_pct, "week_resets": week_resets,
        }))
        tmp_file.replace(cache_file)

    return five_pct, five_resets, week_pct, week_resets


def render_location(data):
    cwd = data.get("workspace", {}).get("current_dir") or data.get("cwd", "")
    dirname = Path(cwd).name or cwd
    session_id = data.get("session_id", "no-session")

    branch, staged, modified = git_info(cwd, session_id)
    if not branch:
        return f"\U0001F4C2 {COLORS['blue']}{dirname}{GRAY}"

    status_bits = []
    if staged:
        status_bits.append(f"{COLORS['green']}+{staged}{GRAY}")
    if modified:
        status_bits.append(f"{COLORS['yellow']}~{modified}{GRAY}")
    status = " " + " ".join(status_bits) if status_bits else ""
    return f"\U0001F4C2 {COLORS['blue']}{dirname}{GRAY} \U0001F33F {COLORS['magenta']}{branch}{GRAY}{status}"


def render_segments(data):
    segments = []

    context_window = data.get("context_window", {})
    ctx_pct = context_window.get("used_percentage")
    if ctx_pct is None:
        segments.append(f"ctx {bar(0, GRAY)} --%")
    else:
        pct = int(ctx_pct)
        color = color_for_pct(pct)
        used = format_tokens(context_window.get("total_input_tokens"))
        limit = format_tokens(context_window.get("context_window_size"))
        segments.append(f"ctx {bar(pct, color)}{color} {pct}%{GRAY} ({used}/{limit})")

    rate_limits = data.get("rate_limits") or {}
    session_id = data.get("session_id", "no-session")
    five_pct, five_resets, week_pct, week_resets = cached_rate_limits(session_id, rate_limits)

    if five_pct is None:
        segments.append(f"5h {bar(0, GRAY)} --%")
    else:
        pct = int(five_pct)
        color = color_for_pct(pct)
        reset_str = format_resets_at(five_resets)
        suffix = f" (resets {reset_str})" if reset_str else ""
        segments.append(f"5h {bar(pct, color)}{color} {pct}%{GRAY}{suffix}")

    if week_pct is None:
        segments.append(f"7d {bar(0, GRAY)} --%")
    else:
        pct = int(week_pct)
        color = color_for_pct(pct)
        reset_str = format_resets_at(week_resets)
        suffix = f" (resets {reset_str})" if reset_str else ""
        segments.append(f"7d {bar(pct, color)}{color} {pct}%{GRAY}{suffix}")

    segments.append(peak_hours_status())

    return segments


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("statusline: invalid input")
        return

    try:
        model = data.get("model", {}).get("display_name", "?")
        parts = [f"{COLORS['cyan']}[{model}]{GRAY}", render_location(data)]
        parts.extend(render_segments(data))
        print(GRAY + " | ".join(parts) + RESET)
    except Exception as e:
        print(f"statusline: error ({e})")


if __name__ == "__main__":
    main()
