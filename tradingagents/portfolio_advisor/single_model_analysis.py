"""One reasoning model pass for scheduled advisor jobs (no LangGraph)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from tradingagents.agents.utils.event_log import append_event, format_recent_events_for_ticker
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.llm_clients import create_llm_client
from tradingagents.portfolio_advisor import messaging, price_util

logger = logging.getLogger(__name__)


def _reasoning_llm(cfg: Dict[str, Any]):
    model = (cfg.get("portfolio_advisor_reasoning_model") or "deepseek/deepseek-r1").strip()
    provider = (cfg.get("llm_provider") or "openrouter").lower()
    if "/" in model and provider != "openrouter":
        provider = "openrouter"
    base = cfg.get("corporate_openrouter_base_url") or cfg.get("backend_url")
    return create_llm_client(provider, model, base_url=base).get_llm()


def run_single_model_analysis(
    cfg: Dict[str, Any],
    ticker: str,
    job_type: str,
) -> str:
    """Structured one shot memo for thesis_check, weekly_summary, post_earnings, routine_monitoring."""
    sym = (ticker or "").strip().upper()
    if not sym:
        raise ValueError("ticker required")
    jt = (job_type or "routine_monitoring").strip().lower()

    px = price_util.last_close_yfinance(sym)
    px_line = f"Last close from public feed: {px:.6f}" if px is not None else "Last close: missing (no public print returned)"

    mem = TradingMemoryLog(cfg)
    lookback = int(cfg.get("memory_context_lookback_days") or 90)
    ev_days = int(cfg.get("memory_event_log_prompt_days") or 30)
    md_ctx = mem.get_past_context(
        sym,
        n_same=int(cfg.get("memory_context_max_same_ticker") or 5),
        n_cross=int(cfg.get("memory_context_max_cross_ticker") or 2),
        lookback_days=lookback,
    )
    ev_ctx = format_recent_events_for_ticker(cfg, sym, days=ev_days, max_events=20)

    today = date.today().isoformat()
    prompt = f"""You are the desk lead on one open name. Advisory only. No trade orders.

Ticker {sym}
Job type {jt}
As of {today}

Price line
{px_line}

Markdown memory (trimmed)
{(md_ctx or 'none')[:7000]}

JSONL tail (trimmed)
{(ev_ctx or 'none')[:5000]}

Output format (plain text, short lines, no decorative separators)

VERDICT
One sentence first.

BULLETS
Three to six bullets: price vs thesis, timing, risk, what to watch next.

DATA GAPS
List any missing figures explicitly. Do not guess prices or dates not shown above.
"""
    llm = _reasoning_llm(cfg)
    msg = llm.invoke([HumanMessage(content=prompt)])
    content = getattr(msg, "content", str(msg))
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        content = "\n".join(parts) if parts else str(content)
    text = str(content).strip()
    subj = f"[TradingAgents] Advisor single model run {sym} {jt} {today}"
    messaging.send_advisor_message(cfg, subj, text[:12000])
    append_event(
        cfg,
        {
            "ticker": sym,
            "event_type": "single_model_analysis",
            "key_data": {"job_type": jt, "date": today, "excerpt": text[:900]},
            "outcome": None,
        },
    )
    return text
