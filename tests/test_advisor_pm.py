"""Tests for advisor-level PM council (no live LLM)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.portfolio_advisor.advisor_pm import (
    _append_pm_memory_md,
    apply_pm_cycle_followups,
    load_recent_pm_cycles,
    optional_pm_cycle_on_portfolio_change,
    pm_log_path,
    pm_memory_path,
    run_pm_after_full_graph_if_enabled,
    run_pm_cycle,
)
from tradingagents.portfolio_advisor.models import (
    AdvisorPMAppendJob,
    AdvisorPMCycleResult,
    AdvisorPMTickerStance,
)


def test_run_pm_cycle_writes_logs(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    fake = AdvisorPMCycleResult(
        executive_summary="Test memo",
        stances=[AdvisorPMTickerStance(ticker="NVDA", stance="hold", rationale="ok")],
        forward_tasks=["Replan next week"],
        memory_note="Watch semis",
    )
    m_struct = MagicMock()
    m_struct.invoke.return_value = fake
    m_llm = MagicMock()
    m_client = MagicMock()
    m_client.get_llm.return_value = m_llm

    with patch("tradingagents.portfolio_advisor.advisor_pm.etoro_scan.fetch_portfolio_rows") as fetch:
        fetch.return_value = ({}, "portfolio text here", ["NVDA"], [])
        with patch("tradingagents.portfolio_advisor.advisor_pm.create_llm_client", return_value=m_client):
            with patch("tradingagents.portfolio_advisor.advisor_pm.bind_structured", return_value=m_struct):
                with patch("tradingagents.portfolio_advisor.advisor_pm.append_event"):
                    out = run_pm_cycle(cfg, trigger="test_trigger")
    assert out.executive_summary == "Test memo"
    assert pm_log_path(cfg).is_file()
    rows = load_recent_pm_cycles(cfg, limit=3)
    assert len(rows) == 1
    assert rows[0]["trigger"] == "test_trigger"
    assert rows[0]["result"]["stances"][0]["ticker"] == "NVDA"


def test_optional_pm_after_bootstrap_calls_run_pm_cycle(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "portfolio_advisor_pm_cycle_after_bootstrap": True}
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        from tradingagents.portfolio_advisor.bootstrap import _optional_pm_cycle_after_bootstrap

        _optional_pm_cycle_after_bootstrap(cfg)
    m.assert_called_once_with(cfg, trigger="after_bootstrap")


def test_optional_pm_after_bootstrap_skipped_when_disabled(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "portfolio_advisor_pm_cycle_after_bootstrap": False}
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        from tradingagents.portfolio_advisor.bootstrap import _optional_pm_cycle_after_bootstrap

        _optional_pm_cycle_after_bootstrap(cfg)
    m.assert_not_called()


def test_optional_pm_after_bootstrap_skipped_when_pm_globally_disabled(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_enabled": False,
        "portfolio_advisor_pm_cycle_after_bootstrap": True,
    }
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        from tradingagents.portfolio_advisor.bootstrap import _optional_pm_cycle_after_bootstrap

        _optional_pm_cycle_after_bootstrap(cfg)
    m.assert_not_called()


def test_run_pm_after_full_graph_calls_run_pm_cycle(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        run_pm_after_full_graph_if_enabled(
            cfg,
            ticker="nvda",
            trade_date="2026-05-01",
            final_state={"final_trade_decision": "Hold — test"},
        )
    m.assert_called_once()
    assert m.call_args[1]["trigger"] == "after_langgraph"
    assert "NVDA" in m.call_args[1]["extra_context"]


def test_run_pm_after_full_graph_skipped_when_disabled(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_after_each_langgraph": False,
    }
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        run_pm_after_full_graph_if_enabled(
            cfg, ticker="AAPL", trade_date="2026-05-01", final_state={"final_trade_decision": "x"}
        )
    m.assert_not_called()


def test_run_pm_after_full_graph_skipped_when_pm_globally_disabled(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_enabled": False,
        "portfolio_advisor_pm_after_each_langgraph": True,
    }
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        run_pm_after_full_graph_if_enabled(
            cfg, ticker="AAPL", trade_date="2026-05-01", final_state={"final_trade_decision": "x"}
        )
    m.assert_not_called()


def test_apply_pm_followups_replan(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_apply_actions": True,
    }
    res = AdvisorPMCycleResult(
        executive_summary="x",
        request_replan=True,
        replan_rationale="book changed",
    )
    with patch("tradingagents.portfolio_advisor.service.run_replan", return_value="replanned") as m:
        out = apply_pm_cycle_followups(cfg, res)
    m.assert_called_once()
    assert out["replan_outcome"] == "replanned"


def test_apply_pm_followups_append_jobs(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_apply_actions": True,
    }
    res = AdvisorPMCycleResult(
        executive_summary="x",
        append_jobs=[
            AdvisorPMAppendJob(ticker="NVDA", execution_tier="single_model", job_type="thesis_check", rationale="pm"),
        ],
    )
    with patch("tradingagents.portfolio_advisor.advisor_pm.etoro_scan.fetch_portfolio_rows") as fetch:
        fetch.return_value = ({}, "t", ["NVDA"], [])
        out = apply_pm_cycle_followups(cfg, res)
    assert out["jobs_appended"] == 1
    from tradingagents.portfolio_advisor import state as pa_state

    st = pa_state.load_state(cfg)
    pend = [j for j in st.get("jobs") or [] if j.get("status") == "pending"]
    assert len(pend) == 1
    assert pend[0]["ticker"] == "NVDA"
    assert pend[0]["flags"] == ["PM_APPEND"]


def test_apply_pm_followups_disabled_skips_side_effects(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "portfolio_advisor_pm_apply_actions": False}
    res = AdvisorPMCycleResult(executive_summary="x", request_replan=True, append_jobs=[AdvisorPMAppendJob(ticker="NVDA")])
    with patch("tradingagents.portfolio_advisor.service.run_replan") as m:
        out = apply_pm_cycle_followups(cfg, res)
    m.assert_not_called()
    assert out["apply_enabled"] is False


def test_optional_pm_on_portfolio_change_skipped_when_pm_globally_disabled(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_enabled": False,
        "portfolio_advisor_pm_cycle_on_portfolio_change": True,
    }
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        optional_pm_cycle_on_portfolio_change(
            cfg,
            trigger="t",
            old_portfolio_text_hash="a",
            new_portfolio_text_hash="b",
            tickers_added=["X"],
        )
    m.assert_not_called()


def test_optional_pm_on_portfolio_change_skipped_when_disabled(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_cycle_on_portfolio_change": False,
    }
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        optional_pm_cycle_on_portfolio_change(
            cfg,
            trigger="t",
            old_portfolio_text_hash="a",
            new_portfolio_text_hash="b",
            tickers_added=["X"],
        )
    m.assert_not_called()


def test_optional_pm_on_portfolio_change_noop_when_no_signal(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        optional_pm_cycle_on_portfolio_change(
            cfg,
            trigger="t",
            old_portfolio_text_hash=None,
            new_portfolio_text_hash="same",
            tickers_added=[],
            tickers_removed=[],
        )
    m.assert_not_called()


def test_optional_pm_on_portfolio_change_runs_on_ticker_delta(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        optional_pm_cycle_on_portfolio_change(
            cfg,
            trigger="weekly_portfolio_change",
            old_portfolio_text_hash=None,
            new_portfolio_text_hash="unchanged",
            tickers_added=["nvda"],
            tickers_removed=[],
        )
    m.assert_called_once()
    assert m.call_args[1]["trigger"] == "weekly_portfolio_change"
    assert "NVDA" in (m.call_args[1].get("extra_context") or "")


def test_pm_memory_path_unified_uses_memory_log_path(tmp_path):
    mem = tmp_path / "trading_memory.md"
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_unified_memory": True,
        "memory_log_path": str(mem),
    }
    assert pm_memory_path(cfg) == mem


def test_pm_memory_path_legacy_uses_advisor_dir(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "portfolio_advisor_pm_unified_memory": False}
    assert pm_memory_path(cfg) == tmp_path / "pa" / "pm_memory.md"


def test_append_pm_unified_writes_sentinel_and_entry_separator(tmp_path):
    mem = tmp_path / "trading_memory.md"
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "portfolio_advisor_pm_unified_memory": True,
        "memory_log_path": str(mem),
    }
    res = AdvisorPMCycleResult(executive_summary="memo", stances=[])
    _append_pm_memory_md(cfg, trigger="unit", result=res)
    text = mem.read_text(encoding="utf-8")
    assert "<!-- TRADINGAGENTS_PM_ADVISOR_LOG -->" in text
    assert "PM cycle" in text
    assert TradingMemoryLog._SEPARATOR in text


def test_append_pm_legacy_file_has_no_trading_separator(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "portfolio_advisor_pm_unified_memory": False}
    res = AdvisorPMCycleResult(executive_summary="memo", stances=[])
    _append_pm_memory_md(cfg, trigger="unit", result=res)
    p = pm_memory_path(cfg)
    text = p.read_text(encoding="utf-8")
    assert "<!-- TRADINGAGENTS_PM_ADVISOR_LOG -->" in text
    assert TradingMemoryLog._SEPARATOR not in text


def test_prior_pm_context_empty_when_cycles_zero(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "portfolio_advisor_pm_prior_cycles": 0}
    from tradingagents.portfolio_advisor.advisor_pm import _prior_pm_context

    assert _prior_pm_context(cfg) == ""


def test_optional_pm_on_portfolio_change_runs_on_hash_delta(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as m:
        optional_pm_cycle_on_portfolio_change(
            cfg,
            trigger="portfolio_book_changed",
            old_portfolio_text_hash="aa" * 32,
            new_portfolio_text_hash="bb" * 32,
            tickers_added=[],
            tickers_removed=[],
        )
    m.assert_called_once()
    assert m.call_args[1]["trigger"] == "portfolio_book_changed"
    assert "fingerprint" in (m.call_args[1].get("extra_context") or "").lower()
