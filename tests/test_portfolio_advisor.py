"""Unit tests for portfolio advisor state and job materialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tradingagents.portfolio_advisor import state
from tradingagents.portfolio_advisor.models import AdvisorJobSpec, AdvisorPlanResult
from tradingagents.portfolio_advisor import service as pas


def _cfg(tmp_path):
    return {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_max_jobs_per_plan": 10,
    }


def test_state_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    st = state.load_state(cfg)
    st["first_scan_complete"] = True
    st["jobs"].append(
        {
            "id": "a1",
            "ticker": "NVDA",
            "scheduled_at": "2099-01-01T12:00:00+00:00",
            "kind": "deep_research",
            "reason": "test",
            "status": "pending",
            "created_at": "2098-01-01T00:00:00+00:00",
        }
    )
    state.save_state(cfg, st)
    st2 = state.load_state(cfg)
    assert st2["first_scan_complete"] is True
    assert len(st2["jobs"]) == 1
    assert st2["jobs"][0]["ticker"] == "NVDA"


def test_cancel_all_pending(tmp_path):
    cfg = _cfg(tmp_path)
    st = state.default_state()
    st["jobs"] = [
        {"id": "1", "status": "pending", "ticker": "A"},
        {"id": "2", "status": "completed", "ticker": "B"},
    ]
    n = state.cancel_all_pending(st, "reset")
    assert n == 1
    assert st["jobs"][0]["status"] == "cancelled"
    assert st["jobs"][1]["status"] == "completed"


def test_jobs_from_plan_filters_and_caps_future():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT15:00:00+00:00")
    past = "2020-01-01T12:00:00+00:00"
    plan = AdvisorPlanResult(
        executive_summary="memo",
        jobs=[
            AdvisorJobSpec(ticker="NVDA", scheduled_at=future, action="deep_research", rationale="r1"),
            AdvisorJobSpec(ticker="AAPL", scheduled_at=past, action="deep_research", rationale="old"),
            AdvisorJobSpec(ticker="MSFT", scheduled_at=future, action="watch_only", rationale="w"),
        ],
        immediate_actions=["note"],
    )
    cfg = {"portfolio_advisor_max_jobs_per_plan": 5}
    rows = pas._jobs_from_plan(plan, cfg)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["kind"] == "deep_research"
    assert rows[0]["execution_tier"] == "single_model"
    assert rows[0]["job_type"] == "routine_monitoring"


def test_run_job_allows_candidate_when_not_live(tmp_path):
    cfg = _cfg(tmp_path)
    job = {
        "id": "cand1",
        "ticker": "ASML",
        "status": "pending",
        "execution_tier": "single_model",
        "job_type": "thesis_check",
        "source": "candidate_gate",
        "reason": "candidate",
    }
    st = state.default_state()
    st["jobs"] = [dict(job)]
    state.save_state(cfg, st)

    with patch("tradingagents.portfolio_advisor.service.run_single_model_analysis", return_value="VERDICT\nBROKEN."):
        with patch("tradingagents.portfolio_advisor.service._post_batch_pm_brief"):
            out = pas._run_job(job, cfg, live=set(), trade_date="2026-05-15")

    assert out["status"] == "completed"
    st2 = state.load_state(cfg)
    assert st2["jobs"][0]["status"] == "completed"


def test_run_job_cancels_non_candidate_when_not_live(tmp_path):
    cfg = _cfg(tmp_path)
    job = {
        "id": "plan1",
        "ticker": "ASML",
        "status": "pending",
        "execution_tier": "single_model",
        "job_type": "thesis_check",
        "source": "planner",
    }
    st = state.default_state()
    st["jobs"] = [dict(job)]
    state.save_state(cfg, st)

    out = pas._run_job(job, cfg, live=set(), trade_date="2026-05-15")

    assert out["status"] == "cancelled"
    st2 = state.load_state(cfg)
    assert st2["jobs"][0]["status"] == "cancelled"


def test_replan_skip_llm_unchanged(tmp_path):
    cfg = {
        **_cfg(tmp_path),
        "portfolio_advisor_skip_replan_llm_when_unchanged": True,
    }
    cat = "same catalyst block"
    digest = pas._catalyst_digest(cat)
    st = {
        "last_portfolio_tickers": ["NVDA", "AAPL"],
        "last_catalyst_digest": digest,
    }
    assert pas._replan_skip_llm(cfg, "replan", ["AAPL", "NVDA"], cat, st) is True
    assert pas._replan_skip_llm(cfg, "replan", ["MSFT"], cat, st) is False
    assert pas._replan_skip_llm(cfg, "init", ["AAPL", "NVDA"], cat, st) is False


@patch("tradingagents.portfolio_advisor.service.date")
def test_weekday_match_helper(mock_date):
    d = MagicMock()
    d.weekday.return_value = 3
    mock_date.today.return_value = d
    cfg = {"portfolio_advisor_weekly_weekday": 3}
    assert pas._weekday_matches(cfg) is True
