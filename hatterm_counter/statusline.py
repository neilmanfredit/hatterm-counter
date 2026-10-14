# Copyright 2026 Neil Manfred
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .parser import SessionSummary, gather_for_cwd
from .providers import classify_claude_model, PRICING

# ANSI colour codes
_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "grey": "\033[90m",
    "gold": "\033[38;5;178m",
    "cyan": "\033[36m",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    return os.environ.get(name, "1" if default else "0") == "1"


def _bar(pct: int, width: int = 10) -> tuple[str, str]:
    """Returns (bar_string, colour) for the given usage percentage."""
    filled = max(0, min(width, int(pct * width / 100)))
    bar = "█" * filled + "░" * (width - filled)
    colour = _C["red"] if pct >= 90 else (_C["yellow"] if pct >= 70 else _C["green"])
    return bar, colour


def _git_status(cwd: str) -> str:
    """Returns a formatted git branch + change summary, or empty string."""
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=2
        )
        if r.returncode != 0:
            return ""
        branch = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True, timeout=2
        ).stdout.strip()
        if not branch:
            return ""
        staged = len(subprocess.run(
            ["git", "-C", cwd, "diff", "--cached", "--numstat"],
            capture_output=True, text=True, timeout=2
        ).stdout.strip().splitlines())
        modified = len(subprocess.run(
            ["git", "-C", cwd, "diff", "--numstat"],
            capture_output=True, text=True, timeout=2
        ).stdout.strip().splitlines())
        parts = [f"\U0001f33f {branch}"]
        if staged:
            parts.append(f"{_C['green']}+{staged}{_C['reset']}")
        if modified:
            parts.append(f"{_C['yellow']}~{modified}{_C['reset']}")
        return " " + " ".join(parts)
    except Exception:
        return ""


def format_statusline_from_session(sess: SessionSummary, cwd: str) -> str:
    """Renders a compact multi-line statusline string for the given session."""
    bar_width = _env_int("CC_BAR_WIDTH", 10)
    show_git = _env_bool("CC_SHOW_GIT")
    show_cost = _env_bool("CC_SHOW_COST")

    dirname = Path(cwd).name or "~"
    tool_label = _tool_label(sess)
    git_part = _git_status(cwd) if show_git and cwd else ""
    line1 = f"{_C['gold']}[{tool_label}]{_C['reset']} \U0001f4c1 {dirname}{git_part}"

    pct, input_tok, ctx_size = _context_pct(sess)
    bar, colour = _bar(pct, bar_width)
    tok_h = f"{input_tok / 1000:.1f}k"
    ctx_h = f"{ctx_size / 1000:.0f}k"
    line2 = f"{colour}{bar}{_C['reset']} {pct}% ({tok_h}/{ctx_h})"
    if show_cost:
        line2 += f" | {_C['grey']}${sess.usage.cost:.2f}{_C['reset']}"

    lines = [f"  {line1}", f"  {line2}"]
    return "\n".join(lines)


def _tool_label(sess: SessionSummary) -> str:
    if sess.tool == "gemini":
        return "Gemini Pro" if "pro" in sess.last_model.lower() else "Gemini Flash"
    if sess.tool == "claude":
        m = sess.last_model.lower()
        if "opus" in m:
            return "Claude Opus"
        if "haiku" in m:
            return "Claude Haiku"
        return "Claude Sonnet"
    return sess.tool.title()


def _context_pct(sess: SessionSummary) -> tuple[int, int, int]:
    """Returns (used_pct, input_tokens, ctx_window_size)."""
    if sess.tool == "gemini":
        ctx = 2_000_000 if "pro" in sess.last_model.lower() else 1_000_000
    else:
        ctx = 200_000
    inp = sess.usage.input_tokens
    pct = int((inp / ctx) * 100) if ctx > 0 else 0
    return pct, inp, ctx


def format_statusline_for_cwd(cwd: str | None = None) -> str:
    """Returns a status string for the given CWD (defaults to os.getcwd())."""
    if not cwd:
        cwd = os.getcwd()
    max_age = _env_int("CC_MAX_AGE_DAYS", 7) * 86400
    sess = gather_for_cwd(cwd, max_age_s=max_age)
    if not sess:
        return f"  {_C['grey']}context: warming up…{_C['reset']}"
    return format_statusline_from_session(sess, cwd)


def format_claude_code_statusline(data: dict) -> str:
    """Formats output for Claude Code's statusLine hook payload."""
    bar_width = _env_int("CC_BAR_WIDTH", 10)
    show_git = _env_bool("CC_SHOW_GIT")
    show_cost = _env_bool("CC_SHOW_COST")
    show_rate_limits = _env_bool("CC_SHOW_RATE_LIMITS")

    model = data.get("model", {}).get("display_name", "Claude")
    cwd = data.get("workspace", {}).get("current_dir", "")
    dirname = Path(cwd).name if cwd else "~"
    git_part = _git_status(cwd) if show_git and cwd else ""
    line1 = f"{_C['gold']}[{model}]{_C['reset']} \U0001f4c1 {dirname}{git_part}"

    pct_raw = data.get("context_window", {}).get("used_percentage")
    if pct_raw is None or pct_raw == "null":
        line2 = f"{_C['grey']}context: warming up…{_C['reset']}"
    else:
        pct = int(float(pct_raw))
        tok_in = data.get("context_window", {}).get("total_input_tokens", 0)
        ctx_sz = data.get("context_window", {}).get("context_window_size", 200_000)
        bar, colour = _bar(pct, bar_width)
        line2 = f"{colour}{bar}{_C['reset']} {pct}% ({tok_in / 1000:.1f}k/{ctx_sz / 1000:.0f}k)"
        if show_cost:
            cost = data.get("cost", {}).get("total_cost_usd", 0.0)
            line2 += f" | {_C['grey']}${cost:.2f}{_C['reset']}"

    lines = [f"  {line1}", f"  {line2}"]

    if show_rate_limits:
        line3 = _format_rate_limits(data)
        if line3:
            lines.append(f"  {line3}")

    return "\n".join(lines)


def _format_rate_limits(data: dict) -> str:
    now = time.time()
    five_h = data.get("rate_limits", {}).get("five_hour", {})
    seven_d = data.get("rate_limits", {}).get("seven_day", {})

    parts = []
    for label, bucket in [("5h", five_h), ("7d", seven_d)]:
        pct_raw = bucket.get("used_percentage")
        if pct_raw is None or pct_raw == "null":
            continue
        pct = int(float(pct_raw))
        colour = _C["red"] if pct >= 90 else (_C["yellow"] if pct >= 70 else _C["green"])
        resets_at = bucket.get("resets_at")
        countdown = _fmt_countdown(resets_at, now)
        parts.append(f"{label} {colour}{pct}%{_C['reset']}{_C['grey']}{countdown}{_C['reset']}")

    if not parts:
        return f"{_C['grey']}usage limits: warming up…{_C['reset']}"
    return f" {_C['grey']}|{_C['reset']} ".join(parts)


def _fmt_countdown(resets_at, now: float) -> str:
    if resets_at is None or resets_at == "null":
        return ""
    try:
        diff = max(0, int(float(resets_at)) - int(now))
        h = diff // 3600
        m = (diff % 3600) // 60
        return f" ({h}h{m:02d}m)" if h > 0 else f" ({m}m)"
    except Exception:
        return ""
