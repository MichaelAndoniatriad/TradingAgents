"""Lightweight weekly portfolio check (no full replan / no heavy analysis by default)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set, Tuple

from tradingagents.llm_clients import create_llm_client
from tradingagents.portfolio_advisor import etoro_scan, outcome_sync, state

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(dt: str) -> datetime:
    s = (dt or "").strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _optional_weekly_narrative(cfg: Dict[str, Any], digest: str) -> str:
    """At most ~80 words; advisory only. Empty string if disabled or LLM fails."""
    if not cfg.get("portfolio_advisor_weekly_llm"):
        return ""
    provider = (cfg.get("llm_provider") or "openai").lower()
    model = (cfg.get("quick_think_llm") or "gpt-5.4-mini").strip()
    kwargs: Dict[str, Any] = {}
    if provider == "google" and cfg.get("google_thinking_level"):
        kwargs["thinking_level"] = cfg["google_thinking_level"]
    if provider == "openai" and cfg.get("openai_reasoning_effort"):
        kwargs["reasoning_effort"] = cfg["openai_reasoning_effort"]
    if provider == "anthropic" and cfg.get("anthropic_effort"):
        kwargs["effort"] = cfg["anthropic_effort"]
    try:
        client = create_llm_client(
            provider=provider,
            model=model,
            base_url=cfg.get("backend_url"),
            **kwargs,
        )
        llm = client.get_llm()
        prompt = (
            "You are a portfolio advisor. In at most 80 words, react to the weekly check digest below. "
            "Advisory only; no trade orders. If everything looks routine, say so briefly. "
            "If something deserves attention, name it clearly.\n\n---\n"
            f"{digest[:6000]}"
        )
        msg = llm.invoke(prompt)
        raw = getattr(msg, "content", str(msg))
        if isinstance(raw, list):
            bits = []
            for block in raw:
                if isinstance(block, dict) and block.get("type") == "text":
                    bits.append(block.get("text", ""))
            raw = "\n".join(bits) if bits else str(raw)
        return str(raw).strip()[:1200]
    except Exception as e:
        logger.warning("weekly overview LLM skipped: %s", e)
        return ""


def run_weekly_quick_check(cfg: Dict[str, Any]) -> Tuple[str, bool, Set[str]]:
    """Compare live eToro book vs state; cleanup orphan jobs; email digest.

    Returns ``(body_text, needs_attention, live_ticker_set)``.
    """
    _, portfolio_text, live_list, rows = etoro_scan.fetch_portfolio_rows()
    live: Set[str] = etoro_scan.current_ticker_set(live_list)
    try:
        outcome_sync.auto_close_outcomes(cfg, live, rows=rows)
    except Exception:
        logger.debug("weekly outcome_sync skipped", exc_info=True)
    st = state.load_state(cfg)
    prev: Set[str] = set(str(t).upper().strip() for t in (st.get("last_portfolio_tickers") or []) if t)

    added = sorted(live - prev)
    removed = sorted(prev - live)

    cancelled: List[str] = []
    for j in list(st.get("jobs") or []):
        if j.get("status") != "pending":
            continue
        tid = str(j.get("ticker") or "").strip().upper()
        if tid and tid not in live:
            jid = str(j.get("id") or "")
            if jid and state.cancel_job(st, jid, reason="weekly check: not in portfolio"):
                cancelled.append(f"{tid} (job {jid[:8]}…)")

    now = _utc_now()
    overdue: List[str] = []
    for j in state.list_pending_jobs(st):
        try:
            when = _parse_iso(str(j.get("scheduled_at") or ""))
        except ValueError:
            continue
        if when < now:
            overdue.append(
                f"{j.get('ticker')} scheduled {j.get('scheduled_at')} — still pending (is ``run-due`` cron running?)"
            )

    st["last_portfolio_tickers"] = sorted(live)
    st["last_weekly_check_iso"] = now.isoformat()
    state.save_state(cfg, st)

    lines = [
        "Weekly portfolio check (read-only eToro snapshot).",
        "This is a status pass — not a full reschedule. Use `advisor portfolio replan` when you want a new LLM schedule.",
        "",
        "--- Positions vs last week ---",
        f"Current tickers ({len(live)}): {', '.join(sorted(live))}",
    ]
    if added or removed:
        lines.append(
            "Changes since last recorded snapshot: "
            f"added {', '.join(added) if added else '—'}; "
            f"removed {', '.join(removed) if removed else '—'}"
        )
    else:
        lines.append("No ticker set change vs last advisor snapshot.")

    if cancelled:
        lines.extend(["", "--- Auto-cleaned jobs ---", "Cancelled pending deep runs (no longer held):"])
        lines.extend(f"  - {c}" for c in cancelled)
    if overdue:
        lines.extend(["", "--- Attention ---", "Overdue pending jobs (past scheduled time):"])
        lines.extend(f"  - {o}" for o in overdue[:20])

    lines.extend(["", "--- Account excerpt ---", portfolio_text[:4000]])
    digest = "\n".join(lines)

    narrative = _optional_weekly_narrative(cfg, digest)
    if narrative:
        digest += "\n\n--- Advisor note (optional LLM) ---\n" + narrative

    attention = bool(added or removed or cancelled or overdue)
    return digest, attention, live
