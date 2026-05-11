"""Orchestration: eToro scan → LLM plan → persisted jobs → due runs."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tradingagents.agents.utils.event_log import append_event
from tradingagents.clerk.deep_runner import run_deep_research, save_deep_report
from tradingagents.dataflows.config import set_config
from tradingagents.portfolio_advisor import (
    catalysts,
    etoro_scan,
    messaging,
    outcome_sync,
    plan_validation,
    planner,
    state,
    weekly_check,
    weekly_significance,
    watchdog as watchdog_mod,
)
from tradingagents.portfolio_advisor.models import AdvisorPlanResult
from tradingagents.portfolio_advisor.single_model_analysis import run_single_model_analysis

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(dt: str) -> datetime:
    s = (dt or "").strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _weekday_matches(cfg: Dict[str, Any]) -> bool:
    """Return True if today's weekday matches configured weekly scan day (0=Mon … 6=Sun)."""
    want = int(cfg.get("portfolio_advisor_weekly_weekday", 5))
    got = date.today().weekday()
    return got == want


def _catalyst_digest(catalyst_text: str) -> str:
    return hashlib.sha256((catalyst_text or "").encode("utf-8")).hexdigest()


def _replan_skip_llm(
    cfg: Dict[str, Any],
    mode: str,
    tickers: List[str],
    catalyst_text: str,
    st: Dict[str, Any],
) -> bool:
    """True when replan should skip the planner LLM (unchanged book + digest)."""
    if mode != "replan":
        return False
    if not bool(cfg.get("portfolio_advisor_skip_replan_llm_when_unchanged")):
        return False
    cur = sorted(str(t).strip().upper() for t in tickers if str(t).strip())
    prev = sorted(
        str(t).strip().upper() for t in (st.get("last_portfolio_tickers") or []) if str(t).strip()
    )
    if cur != prev:
        return False
    digest = _catalyst_digest(catalyst_text)
    return digest == (st.get("last_catalyst_digest") or "")


def _job_snapshot_for_diff(j: Dict[str, Any]) -> str:
    return (
        f"{str(j.get('ticker') or '').strip().upper()} @ {str(j.get('scheduled_at') or '')} "
        f"tier={str(j.get('execution_tier') or 'single_model')} type={str(j.get('job_type') or 'routine_monitoring')}"
    )


