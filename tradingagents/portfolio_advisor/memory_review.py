"""Monthly-style review over JSONL event log (optional reasoning LLM)."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from tradingagents.agents.utils.event_log import load_events_for_review
from tradingagents.dataflows.config import set_config
from tradingagents.llm_clients import create_llm_client
from tradingagents.portfolio_advisor import messaging

logger = logging.getLogger(__name__)


def run_memory_review(cfg: Dict[str, Any], *, lookback_days: int = 120) -> str:
    """Summarize recent events; email result. Uses reasoning model when configured."""
    set_config(cfg)
    rows = load_events_for_review(cfg, days=int(lookback_days))
    if not rows:
        body = f"No event log rows in the last {lookback_days} days. Path uses event_log_path or memory sibling."
        messaging.send_advisor_message(cfg, "[TradingAgents] Memory review (empty)", body)
        return body

    # Compact histogram without LLM
    counts: Dict[str, int] = {}
    for r in rows:
        et = str(r.get("event_type") or "?")
        counts[et] = counts.get(et, 0) + 1
    hist = "\n".join(f"- {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    sample = json.dumps(rows[-40:], indent=2, ensure_ascii=False)[:12000]

    model = (cfg.get("portfolio_advisor_reasoning_model") or "deepseek/deepseek-r1").strip()
    provider = "openrouter" if "/" in model else (cfg.get("llm_provider") or "openrouter").lower()
    base = cfg.get("corporate_openrouter_base_url") or cfg.get("backend_url")
    prompt = f"""You are reviewing a machine event log for a trading research stack (advisory only, no orders).

Lookback: last {lookback_days} days.

Event counts by type:
{hist}

Last 40 raw events (JSON):
{sample}

Write a short review (max 12 bullet points) covering:
1) Which event types dominate and whether that matches a healthy cadence.
2) Any tickers with repeated failures or missing follow-ups.
3) One concrete suggestion to tighten the human workflow (not model hype).

If the log is too sparse to infer patterns, say so explicitly.
Today (UTC date): {date.today().isoformat()}
"""
    try:
        llm = create_llm_client(provider, model, base_url=base).get_llm()
        msg = llm.invoke([HumanMessage(content=prompt)])
        narrative = getattr(msg, "content", str(msg))
        if isinstance(narrative, list):
            bits = []
            for block in narrative:
                if isinstance(block, dict) and block.get("type") == "text":
                    bits.append(block.get("text", ""))
            narrative = "\n".join(bits) if bits else str(narrative)
        narrative = str(narrative).strip()
    except Exception as e:
        logger.warning("memory review LLM failed: %s", e)
        narrative = f"(LLM narrative skipped: {e})"

    body = f"--- Event histogram ---\n{hist}\n\n--- Review ---\n{narrative}"
    messaging.send_advisor_message(
        cfg,
        f"[TradingAgents] Memory review — {len(rows)} events / {lookback_days}d",
        body[:50000],
    )
    return body
