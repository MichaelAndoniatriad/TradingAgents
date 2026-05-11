"""Tests for JSONL event log helpers."""

from __future__ import annotations

from pathlib import Path

from tradingagents.agents.utils import event_log


def test_append_and_format_tail(tmp_path):
    cfg = {"event_log_path": str(tmp_path / "ev.jsonl")}
    event_log.append_event(cfg, {"ticker": "NOW", "event_type": "test", "key_data": {"x": 1}})
    txt = event_log.format_recent_events_for_ticker(cfg, "NOW", days=30, max_events=5)
    assert "NOW" in txt
    assert "test" in txt


def test_format_tail_prefers_weighted_event_types(tmp_path):
    cfg = {"event_log_path": str(tmp_path / "w.jsonl")}
    p = Path(cfg["event_log_path"])
    p.write_text(
        "\n".join(
            [
                '{"timestamp": "2026-01-02T00:00:00+00:00", "ticker": "ZZ", "event_type": "advisor_replan_skipped", "key_data": {}}',
                '{"timestamp": "2026-01-01T00:00:00+00:00", "ticker": "ZZ", "event_type": "full_graph_decision", "key_data": {"rating": "Buy"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    txt = event_log.format_recent_events_for_ticker(cfg, "ZZ", days=9999, max_events=5)
    assert "full_graph_decision" in txt
    assert txt.index("full_graph_decision") < txt.index("advisor_replan_skipped")


def test_load_events_for_review_filters(tmp_path):
    cfg = {"event_log_path": str(tmp_path / "ev2.jsonl")}
    p = Path(cfg["event_log_path"])
    p.write_text(
        '{"timestamp": "2099-01-01T00:00:00+00:00", "ticker": "A", "event_type": "old"}\n',
        encoding="utf-8",
    )
    rows = event_log.load_events_for_review(cfg, days=120)
    assert len(rows) == 1
