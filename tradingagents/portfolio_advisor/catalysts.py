"""Lightweight catalyst hints (earnings) via yfinance."""

from __future__ import annotations

import logging
from datetime import date
from typing import List

from tradingagents.advisor.earnings import next_earnings_from_yfinance

logger = logging.getLogger(__name__)


def earnings_ramp_block_for_tickers(
    tickers: List[str],
    ramp_days: int = 7,
    *,
    max_tickers: int = 40,
) -> str:
    """List tickers whose next parsed earnings date falls within ``ramp_days`` (inclusive).

    Used to steer the portfolio planner toward higher monitoring frequency before prints.
    """
    today = date.today()
    rows: List[tuple[int, str, str]] = []
    for raw in tickers[:max_tickers]:
        sym = raw.strip().upper()
        if not sym:
            continue
        d = next_earnings_from_yfinance(sym)
        if d is None:
            continue
        delta = (d - today).days
        if 0 <= delta <= int(ramp_days):
            rows.append((delta, sym, d.isoformat()))
    rows.sort(key=lambda x: x[0])
    if not rows:
        return (
            f"(No earnings dates parsed within the next {int(ramp_days)} calendar days "
            "for this ticker set; treat catalyst hints below as best effort.)"
        )
    lines = [
        f"Earnings within {int(ramp_days)} calendar days (prioritize research and watch_only vs skip):",
    ]
    for _delta, sym, iso in rows[:25]:
        lines.append(f"- {sym}: {iso}")
    return "\n".join(lines)


def catalyst_block_for_tickers(tickers: List[str], max_tickers: int = 30) -> str:
    """Return a compact markdown-ish block for the planner prompt."""
    lines: List[str] = []
    for raw in tickers[:max_tickers]:
        sym = raw.strip().upper()
        if not sym:
            continue
        snippet = _earnings_snippet(sym)
        lines.append(f"- **{sym}**: {snippet}")
    return "\n".join(lines) if lines else "(no positions)"


def _earnings_snippet(ticker: str) -> str:
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        ed = getattr(t, "earnings_dates", None)
        if ed is not None and hasattr(ed, "head") and len(ed) > 0:
            nxt = ed.head(2)
            parts = []
            for idx in nxt.index:
                parts.append(str(idx.date()))
            if parts:
                return f"upcoming/recent earnings dates (index): {', '.join(parts)}"
        cal = getattr(t, "calendar", None)
        if isinstance(cal, dict):
            ev = cal.get("Earnings Date")
            if ev is not None:
                return f"calendar earnings hint: {ev}"
    except Exception as e:
        logger.debug("catalyst fetch failed for %s: %s", ticker, e)
    return "no public earnings calendar row (use news + fundamentals in research)"
