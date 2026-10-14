# Copyright 2026 Neil Manfred
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from .providers import PRICING, classify_claude_model, classify_gemini_model


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------

class TurnUsage:
    __slots__ = ("input_tokens", "output_tokens", "cache_write", "cache_read", "cost")

    def __init__(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_write: int = 0,
        cache_read: int = 0,
        cost: float = 0.0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_write = cache_write
        self.cache_read = cache_read
        self.cost = cost

    def __add__(self, other: "TurnUsage") -> "TurnUsage":
        return TurnUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write + other.cache_write,
            self.cache_read + other.cache_read,
            self.cost + other.cost,
        )


class SessionSummary:
    def __init__(self, path: Path, project_dir: str, tool: str) -> None:
        self.path = path
        self.project_dir = project_dir
        self.tool = tool
        self.usage = TurnUsage()
        self.turn_count = 0
        self.mtime: float = 0.0
        self.last_model: str = ""


# ---------------------------------------------------------------------------
# Claude Code log parsing
# ---------------------------------------------------------------------------

def _claude_log_dir() -> Path:
    return Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))


def _iter_claude_sessions(max_age_s: float | None = None) -> Iterator[SessionSummary]:
    now = time.time()
    base = _claude_log_dir()
    if not base.exists():
        return
    for path in base.glob("projects/**/*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if max_age_s is not None and (now - mtime) > max_age_s:
            continue
        sess = _parse_claude_session(path)
        if sess is not None:
            yield sess


def _parse_claude_session(path: Path) -> SessionSummary | None:
    project_dir = ""
    turns: dict[str, TurnUsage] = {}
    last_model = ""

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not project_dir:
                    project_dir = entry.get("cwd") or entry.get("project") or ""
                msg = entry.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                msg_id = msg.get("id")
                if not usage or not msg_id:
                    continue
                model = msg.get("model", "claude-sonnet")
                last_model = model
                tier = classify_claude_model(model)
                p = PRICING[tier]
                inp = int(usage.get("input_tokens", 0))
                out = int(usage.get("output_tokens", 0))
                cw = int(usage.get("cache_creation_input_tokens", 0))
                cr = int(usage.get("cache_read_input_tokens", 0))
                cost = (
                    inp * p["input"]
                    + out * p["output"]
                    + cw * p.get("cache_write", 0.0)
                    + cr * p.get("cache_read", 0.0)
                ) / 1_000_000
                turns[msg_id] = TurnUsage(inp, out, cw, cr, cost)
    except OSError:
        return None

    if not turns:
        return None

    sess = SessionSummary(path, project_dir, "claude")
    sess.mtime = path.stat().st_mtime
    sess.last_model = last_model
    for t in turns.values():
        sess.usage = sess.usage + t
        sess.turn_count += 1
    return sess


# ---------------------------------------------------------------------------
# Gemini CLI log parsing
# ---------------------------------------------------------------------------

def _gemini_log_dir() -> Path:
    return Path(os.environ.get("GEMINI_CLI_HOME", Path.home() / ".gemini"))


def _load_gemini_project_map() -> dict[str, str]:
    gemini_dir = _gemini_log_dir()
    path = gemini_dir / "projects.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {v: k for k, v in data.get("projects", {}).items()}
    except Exception:
        return {}


def _iter_gemini_sessions(max_age_s: float | None = None) -> Iterator[SessionSummary]:
    now = time.time()
    base = _gemini_log_dir()
    if not base.exists():
        return
    project_map = _load_gemini_project_map()
    patterns = ["session-*.jsonl", "session-*.json"]
    paths: list[Path] = []
    for p in patterns:
        paths.extend(base.rglob(p))
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if max_age_s is not None and (now - mtime) > max_age_s:
            continue
        sess = _parse_gemini_session(path, project_map)
        if sess is not None:
            yield sess


def _parse_gemini_session(path: Path, project_map: dict[str, str]) -> SessionSummary | None:
    short_name = ""
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "chats" and i > 0:
            short_name = parts[i - 1]
            break
    if not short_name and len(path.parents) >= 2:
        short_name = path.parents[1].name

    project_dir = project_map.get(short_name, f"~/.gemini/tmp/{short_name}" if short_name else "")
    turns: dict[str, TurnUsage] = {}
    last_model = ""

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_id = entry.get("id")
                if not msg_id or "tokens" not in entry:
                    continue
                model = entry.get("model", "flash")
                last_model = model
                tier = classify_gemini_model(model)
                p = PRICING[tier]
                tokens = entry["tokens"]
                inp = int(tokens.get("input", 0))
                out = int(tokens.get("output", 0))
                cached = int(tokens.get("cached", 0))
                cost = (
                    inp * p["input"]
                    + out * p["output"]
                    + cached * p.get("cached", 0.0)
                ) / 1_000_000
                turns[msg_id] = TurnUsage(inp, out, 0, cached, cost)
    except OSError:
        return None

    if not turns:
        return None

    sess = SessionSummary(path, project_dir, "gemini")
    sess.mtime = path.stat().st_mtime
    sess.last_model = last_model
    for t in turns.values():
        sess.usage = sess.usage + t
        sess.turn_count += 1
    return sess


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class UsageSummary:
    def __init__(self) -> None:
        self.sessions: list[SessionSummary] = []

    def total_cost(self) -> float:
        return sum(s.usage.cost for s in self.sessions)

    def total_input_tokens(self) -> int:
        return sum(s.usage.input_tokens for s in self.sessions)

    def total_output_tokens(self) -> int:
        return sum(s.usage.output_tokens for s in self.sessions)

    def by_tool(self, tool: str) -> list[SessionSummary]:
        return [s for s in self.sessions if s.tool == tool]

    def by_project(self) -> dict[str, list[SessionSummary]]:
        result: dict[str, list[SessionSummary]] = defaultdict(list)
        for s in self.sessions:
            result[s.project_dir].append(s)
        return dict(result)


def gather_all(max_age_s: float | None = None) -> UsageSummary:
    summary = UsageSummary()
    for sess in _iter_claude_sessions(max_age_s):
        summary.sessions.append(sess)
    for sess in _iter_gemini_sessions(max_age_s):
        summary.sessions.append(sess)
    return summary


def gather_for_cwd(cwd: str, max_age_s: float | None = None, exclude_path: Path | None = None) -> SessionSummary | None:
    """Returns the most recently modified session for the given CWD, or None."""
    cwd_resolved = Path(cwd).resolve()
    best: SessionSummary | None = None

    for sess in _iter_claude_sessions(max_age_s):
        if exclude_path and sess.path.resolve() == exclude_path.resolve():
            continue
        if sess.project_dir:
            try:
                if Path(sess.project_dir).resolve() == cwd_resolved:
                    if best is None or sess.mtime > best.mtime:
                        best = sess
            except Exception:
                pass

    for sess in _iter_gemini_sessions(max_age_s):
        if exclude_path and sess.path.resolve() == exclude_path.resolve():
            continue
        if sess.project_dir:
            try:
                p = Path(sess.project_dir).expanduser().resolve()
                if p == cwd_resolved:
                    if best is None or sess.mtime > best.mtime:
                        best = sess
            except Exception:
                pass

    return best
