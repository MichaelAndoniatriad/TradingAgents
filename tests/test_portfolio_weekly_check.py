"""Tests for lightweight weekly portfolio check."""

from __future__ import annotations

from unittest.mock import patch

from tradingagents.portfolio_advisor import state, weekly_check


def _cfg(tmp_path):
    return {"portfolio_advisor_dir": str(tmp_path / "pa")}


@patch("tradingagents.portfolio_advisor.weekly_check.outcome_sync.auto_close_outcomes")
@patch("tradingagents.portfolio_advisor.weekly_check.etoro_scan.fetch_portfolio_rows")
def test_weekly_check_cancels_jobs_for_sold_tickers(mock_fetch, _mock_sync, tmp_path):
    cfg = _cfg(tmp_path)
    mock_fetch.return_value = ({}, "summary", ["AAPL"], [])

    st = state.default_state()
    st["last_portfolio_tickers"] = ["NVDA", "AAPL"]
    st["jobs"] = [
        {
            "id": "j1",
            "ticker": "NVDA",
            "scheduled_at": "2099-01-01T12:00:00+00:00",
            "kind": "deep_research",
            "reason": "t",
            "status": "pending",
            "created_at": "2098-01-01T00:00:00+00:00",
        },
        {
            "id": "j2",
            "ticker": "AAPL",
            "scheduled_at": "2099-01-02T12:00:00+00:00",
            "kind": "deep_research",
            "reason": "t",
            "status": "pending",
            "created_at": "2098-01-01T00:00:00+00:00",
        },
    ]
    state.save_state(cfg, st)

    body, attention, live = weekly_check.run_weekly_quick_check(cfg)
    assert live == {"AAPL"}
    assert "NVDA" in body or "j1" in body or "cancelled" in body.lower()
    st2 = state.load_state(cfg)
    statuses = {j["id"]: j["status"] for j in st2["jobs"]}
    assert statuses["j1"] == "cancelled"
    assert statuses["j2"] == "pending"
    assert attention is True
    assert st2["last_portfolio_tickers"] == ["AAPL"]
