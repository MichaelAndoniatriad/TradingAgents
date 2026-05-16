"""Tests for tradingagents.llm_clients.cost_report aggregation logic."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.llm_clients.cost_report import (
    load_records,
    daily_spend,
    model_spend,
    top_calls,
    null_cost_count,
    total_spend,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


SAMPLE_RECORDS = [
    {"ts": _ts(0), "model": "openai/gpt-4o", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost_usd": 0.001800, "tags": [], "run_id": "a", "parent_run_id": None},
    {"ts": _ts(1), "model": "deepseek/deepseek-r1", "prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300, "cost_usd": 0.000330, "tags": [], "run_id": "b", "parent_run_id": None},
    {"ts": _ts(2), "model": "openai/gpt-4o", "prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700, "cost_usd": 0.003250, "tags": [], "run_id": "c", "parent_run_id": None},
    {"ts": _ts(3), "model": "unknown-future-model", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost_usd": None, "tags": [], "run_id": "d", "parent_run_id": None},
    {"ts": _ts(10), "model": "openai/gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500, "cost_usd": 0.000450, "tags": [], "run_id": "e", "parent_run_id": None},
]


def test_load_and_filter_by_days():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    _write_jsonl(path, SAMPLE_RECORDS)

    all_recs = load_records(path=path)
    assert len(all_recs) == 5

    recent = load_records(path=path, days=5)
    assert len(recent) == 4  # record 5 is 10 days ago

    very_recent = load_records(path=path, days=1)
    # days=1 means cutoff is 1 day ago; record at _ts(0) qualifies but _ts(1) is borderline
    assert len(very_recent) >= 1

    path.unlink(missing_ok=True)


def test_daily_spend_and_model_spend_grouping():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    _write_jsonl(path, SAMPLE_RECORDS)
    recs = load_records(path=path)

    # daily_spend sums correctly
    days = daily_spend(recs)
    total = sum(days.values())
    expected = sum(r["cost_usd"] for r in SAMPLE_RECORDS if r["cost_usd"] is not None)
    assert abs(total - expected) < 1e-9

    # model_spend: gpt-4o should be top (two calls, highest combined cost)
    ms = model_spend(recs)
    top_model, top_count, top_cost = ms[0]
    assert top_model == "openai/gpt-4o"
    assert top_count == 2
    assert abs(top_cost - (0.001800 + 0.003250)) < 1e-9

    path.unlink(missing_ok=True)


def test_top_calls_and_null_count():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    _write_jsonl(path, SAMPLE_RECORDS)
    recs = load_records(path=path)

    # top_calls: most expensive first, null treated as 0
    top = top_calls(recs, 3)
    assert len(top) == 3
    assert top[0]["cost_usd"] == 0.003250  # gpt-4o second call

    # null_cost_count
    assert null_cost_count(recs) == 1

    # total_spend excludes nulls
    assert abs(total_spend(recs) - (0.001800 + 0.000330 + 0.003250 + 0.000450)) < 1e-9

    path.unlink(missing_ok=True)
