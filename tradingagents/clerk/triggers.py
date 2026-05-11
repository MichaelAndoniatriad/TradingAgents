# tradingagents/clerk/triggers.py

from __future__ import annotations

import logging
from datetime import date
from typing import List

from tradingagents.advisor.earnings import next_earnings_from_yfinance
from tradingagents.clerk.watchlist import ClerkTriggers

logger = logging.getLogger(__name__)


def collect_deep_research_reasons(
    ticker: str,
    as_of: date,
    triggers: ClerkTriggers,
    new_headline_items: List[dict],
    bootstrap_baseline: bool,
) -> List[str]:
    """Return human-readable reason codes (no percentage logic).

    When ``bootstrap_baseline`` is True we are ingesting a first-time headline
    fingerprint set — we never schedule deep research on that pass.
    """
    if bootstrap_baseline:
        return []

    reasons: List[str] = []

    if triggers.deep_research_on_new_headlines and new_headline_items:
        reasons.append("new_headlines")

    n_earn = triggers.deep_research_earnings_within_days
    if n_earn is not None and n_earn >= 0:
        ed = next_earnings_from_yfinance(ticker)
        if ed is not None:
            days = (ed - as_of).days
            if 0 <= days <= n_earn:
                reasons.append(f"earnings_within_{n_earn}d ({ed.isoformat()})")

    kws = [k.strip().lower() for k in triggers.deep_research_keyword_hits if k.strip()]
    if kws and new_headline_items:
        for it in new_headline_items:
            title = str(it.get("title") or "").lower()
            if any(k in title for k in kws):
                reasons.append("keyword_in_new_headline")
                break

    if triggers.use_llm_materiality_gate:
        logger.warning(
            "use_llm_materiality_gate is set for %s but not implemented yet — ignored",
            ticker,
        )

    # De-duplicate while preserving order
    out: List[str] = []
    for r in reasons:
        if r not in out:
            out.append(r)
    return out
