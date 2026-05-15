# tests/test_clerk_monthly.py

import json
from pathlib import Path
from unittest.mock import patch

from tradingagents.clerk.monthly import load_monthly_candidates, run_monthly_lookout


def test_load_monthly_candidates(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps({"candidates": ["aa", "bb"], "theme": "test"}),
        encoding="utf-8",
    )
    t, theme = load_monthly_candidates(p)
    assert t == ["AA", "BB"]
    assert theme == "test"


def test_monthly_lookout_gates_candidates_before_deep_runs(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "candidates": [
                    {"ticker": "OWND", "reason": "Already held", "priority": 1, "liquidity_ok": True},
                    {
                        "ticker": "ASML",
                        "reason": "Semicap monopoly candidate with clear portfolio role",
                        "priority": 2,
                        "liquidity_ok": True,
                        "policy_ok": True,
                    },
                ],
                "theme": "test",
            }
        ),
        encoding="utf-8",
    )
    cfg = {
        "results_dir": str(tmp_path / "results"),
        "data_cache_dir": str(tmp_path / "cache"),
        "portfolio_advisor_dir": str(tmp_path / "pa"),
    }
    final_state = {"final_trade_decision": "Rating: Hold\nTest"}
    with patch("tradingagents.clerk.monthly.etoro_scan.fetch_portfolio_rows", return_value=({}, "", ["OWND"], [])):
        with patch("tradingagents.clerk.monthly.run_deep_research", return_value=(final_state, "Hold")) as deep:
            with patch("tradingagents.clerk.monthly._summarize_monthly", return_value="summary"):
                with patch("tradingagents.clerk.monthly.run_promoted_candidate_pm_comparison", return_value=0):
                    digest = run_monthly_lookout(p, trade_date="2026-05-15", max_deep=2, config=cfg)

    deep.assert_called_once()
    assert deep.call_args[0][0] == "ASML"
    assert "**OWND** — `rejected`" in digest
    assert "**ASML** — `research_queued`" in digest


def test_monthly_lookout_sends_promoted_candidates_to_pm(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "ASML",
                        "reason": "Semicap monopoly candidate with clear portfolio role",
                        "priority": 1,
                        "liquidity_ok": True,
                        "policy_ok": True,
                        "full_graph_rating": "Overweight",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cfg = {
        "results_dir": str(tmp_path / "results"),
        "data_cache_dir": str(tmp_path / "cache"),
        "portfolio_advisor_dir": str(tmp_path / "pa"),
    }
    final_state = {"final_trade_decision": "Rating: Hold\nTest"}
    with patch("tradingagents.clerk.monthly.etoro_scan.fetch_portfolio_rows", return_value=({}, "", ["NVDA"], [])):
        with patch("tradingagents.clerk.monthly.run_deep_research", return_value=(final_state, "Hold")):
            with patch("tradingagents.clerk.monthly._summarize_monthly", return_value="summary"):
                with patch("tradingagents.clerk.monthly.run_promoted_candidate_pm_comparison", return_value=1) as pm:
                    digest = run_monthly_lookout(p, trade_date="2026-05-15", max_deep=1, config=cfg)

    pm.assert_called_once()
    assert "PM candidate comparisons: 1" in digest
    assert "**ASML** — `promoted`" in digest
