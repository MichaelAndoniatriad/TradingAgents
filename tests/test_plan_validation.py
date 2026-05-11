"""Plan validation against live rows and exit rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tradingagents.portfolio_advisor.models import AdvisorJobSpec, AdvisorPlanResult
from tradingagents.portfolio_advisor import plan_validation
from tradingagents.portfolio_advisor.plan_validation import weighted_avg_open_for_lots


def test_weighted_avg_open_for_lots_multi_prices():
    lots = [
        {"symbolFull": "GTLB", "openRate": 43.0, "units": 5.0},
        {"symbolFull": "GTLB", "openRate": 47.0, "units": 15.0},
        {"symbolFull": "GTLB", "openRate": 38.0, "units": 10.0},
    ]
    w = weighted_avg_open_for_lots(lots)
    # (43*5 + 47*15 + 38*10) / 30 = (215 + 705 + 380) / 30 = 1300/30
    assert abs(w - 1300.0 / 30.0) < 1e-6


def _future_iso(days: int = 9) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


@patch("tradingagents.portfolio_advisor.plan_validation.messaging.send_advisor_message")
@patch("tradingagents.portfolio_advisor.plan_validation.last_close_yfinance")
def test_dd40_removes_job(mock_px, _mock_msg):
    mock_px.return_value = 50.0
    rows = [{"symbolFull": "XX", "openRate": 100.0, "isBuy": True}]
    plan = AdvisorPlanResult(
        executive_summary="m",
        jobs=[
            AdvisorJobSpec(
                ticker="XX",
                scheduled_at=_future_iso(10),
                action="deep_research",
                rationale="r",
                execution_tier="single_model",
                job_type="routine_monitoring",
            )
        ],
        immediate_actions=[],
    )
    out, overrides = plan_validation.validate_advisor_plan({}, plan, rows, thesis_metrics={})
    assert len(out.jobs) == 0
    assert any(o.get("change") == "removed_job" for o in overrides)


@patch("tradingagents.portfolio_advisor.plan_validation.last_close_yfinance")
def test_no_metrics_downgrades_single_model(mock_px):
    mock_px.return_value = 100.0
    rows = [{"symbolFull": "YY", "openRate": 100.0, "isBuy": True}]
    plan = AdvisorPlanResult(
        executive_summary="m",
        jobs=[
            AdvisorJobSpec(
                ticker="YY",
                scheduled_at=_future_iso(10),
                action="deep_research",
                rationale="r",
                execution_tier="single_model",
                job_type="thesis_check",
            )
        ],
        immediate_actions=[],
    )
    out, overrides = plan_validation.validate_advisor_plan({}, plan, rows, thesis_metrics={})
    assert out.jobs[0].execution_tier == "full_graph"
    assert any(o.get("change") == "tier_upgrade_full_graph_no_metrics" for o in overrides)


@patch("tradingagents.portfolio_advisor.plan_validation.last_close_yfinance")
def test_empty_thesis_metrics_upgrades_nvda_cvlt_orcl(mock_px):
    mock_px.return_value = 50.0
    rows = [
        {"symbolFull": "NVDA", "openRate": 10.0, "isBuy": True},
        {"symbolFull": "CVLT", "openRate": 20.0, "isBuy": True},
        {"symbolFull": "ORCL", "openRate": 30.0, "isBuy": True},
    ]
    jobs = [
        AdvisorJobSpec(
            ticker=t,
            scheduled_at=_future_iso(10),
            action="deep_research",
            rationale="r",
            execution_tier="single_model",
            job_type="thesis_check",
        )
        for t in ("NVDA", "CVLT", "ORCL")
    ]
    plan = AdvisorPlanResult(executive_summary="m", jobs=jobs, immediate_actions=[])
    out, overrides = plan_validation.validate_advisor_plan({}, plan, rows, thesis_metrics={})
    assert all(j.execution_tier == "full_graph" for j in out.jobs)
    assert sum(1 for o in overrides if o.get("change") == "tier_upgrade_full_graph_no_metrics") == 3


@patch("tradingagents.portfolio_advisor.plan_validation.last_close_yfinance")
def test_missing_price_schedules_urgent_full_graph(mock_px):
    mock_px.return_value = None
    rows = [{"symbolFull": "ZZ", "openRate": 10.0, "isBuy": True}]
    far = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    plan = AdvisorPlanResult(
        executive_summary="m",
        jobs=[
            AdvisorJobSpec(
                ticker="ZZ",
                scheduled_at=far,
                action="deep_research",
                rationale="r",
                execution_tier="single_model",
                job_type="routine_monitoring",
            )
        ],
        immediate_actions=[],
    )
    out, overrides = plan_validation.validate_advisor_plan({}, plan, rows, thesis_metrics={})
    assert len(out.jobs) == 1
    assert out.jobs[0].execution_tier == "full_graph"
    assert "URGENT_VALIDATION_NO_PRICE" in (out.jobs[0].flags or [])
    assert any(o.get("change") == "urgent_full_graph_missing_price_or_entry" for o in overrides)
    when = datetime.fromisoformat(out.jobs[0].scheduled_at.replace("Z", "+00:00"))
    assert when <= datetime.now(timezone.utc) + timedelta(hours=25)
