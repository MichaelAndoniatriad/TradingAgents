# tradingagents/clerk/weekly_queue.py
"""Weekly deep-research queue: evaluate triggers without mutating the daily digest."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tradingagents.clerk.deep_runner import run_deep_research, save_deep_report
from tradingagents.clerk.news_scan import fetch_yfinance_news, format_headlines_for_digest, _fingerprint
from tradingagents.clerk.state import ClerkStateStore
from tradingagents.clerk.triggers import collect_deep_research_reasons
from tradingagents.clerk.watchlist import ClerkWatchlist

logger = logging.getLogger(__name__)


def collect_weekly_deep_queue(
    wl: ClerkWatchlist,
    *,
    trade_date: str,
    data_cache_dir: Path,
) -> List[Tuple[str, List[str]]]:
    """Return (ticker, reasons) for tickers that warrant deep research this week.

    Uses the same headline + fingerprint store as the morning clerk so daily
    runs stay authoritative; this pass re-fetches Yahoo headlines and
    recomputes trigger reasons (typically run once per week).
    """
    store = ClerkStateStore(Path(data_cache_dir) / "clerk" / "news_seen")
    as_of = date.today()
    out: List[Tuple[str, List[str]]] = []

    for ticker in wl.tickers:
        items = fetch_yfinance_news(ticker, limit=25)
        seen = store.load_seen(ticker)
        bootstrap = not bool(seen) and bool(items)
        if bootstrap:
            new_items: List[dict] = []
        else:
            new_items = [it for it in items if _fingerprint(it) not in seen]

        reasons = collect_deep_research_reasons(
            ticker,
            as_of,
            wl.triggers,
            new_headline_items=new_items,
            bootstrap_baseline=bootstrap,
        )
        if reasons:
            out.append((ticker, reasons))
    return out


def format_deep_queue_markdown(entries: List[Tuple[str, List[str]]]) -> str:
    if not entries:
        return (
            "## Weekly deep-research queue\n\n"
            "_No tickers matched deep-research triggers this week (earnings window, "
            "keywords in new headlines, or headline-delta gate)._\n"
        )
    lines = [
        "## Weekly deep-research queue",
        "",
        "Run **`clerk weekly --execute-deep-queue`** (with the same watchlist / eToro flags) "
        "to execute the full TradingAgents graph for these names — **only** when you are ready for the API cost.",
        "",
        "| Ticker | Reasons |",
        "| --- | --- |",
    ]
    for t, rs in entries:
        lines.append(f"| {t} | {', '.join(rs)} |")
    lines.append("")
    return "\n".join(lines)


def execute_deep_queue(
    entries: List[Tuple[str, List[str]]],
    *,
    trade_date: str,
    wl: ClerkWatchlist,
    config: Dict[str, Any],
    max_deep: int,
) -> List[str]:
    """Run deep research for up to ``max_deep`` queued tickers; return tickers completed."""
    done: List[str] = []
    cfg = config.copy()
    results_root = Path(cfg["results_dir"])
    store = ClerkStateStore(Path(cfg["data_cache_dir"]) / "clerk" / "news_seen")
    for ticker, _reasons in entries[: max(0, max_deep)]:
        try:
            final_state, _dec = run_deep_research(
                ticker,
                trade_date,
                wl.deep_research_analysts,
                cfg,
            )
            path = save_deep_report(
                results_dir=results_root,
                ticker=ticker,
                trade_date=trade_date,
                final_state=final_state,
            )
            logger.info("Weekly deep queue: saved %s", path)
            done.append(ticker)
            # Align fingerprint store with morning clerk so the same headlines are not re-queued.
            items = fetch_yfinance_news(ticker, limit=25)
            merged = set(store.load_seen(ticker))
            for it in items:
                merged.add(_fingerprint(it))
            store.save_seen(ticker, list(merged))
        except Exception as e:
            logger.exception("Weekly deep queue failed for %s: %s", ticker, e)
    return done
