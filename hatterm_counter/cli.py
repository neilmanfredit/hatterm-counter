# Copyright 2026 Neil Manfred
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .parser import gather_all, gather_for_cwd
from .providers import PRICING
from .statusline import format_claude_code_statusline, format_statusline_for_cwd


_GOLD = "\033[38;5;178m"
_BOLD = "\033[1m"
_GREY = "\033[90m"
_RESET = "\033[0m"


def _header(title: str) -> None:
    print(f"{_GOLD}┌{'─' * 68}┐{_RESET}")
    print(f"{_GOLD}│{_BOLD}{title.center(68)}{_RESET}{_GOLD}│{_RESET}")
    print(f"{_GOLD}└{'─' * 68}┘{_RESET}")


def _section(title: str) -> str:
    prefix = f"┌── {title} "
    dashes = 72 - len(prefix)
    return f"{_GOLD}{_BOLD}{prefix}{'─' * dashes}┐{_RESET}"


def run_dashboard() -> None:
    summary = gather_all()
    _header("AI COGNITIVE RESOURCE REPORT")
    print(f"{_GREY}Report Date: {time.strftime('%A, %d %B %Y')}{_RESET}\n")

    claude_sessions = summary.by_tool("claude")
    gemini_sessions = summary.by_tool("gemini")

    c_in = sum(s.usage.input_tokens for s in claude_sessions)
    c_out = sum(s.usage.output_tokens for s in claude_sessions)
    c_cw = sum(s.usage.cache_write for s in claude_sessions)
    c_cr = sum(s.usage.cache_read for s in claude_sessions)
    c_cost = sum(s.usage.cost for s in claude_sessions)

    g_in = sum(s.usage.input_tokens for s in gemini_sessions)
    g_out = sum(s.usage.output_tokens for s in gemini_sessions)
    g_cached = sum(s.usage.cache_read for s in gemini_sessions)
    g_cost = sum(s.usage.cost for s in gemini_sessions)

    print(_section("CLAUDE CODE RESOURCES"))
    print(f"│  Sessions Tracked: {len(claude_sessions):<50} │")
    print(f"│  Input Tokens:     {f'{c_in:,}':<50} │")
    print(f"│  Output Tokens:    {f'{c_out:,}':<50} │")
    print(f"│  Cache Created:    {f'{c_cw:,}':<50} │")
    print(f"│  Cache Read Hits:  {f'{c_cr:,}':<50} │")
    print(f"│  Estimated Cost:   ${c_cost:,.2f}{' ' * max(0, 50 - len(f'${c_cost:,.2f}'))} │")
    print(f"{_GOLD}└{'─' * 71}┘{_RESET}\n")

    print(_section("GEMINI CLI RESOURCES"))
    print(f"│  Sessions Tracked: {len(gemini_sessions):<50} │")
    print(f"│  Input Tokens:     {f'{g_in:,}':<50} │")
    print(f"│  Output Tokens:    {f'{g_out:,}':<50} │")
    print(f"│  Context Cached:   {f'{g_cached:,}':<50} │")
    print(f"│  Estimated Cost:   ${g_cost:,.2f}{' ' * max(0, 50 - len(f'${g_cost:,.2f}'))} │")
    print(f"{_GOLD}└{'─' * 71}┘{_RESET}\n")

    total_cost = c_cost + g_cost
    print(_section("GLOBAL ALLOCATION"))
    print(f"│  Total Sessions:   {len(summary.sessions):<50} │")
    print(f"│  Combined Cost:    ${total_cost:,.2f}{' ' * max(0, 50 - len(f'${total_cost:,.2f}'))} │")
    print(f"{_GOLD}└{'─' * 71}┘{_RESET}\n")

    # Per-project breakdown
    print(f"{_BOLD}PROJECT ALLOCATION ANALYSIS{_RESET}")
    print(f"{_GREY}{'─' * 70}{_RESET}")
    print(f"{_BOLD}{'Project':<36} {'Tool':<10} {'Sessions':<10} {'Est. Cost':<12}{_RESET}")
    print(f"{_GREY}{'─' * 70}{_RESET}")
    by_proj = summary.by_project()
    rows = []
    for proj, sessions in by_proj.items():
        for tool in ("claude", "gemini"):
            tool_sessions = [s for s in sessions if s.tool == tool]
            if not tool_sessions:
                continue
            cost = sum(s.usage.cost for s in tool_sessions)
            rows.append((proj, tool, len(tool_sessions), cost))
    rows.sort(key=lambda r: r[3], reverse=True)
    last_proj = None
    for proj, tool, count, cost in rows:
        label = _fmt_path(proj)
        if len(label) > 34:
            label = label[:31] + "..."
        proj_col = "" if proj == last_proj else label
        last_proj = proj
        print(f"{proj_col:<36} {tool.title():<10} {count:<10} ${cost:.2f}")
    print(f"{_GREY}{'─' * 70}{_RESET}")


def _fmt_path(path_str: str) -> str:
    if not path_str:
        return "Global / Unknown"
    try:
        p = Path(path_str).resolve()
        home = Path.home().resolve()
        if p == home:
            return "~"
        if home in p.parents:
            return f"~/{p.relative_to(home)}"
        return str(p)
    except Exception:
        return path_str


def run_statusline() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print(f"  \033[90mcontext: warming up…\033[0m")
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  \033[90mcontext: warming up…\033[0m")
        return

    if "hook_event_name" in data:
        _handle_gemini_hook(data)
    else:
        print(format_claude_code_statusline(data))


def _handle_gemini_hook(data: dict) -> None:
    event = data.get("hook_event_name")
    cwd = data.get("cwd", os.getcwd())
    if event in ("SessionStart", "AfterAgent"):
        status = format_statusline_for_cwd(cwd)
        sys.stderr.write(status + "\n")
        sys.stderr.flush()
        print(json.dumps({"systemMessage": status}))
    else:
        print(json.dumps({}))


def main() -> None:
    if sys.stdin.isatty():
        args = sys.argv[1:]
        if "--statusline" in args or "--compact" in args or "-s" in args:
            cwd = None
            for i, arg in enumerate(args):
                if arg in ("--cwd", "-C") and i + 1 < len(args):
                    cwd = args[i + 1]
            print(format_statusline_for_cwd(cwd))
            return
        run_dashboard()
        return
    run_statusline()