def _diff_pending_jobs_section(prev: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> str:
    if not prev:
        return ""
    prev_lines = sorted({_job_snapshot_for_diff(j) for j in prev})
    new_lines = sorted({_job_snapshot_for_diff(j) for j in new_rows})
    if prev_lines == new_lines:
        return "Schedule diff: unchanged lines versus prior pending jobs.\n"
    ps, ns = set(prev_lines), set(new_lines)
    added, removed = sorted(ns - ps), sorted(ps - ns)
    parts = ["Schedule diff versus prior pending jobs:"]
    if added:
        parts.append("New or changed:")
        parts.extend(f"  {x}" for x in added[:50])
    if removed:
        parts.append("Dropped:")
        parts.extend(f"  {x}" for x in removed[:50])
    return "\n".join(parts) + "\n"


def _jobs_from_plan(plan: AdvisorPlanResult, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    now = _utc_now()
    max_jobs = int(cfg.get("portfolio_advisor_max_jobs_per_plan") or 15)
    out: List[Dict[str, Any]] = []
    for spec in plan.jobs:
        if len(out) >= max_jobs:
            break
        if spec.action != "deep_research":
            continue
        try:
            when = _parse_iso(spec.scheduled_at)
        except ValueError:
            logger.warning("skip job bad scheduled_at for %s: %r", spec.ticker, spec.scheduled_at)
            continue
        if when < now:
            logger.info("skip past-dated job %s %s", spec.ticker, spec.scheduled_at)
            continue
        out.append(
            {
                "id": uuid.uuid4().hex[:20],
                "ticker": spec.ticker.strip().upper(),
                "scheduled_at": spec.scheduled_at.strip(),
                "kind": "deep_research",
                "reason": (spec.rationale or "").strip(),
                "status": "pending",
                "created_at": now.isoformat(),
                "execution_tier": spec.execution_tier,
                "job_type": (spec.job_type or "routine_monitoring").strip(),
                "flags": list(spec.flags or []),
            }
        )
    return out


def run_planning_session(cfg: Dict[str, Any], *, mode: str) -> Tuple[AdvisorPlanResult, Dict[str, Any]]:
    """Full eToro scan + LLM plan + persist jobs. ``mode`` is ``init`` or ``replan``."""
    set_config(cfg)
    _payload, portfolio_text, tickers, rows = etoro_scan.fetch_portfolio_rows()
    if not tickers:
        raise RuntimeError("No tickers in eToro portfolio export.")
    live = etoro_scan.current_ticker_set(tickers)
    try:
        outcome_sync.auto_close_outcomes(cfg, live, rows=rows)
    except Exception:
        logger.debug("outcome_sync after planning fetch skipped", exc_info=True)
    cat = catalysts.catalyst_block_for_tickers(tickers)
    st = state.load_state(cfg)
    if _replan_skip_llm(cfg, mode, tickers, cat, st):
        body = (
            "Portfolio advisor (replan) skipped the planner LLM: live ticker set and catalyst digest "
            "match the last successful plan. Pending jobs were left unchanged."
        )
        skip_plan = AdvisorPlanResult(
            executive_summary=body,
            jobs=[],
            immediate_actions=[],
        )
        st["last_replan_skip_iso"] = _utc_now().isoformat()
        state.save_state(cfg, st)
        append_event(
            cfg,
            {
                "ticker": "*",
                "event_type": "advisor_replan_skipped",
                "key_data": {"reason": "portfolio_and_catalyst_unchanged"},
                "outcome": None,
            },
        )
        return skip_plan, st

    plan = planner.build_advisor_plan(
        cfg,
        portfolio_text=portfolio_text,
        catalyst_text=cat,
        mode=mode,
        tickers=tickers,
    )
    thesis_raw = cfg.get("portfolio_advisor_thesis_metrics") or {}
    thesis_metrics = thesis_raw if isinstance(thesis_raw, dict) else {}
    plan, overrides = plan_validation.validate_advisor_plan(
        cfg, plan, rows, thesis_metrics=thesis_metrics
    )
    if overrides:
        append_event(
            cfg,
            {
                "ticker": "*",
                "event_type": "plan_validation_override",
                "key_data": {"overrides": overrides},
                "outcome": None,
            },
        )
    prev_pending = state.list_pending_jobs(st)
    cancelled = state.cancel_all_pending(st, reason="replaced by new advisor plan")
    new_rows = _jobs_from_plan(plan, cfg)
    state.append_jobs(st, new_rows)
    st["last_portfolio_tickers"] = sorted(tickers)
    st["first_scan_complete"] = True
    ts = _utc_now().isoformat()
    if mode == "init":
        st["last_init_iso"] = ts
    if mode == "replan":
        st["last_replan_iso"] = ts
    st["last_catalyst_digest"] = _catalyst_digest(cat)
    st["last_portfolio_text_hash"] = hashlib.sha256(portfolio_text.encode("utf-8")).hexdigest()
    state.save_state(cfg, st)

    lines = [
        f"Portfolio advisor ({mode})",
        "",
        plan.executive_summary,
        "",
        f"New deep_research jobs queued: {len(new_rows)} (cancelled prior pending: {cancelled})",
        "",
    ]
    if mode == "replan" and prev_pending:
        lines.append(_diff_pending_jobs_section(prev_pending, new_rows))
    if plan.immediate_actions:
        lines.append("Immediate actions:")
        for a in plan.immediate_actions:
            lines.append(f"- {a}")
        lines.append("")
    if new_rows:
        lines.append("Scheduled jobs:")
        for j in new_rows:
            lines.append(
                f"- {j['ticker']} @ {j['scheduled_at']} tier {j.get('execution_tier', 'single_model')} "
                f"type {j.get('job_type', 'routine_monitoring')} {j.get('reason', '')}"
            )
    body = "\n".join(lines)
    subj = f"[TradingAgents] Portfolio advisor — {mode} — {len(new_rows)} jobs"
    messaging.send_advisor_message(cfg, subj, body)
    append_event(
        cfg,
        {
            "ticker": "*",
            "event_type": "advisor_plan",
            "key_data": {"mode": mode, "jobs_queued": len(new_rows), "cancelled_pending": cancelled},
            "outcome": None,
        },
    )
    return plan, st


def run_init(cfg: Dict[str, Any], *, force: bool = False) -> None:
    if force:
        state.save_state(cfg, state.default_state())
    else:
        st = state.load_state(cfg)
        if st.get("first_scan_complete"):
            raise RuntimeError(
                "Advisor already initialized. Use `advisor portfolio weekly` for the light check, "
                "`advisor portfolio replan` to rebuild the LLM schedule, or `advisor portfolio init --force`."
            )
    run_planning_session(cfg, mode="init")
    if bool(cfg.get("portfolio_advisor_bootstrap_on_init")):
        from tradingagents.portfolio_advisor.bootstrap import run_full_portfolio_bootstrap

        delay = float(cfg.get("portfolio_advisor_bootstrap_delay_seconds") or 45.0)
        maxp = cfg.get("portfolio_advisor_bootstrap_max_positions")
        maxp_i = int(maxp) if maxp is not None else None
        run_full_portfolio_bootstrap(
            cfg, delay_seconds=delay, max_positions=maxp_i
        )


def run_weekly(cfg: Dict[str, Any], *, ignore_weekday: bool = False) -> str:
    """Lightweight weekly portfolio check (no full replan). Returns status token."""
    if not ignore_weekday and not _weekday_matches(cfg):
        logger.info(
            "Portfolio advisor weekly skipped (today weekday %s != configured %s)",
            date.today().weekday(),
            cfg.get("portfolio_advisor_weekly_weekday", 5),
        )
        return "skipped_weekday"
    set_config(cfg)
    digest, attention, live = weekly_check.run_weekly_quick_check(cfg)
    always = bool(cfg.get("portfolio_advisor_weekly_always_email", True))
    worth = weekly_significance.weekly_email_worth_sending(
        cfg, digest, live, attention_flag=attention
    )
    if always or worth:
        subj = "[TradingAgents] Weekly portfolio check"
        if attention:
            subj += " — review suggested"
        messaging.send_advisor_message(cfg, subj, digest)
    else:
        logger.info("Weekly portfolio check ran clean; email suppressed (no significance gate hit).")
    return "checked"


def run_replan(cfg: Dict[str, Any], *, ignore_weekday: bool = False) -> str:
    """Full LLM reschedule (same engine as init, keeps existing state except pending jobs replaced)."""
    if not ignore_weekday and not _weekday_matches(cfg):
        logger.info(
            "Portfolio advisor replan skipped (weekday gate; use --force to override)",
        )
        return "skipped_weekday"
    run_planning_session(cfg, mode="replan")
    return "replanned"


def run_due_jobs(cfg: Dict[str, Any]) -> int:
    """Execute pending jobs whose time has passed (cap per invocation)."""
    set_config(cfg)
    max_run = int(cfg.get("portfolio_advisor_run_due_max") or 2)
    try:
        _p, _t, live_tickers, rows = etoro_scan.fetch_portfolio_rows()
        live = etoro_scan.current_ticker_set(live_tickers)
        # auto_close_outcomes loads and saves state for unit snapshots internally.
        outcome_sync.auto_close_outcomes(cfg, live, rows=rows)
    except Exception as e:
        logger.error("run_due: cannot fetch portfolio: %s", e)
        return 0

    st = state.load_state(cfg)
    pending = [j for j in state.list_pending_jobs(st)]
    now = _utc_now()
    due: List[Dict[str, Any]] = []
    for j in pending:
        try:
            if _parse_iso(str(j.get("scheduled_at") or "")) <= now:
                due.append(j)
        except ValueError:
            continue
    due.sort(key=lambda x: str(x.get("scheduled_at") or ""))

    ran = 0
    for j in due:
        if ran >= max_run:
            break
        tid = str(j.get("ticker") or "").strip().upper()
        jid = str(j.get("id") or "")
        if not tid or not jid:
            continue
        if tid not in live:
            state.cancel_job(st, jid, reason="no longer in eToro portfolio")
            state.save_state(cfg, st)
            messaging.send_advisor_message(
                cfg,
                f"[TradingAgents] Advisor job cancelled — {tid}",
                f"Removed scheduled deep research for {tid} (not in current portfolio).",
            )
            ran += 1
            continue
        trade_date = date.today().isoformat()
        analysts = cfg.get("portfolio_advisor_deep_analysts") or ["news", "fundamentals", "market"]
        if not isinstance(analysts, list):
            analysts = ["news", "fundamentals", "market"]
        tier = str(j.get("execution_tier") or "single_model").strip().lower()
        job_type = str(j.get("job_type") or "routine_monitoring").strip()
        try:
            if tier == "full_graph":
                final_state, _signal = run_deep_research(tid, trade_date, analysts, cfg)
                rd = Path(str(cfg.get("results_dir", ".")))
                save_deep_report(
                    results_dir=rd, ticker=tid, trade_date=trade_date, final_state=final_state
                )
                j["status"] = "completed"
                j["completed_at"] = _utc_now().isoformat()
                state.save_state(cfg, st)
                ran += 1
                dec = str(final_state.get("final_trade_decision") or "")
                messaging.send_advisor_message(
                    cfg,
                    f"[TradingAgents] Advisor deep run done — {tid}",
                    f"Completed scheduled research for {tid} on {trade_date}.\n\n{dec[:8000]}",
                )
                continue
            run_single_model_analysis(cfg, tid, job_type)
            j["status"] = "completed"
            j["completed_at"] = _utc_now().isoformat()
            state.save_state(cfg, st)
            ran += 1
        except Exception as e:
            logger.exception("deep research failed for %s: %s", tid, e)
            j["status"] = "failed"
            j["error"] = str(e)
            state.save_state(cfg, st)
            messaging.send_advisor_message(cfg, f"[TradingAgents] Advisor run failed — {tid}", str(e))
            ran += 1
    return ran


def run_bootstrap(
    cfg: Dict[str, Any],
    *,
    delay_seconds: float = 45.0,
    max_positions: int | None = None,
    trade_date: str | None = None,
) -> dict:
    """Explicit full-graph pass for all (or capped) live eToro holdings."""
    from tradingagents.portfolio_advisor.bootstrap import run_full_portfolio_bootstrap

    return run_full_portfolio_bootstrap(
        cfg,
        trade_date=trade_date,
        delay_seconds=delay_seconds,
        max_positions=max_positions,
    )


def run_memory_review(cfg: Dict[str, Any], *, lookback_days: int = 120) -> str:
    from tradingagents.portfolio_advisor.memory_review import run_memory_review as _mr

    return _mr(cfg, lookback_days=lookback_days)


def run_watchdog(cfg: Dict[str, Any], *, ignore_market_hours: bool = False) -> int:
    """Price only exit rule sweep (separate from ``run_due_jobs``)."""
    set_config(cfg)
    return int(watchdog_mod.run_watchdog(cfg, ignore_market_hours=ignore_market_hours))


def run_post_earnings(cfg: Dict[str, Any], ticker: str) -> str:
    """Email a one-shot post-earnings verdict using the configured reasoning model."""
    from tradingagents.portfolio_advisor.post_verdict import run_post_earnings_verdict

    return run_post_earnings_verdict(cfg, ticker)


def _digest_preview(digest: Any) -> str:
    s = str(digest or "")
    if not s:
        return "(none)"
    if len(s) <= 16:
        return s
    return f"{s[:16]}…"


def status_text(cfg: Dict[str, Any]) -> str:
    st = state.load_state(cfg)
    lines = [
        f"State file: {state.state_path(cfg)}",
        f"first_scan_complete: {st.get('first_scan_complete')}",
        f"last_init_iso: {st.get('last_init_iso')}",
        f"last_replan_iso: {st.get('last_replan_iso')}",
        f"last_replan_skip_iso: {st.get('last_replan_skip_iso')}",
        f"last_catalyst_digest: {_digest_preview(st.get('last_catalyst_digest'))}",
        f"last_bootstrap_iso: {st.get('last_bootstrap_iso')}",
        f"last_weekly_check_iso: {st.get('last_weekly_check_iso')}",
        f"last_weekly_scan_iso: {st.get('last_weekly_scan_iso')}",
        f"last_portfolio_tickers: {', '.join(st.get('last_portfolio_tickers') or [])}",
        "",
        "Pending jobs:",
    ]
    pend = [j for j in (st.get("jobs") or []) if j.get("status") == "pending"]
    if not pend:
        lines.append("  (none)")
    else:
        for j in sorted(pend, key=lambda x: str(x.get("scheduled_at") or "")):
            lines.append(
                f"  - {j.get('ticker')} @ {j.get('scheduled_at')} id={j.get('id')} {j.get('reason', '')[:80]}"
            )
    return "\n".join(lines)
