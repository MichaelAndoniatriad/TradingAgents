from __future__ import annotations

from unittest.mock import MagicMock, patch

from tradingagents.portfolio_advisor import state
from tradingagents.portfolio_advisor.candidates import (
    append_candidate_records,
    candidate_log_path,
    candidate_state_path,
    evaluate_candidate,
    evaluate_candidates,
    evaluate_candidates_with_evidence,
    handle_candidate_full_graph_result,
    handle_candidate_light_research_result,
    is_candidate_job,
    parse_candidate_thesis_verdict,
    promoted_candidate_context,
    queue_candidate_research_jobs,
    run_promoted_candidate_pm_comparison,
)


def test_candidate_rejects_existing_holding():
    rec = evaluate_candidate(
        {"ticker": "NVDA", "reason": "AI infra", "priority": 1, "liquidity_ok": True},
        live_tickers=["NVDA"],
    )

    assert rec.status == "rejected"
    assert "already_in_portfolio" in rec.gate_failures


def test_candidate_research_queued_when_basic_gates_pass():
    rec = evaluate_candidate(
        {
            "ticker": "ASML",
            "reason": "Semicap monopoly candidate with clear portfolio role",
            "priority": 2,
            "liquidity_ok": True,
            "policy_ok": True,
            "catalyst": "earnings",
        },
        live_tickers=[],
    )

    assert rec.status == "research_queued"
    assert rec.gates["thesis"] == "pass"
    assert rec.gates["catalyst"] == "pass"


def test_candidate_promoted_after_positive_full_graph_rating():
    rec = evaluate_candidate(
        {
            "ticker": "ASML",
            "reason": "Semicap monopoly candidate with clear portfolio role",
            "priority": 1,
            "liquidity_ok": True,
            "policy_ok": True,
            "full_graph_rating": "Overweight",
        }
    )

    assert rec.status == "promoted"


def test_candidate_watch_when_thesis_missing():
    rec = evaluate_candidate({"ticker": "APP", "priority": 4, "liquidity_ok": True})

    assert rec.status == "watch"
    assert "missing_thesis" in rec.gate_failures


def test_queue_candidate_research_jobs_dedupes(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa"), "event_log_path": str(tmp_path / "events.jsonl")}
    records = evaluate_candidates(
        [
            {
                "ticker": "ASML",
                "reason": "Semicap monopoly candidate with clear portfolio role",
                "priority": 2,
                "liquidity_ok": True,
                "policy_ok": True,
            }
        ]
    )

    append_candidate_records(cfg, records)
    assert candidate_log_path(cfg).is_file()
    assert candidate_state_path(cfg).is_file()
    assert "candidate_status_changed" in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert queue_candidate_research_jobs(cfg, records) == 1
    assert queue_candidate_research_jobs(cfg, records) == 0

    st = state.load_state(cfg)
    jobs = state.list_pending_jobs(st)
    assert len(jobs) == 1
    assert jobs[0]["ticker"] == "ASML"
    assert jobs[0]["source"] == "candidate_gate"
    assert jobs[0]["execution_tier"] == "single_model"


def test_evaluate_candidates_with_evidence_promotes_from_full_graph_event(tmp_path):
    event_log = tmp_path / "events.jsonl"
    event_log.write_text(
        (
            '{"timestamp":"2026-05-15T09:00:00+00:00","ticker":"ASML",'
            '"event_type":"full_graph_decision","key_data":{'
            '"decision_id":"dec1","trade_date":"2026-05-15","rating":"Overweight",'
            '"confidence":"Medium","summary":"Positive candidate evidence."},'
            '"outcome":null}\n'
        ),
        encoding="utf-8",
    )
    cfg = {
        "event_log_path": str(event_log),
        "results_dir": str(tmp_path / "missing"),
        "portfolio_advisor_dir": str(tmp_path / "pa"),
    }

    records = evaluate_candidates_with_evidence(
        cfg,
        [{"ticker": "ASML", "reason": "Semicap candidate", "priority": 1, "liquidity_ok": True, "policy_ok": True}],
    )

    assert records[0].status == "promoted"
    assert "event:full_graph_decision:ASML:2026-05-15" in records[0].evidence_refs


def test_evaluate_candidates_with_evidence_enriches_liquidity_from_market_data(tmp_path):
    cfg = {
        "portfolio_advisor_dir": str(tmp_path / "pa"),
        "event_log_path": str(tmp_path / "events.jsonl"),
        "results_dir": str(tmp_path / "missing"),
        "portfolio_advisor_candidate_market_data_enabled": True,
    }
    hist = MagicMock()
    hist.empty = False
    hist.__contains__.side_effect = lambda key: key in {"Volume", "Close"}
    volume = MagicMock()
    volume.tail.return_value.mean.return_value = 1_000_000
    close_drop = MagicMock()
    close_drop.empty = False
    close_drop.iloc.__getitem__.return_value = 123.45
    close = MagicMock()
    close.dropna.return_value = close_drop
    hist.__getitem__.side_effect = lambda key: {"Volume": volume, "Close": close}[key]
    ticker = MagicMock()
    ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=ticker):
        records = evaluate_candidates_with_evidence(
            cfg,
            [{"ticker": "ASML", "reason": "Semicap monopoly candidate", "priority": 2, "policy_ok": True}],
        )

    assert records[0].gates["liquidity"] == "pass"
    assert records[0].status == "research_queued"


