"""Outcome sync: partial unit trims and JSONL fields."""

from __future__ import annotations

from unittest.mock import patch

from tradingagents.portfolio_advisor import outcome_sync, state


def _cfg(tmp_path):
    return {"portfolio_advisor_dir": str(tmp_path / "pa"), "event_log_path": str(tmp_path / "ev.jsonl")}


@patch("tradingagents.portfolio_advisor.outcome_sync.append_event")
def test_partial_close_emits_when_units_drop(mock_append, tmp_path):
    cfg = _cfg(tmp_path)
    st = state.default_state()
    st["last_book_units_by_ticker"] = {"TEAM": 100.0}
    state.save_state(cfg, st)
    rows = [{"symbolFull": "TEAM", "openRate": 50.0, "isBuy": True, "units": 65.0}]
    outcome_sync.auto_close_outcomes(cfg, {"TEAM"}, rows=rows)
    types = [c.args[1]["event_type"] for c in mock_append.call_args_list]
    assert "partial_close_outcome" in types


@patch("tradingagents.portfolio_advisor.outcome_sync.append_event")
def test_outcome_recorded_carries_pnl_source(mock_append, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["memory_log_path"] = str(tmp_path / "mem.md")
    p = tmp_path / "mem.md"
    p.write_text(
        "[2026-01-01 | ZZ | Buy | pending]\n\nDECISION:\nRating: Buy\n\n<!-- ENTRY_END -->\n\n",
        encoding="utf-8",
    )
    with patch("tradingagents.portfolio_advisor.outcome_sync._yf_close_on_or_after", return_value=10.0):
        with patch("tradingagents.portfolio_advisor.outcome_sync._yf_last_close", return_value=11.0):
            outcome_sync.auto_close_outcomes(cfg, set(), rows=[])
    rec = [c for c in mock_append.call_args_list if c.args[1].get("event_type") == "outcome_recorded"]
    assert rec
    kd = rec[0].args[1]["key_data"]
    assert kd.get("pnl_source") == "yfinance_proxy"
