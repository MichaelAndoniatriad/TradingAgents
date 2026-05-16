"""Aggregation helpers for the cost JSONL log.

Reads ~/.tradingagents/logs/cost.jsonl (or TRADINGAGENTS_COST_LOG) and
produces summary structures used by both the CLI cost-report command and
the Streamlit Cost page.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _default_log_path() -> Path:
    override = os.environ.get("TRADINGAGENTS_COST_LOG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".tradingagents" / "logs" / "cost.jsonl"


def load_records(path: Path | None = None, days: int | None = None) -> list[dict[str, Any]]:
    """Return records from the JSONL log, optionally filtered to the last N days.

    Silently skips malformed lines. Returns [] when the file does not exist.
    """
    log_path = path or _default_log_path()
    if not log_path.exists():
        return []

    cutoff: datetime | None = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    records: list[dict[str, Any]] = []
    with log_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff is not None:
                ts_str = rec.get("ts") or ""
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            records.append(rec)
    return records


def daily_spend(records: list[dict[str, Any]]) -> dict[str, float]:
    """Return {date_str: total_cost_usd} ordered by date ascending."""
    by_day: dict[str, float] = defaultdict(float)
    for rec in records:
        cost = rec.get("cost_usd")
        if cost is None:
            continue
        ts_str = rec.get("ts") or ""
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue
        day = ts.strftime("%Y-%m-%d")
        by_day[day] += cost
    return dict(sorted(by_day.items()))


def model_spend(records: list[dict[str, Any]]) -> list[tuple[str, int, float]]:
    """Return [(model, call_count, total_cost_usd)] sorted by cost descending."""
    counts: dict[str, int] = defaultdict(int)
    costs: dict[str, float] = defaultdict(float)
    for rec in records:
        model = rec.get("model") or "unknown"
        counts[model] += 1
        cost = rec.get("cost_usd")
        if cost is not None:
            costs[model] += cost
    all_models = set(counts) | set(costs)
    result = [(m, counts[m], costs.get(m, 0.0)) for m in all_models]
    return sorted(result, key=lambda x: x[2], reverse=True)


def top_calls(records: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    """Return the N most expensive individual records (null cost treated as 0)."""
    return sorted(records, key=lambda r: r.get("cost_usd") or 0.0, reverse=True)[:n]


def null_cost_count(records: list[dict[str, Any]]) -> int:
    """Count records where cost_usd is null/None."""
    return sum(1 for r in records if r.get("cost_usd") is None)


def total_spend(records: list[dict[str, Any]]) -> float:
    """Sum of all non-null cost_usd values."""
    return sum(r["cost_usd"] for r in records if r.get("cost_usd") is not None)
