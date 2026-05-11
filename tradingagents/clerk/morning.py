# tradingagents/clerk/morning.py

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from tradingagents.default_config import DEFAULT_CONFIG

from tradingagents.clerk.deep_runner import run_deep_research, save_deep_report
from tradingagents.clerk.news_scan import fetch_yfinance_news, format_headlines_for_digest, _fingerprint
from tradingagents.clerk.notify import get_clerk_webhook_url, post_text
from tradingagents.clerk.state import ClerkStateStore
from tradingagents.clerk.triggers import collect_deep_research_reasons
from tradingagents.clerk.watchlist import ClerkWatchlist

logger = logging.getLogger(__name__)


def _today_trade_date() -> str:
    return date.today().strftime("%Y-%m-%d")


def run_morning_clerk(
    watchlist: Union[Path, ClerkWatchlist],
    *,
    trade_date: Optional[str] = None,
    webhook_url: Optional[str] = None,
    deep_research: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[str]]:
    """Daily lightweight scan. Returns (digest_markdown, tickers_that_ran_deep).

    First time a ticker appears, fingerprints are recorded and **no** deep
    research fires (baseline pass). After that, deep research runs only when
    triggers match — never on simple percentage moves.
    """
    cfg = (config or DEFAULT_CONFIG).copy()
    wl = (
        ClerkWatchlist.from_path(watchlist)
        if isinstance(watchlist, Path)
        else watchlist
    )
    cfg.setdefault("output_language", wl.output_language)

    as_of = date.today()
    td = trade_date or _today_trade_date()

    clerk_root = Path(cfg["data_cache_dir"]) / "clerk"
    daily_dir = clerk_root / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    store = ClerkStateStore(clerk_root / "news_seen")

    lines: List[str] = [
        f"# Clerk — morning scan ({td})",
        "",
        "Automated digest (no intraday agent loop). Deep multi-agent research runs **only** when a trigger matches.",
        "",
    ]
    deep_tickers: List[str] = []

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

        lines.append(f"## {ticker}")
        if bootstrap:
            lines.append(
                "*First clerk pass:* recorded headline fingerprints only — "
                "no automated deep research today (avoids treating the whole backlog as “news”).*"
            )
        elif new_items:
            lines.append("**New headlines since last clerk run:**")
            lines.append(format_headlines_for_digest(new_items, max_lines=10))
        else:
            lines.append("*No new headlines since the last clerk run.*")

        lines.append("")
        lines.append("**Recent headline snapshot (top):**")
        lines.append(format_headlines_for_digest(items, max_lines=6))
        lines.append("")

        if reasons:
            lines.append(f"**Deep-research triggers:** {', '.join(reasons)}")
        else:
            lines.append("**Deep-research triggers:** none")
        lines.append("")

        # Persist seen fingerprints (merge with prior)
        merged = set(seen)
        for it in items:
            merged.add(_fingerprint(it))
        store.save_seen(ticker, list(merged))

        if deep_research and reasons:
            try:
                final_state, _dec = run_deep_research(
                    ticker,
                    td,
                    wl.deep_research_analysts,
                    cfg,
                )
                report_path = save_deep_report(
                    results_dir=Path(cfg["results_dir"]),
                    ticker=ticker,
                    trade_date=td,
                    final_state=final_state,
                )
                lines.append(f"→ Ran deep research; saved: `{report_path}`")
                deep_tickers.append(ticker)
            except Exception as e:
                logger.exception("Deep research failed for %s", ticker)
                lines.append(f"→ **Deep research failed:** {e}")
            lines.append("")

    digest = "\n".join(lines).strip() + "\n"

    log_path = daily_dir / f"{td}.md"
    log_path.write_text(digest, encoding="utf-8")

    url = (webhook_url or "").strip() or get_clerk_webhook_url()
    if url:
        body = f"Clerk — morning ({td})\n\n{digest}"
        if len(body) > 12000:
            body = body[:11900] + "\n…(truncated)"
        post_text(url, body)

    return digest, deep_tickers