def test_promoted_candidate_context_keeps_candidates_out_of_stances():
    rec = evaluate_candidate(
        {
            "ticker": "ASML",
            "reason": "Semicap monopoly candidate with clear portfolio role",
            "priority": 1,
            "liquidity_ok": True,
            "policy_ok": True,
            "full_graph_rating": "Buy",
        }
    )

    context = promoted_candidate_context([rec], live_tickers=["NVDA", "MSFT"])

    assert "Candidate comparison request" in context
    assert "ASML" in context
    assert "Current holdings: MSFT, NVDA" in context
    assert "Do not put candidate tickers in stances" in context


def test_run_promoted_candidate_pm_comparison_calls_pm(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    rec = evaluate_candidate(
        {
            "ticker": "ASML",
            "reason": "Semicap monopoly candidate with clear portfolio role",
            "priority": 1,
            "liquidity_ok": True,
            "policy_ok": True,
            "full_graph_rating": "Overweight",
        }
    )

    from unittest.mock import patch

    with patch("tradingagents.portfolio_advisor.advisor_pm.run_pm_cycle") as pm:
        n = run_promoted_candidate_pm_comparison(cfg, [rec], live_tickers=["NVDA"])

    assert n == 1
    pm.assert_called_once()
    assert pm.call_args.kwargs["trigger"] == "candidate_comparison"
    assert "ASML" in pm.call_args.kwargs["extra_context"]


def test_parse_candidate_thesis_verdict():
    assert parse_candidate_thesis_verdict("VERDICT\nINTACT. Thesis supported.") == "INTACT"
    assert parse_candidate_thesis_verdict("VERDICT\nWEAKENING. Needs proof.") == "WEAKENING"
    assert parse_candidate_thesis_verdict("VERDICT\nBROKEN. No longer works.") == "BROKEN"
    assert parse_candidate_thesis_verdict("No verdict here") == "UNKNOWN"


def test_candidate_light_research_intact_queues_full_graph(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    job = {
        "id": "light1",
        "ticker": "ASML",
        "source": "candidate_gate",
        "job_type": "thesis_check",
        "reason": "Semicap candidate",
    }

    out = handle_candidate_light_research_result(cfg, job, "VERDICT\nINTACT. Thesis supported.")

    assert out["handled"] is True
    assert out["full_graph_queued"] is True
    st = state.load_state(cfg)
    jobs = state.list_pending_jobs(st)
    assert jobs[0]["ticker"] == "ASML"
    assert jobs[0]["source"] == "candidate_promotion"
    assert jobs[0]["execution_tier"] == "full_graph"


def test_candidate_light_research_broken_rejects_without_full_graph(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    job = {
        "id": "light1",
        "ticker": "ASML",
        "source": "candidate_gate",
        "job_type": "thesis_check",
        "reason": "Semicap candidate",
    }

    out = handle_candidate_light_research_result(cfg, job, "VERDICT\nBROKEN. Thesis failed.")

    assert out["status"] == "rejected"
    assert out["full_graph_queued"] is False
    assert state.list_pending_jobs(state.load_state(cfg)) == []


def test_candidate_full_graph_positive_requests_pm_comparison(tmp_path):
    cfg = {"portfolio_advisor_dir": str(tmp_path / "pa")}
    job = {"id": "deep1", "ticker": "ASML", "source": "candidate_promotion", "reason": "Candidate deep"}

    from unittest.mock import patch

    with patch("tradingagents.portfolio_advisor.candidates.run_promoted_candidate_pm_comparison", return_value=1) as pm:
        out = handle_candidate_full_graph_result(cfg, job, "Rating: Overweight\nGood.", live_tickers=["NVDA"])

    assert out["status"] == "promoted"
    assert out["pm_compared"] == 1
    pm.assert_called_once()


def test_is_candidate_job():
    assert is_candidate_job({"source": "candidate_gate"})
    assert is_candidate_job({"flags": ["CANDIDATE_PROMOTION"]})
    assert not is_candidate_job({"source": "planner"})
