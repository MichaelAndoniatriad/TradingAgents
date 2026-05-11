# tradingagents/clerk/morning.py

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from tradingagents.default_config import DEFAULT_CONFIG

from tradingagents.clerk.news_scan import fetch_yfinance_news, format_headlines_for_digest, _fingerprint
from tradingagents.clerk.portfolio_digest import build_daily_portfolio_markdown
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
    """Daily digest: eToro book snapshot + headline news per ticker.

    Does **not** run the full multi-agent graph (``deep_research`` is ignored).
    Deep research is proposed and optionally executed on the **weekly** clerk
    when triggers warrant it.

    Returns ``(digest_markdown, [])`` for API compatibility (second value unused).
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
        "**Daily scope:** overnight-style **portfolio snapshot** (when eToro keys are set) "
        "+ **recent headlines** for each watchlist ticker. "
        "Trigger hints are listed for transparency; **deep research is scheduled from the weekly job**, not here.",
        "",
    ]

    pf_block, _used_etoro = build_daily_portfolio_markdown(
        cache_dir=Path(cfg["data_cache_dir"]),
        trade_date=td,
    )
    lines.append(pf_block)
    lines.append("---")
    lines.append("")

    if deep_research:
        logger.warning(
            "run_morning_clerk(..., deep_research=True) is ignored — use `clerk weekly --execute-deep-queue`."
        )

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
            lines.append(
                f"**Would queue for weekly deep research:** {', '.join(reasons)} "
                "(weekly pass decides execution; not auto-run here)."
            )
        else:
            lines.append("**Weekly deep-research queue:** no trigger signals from this headline delta.")
        lines.append("")

        # Persist seen fingerprints (merge with prior)
        merged = set(seen)
        for it in items:
            merged.add(_fingerprint(it))
        store.save_seen(ticker, list(merged))

    digest = "\n".join(lines).strip() + "\n"

    log_path = daily_dir / f"{td}.md"
    log_path.write_text(digest, encoding="utf-8")

    url = (webhook_url or "").strip() or get_clerk_webhook_url()
    if url:
        body = f"Clerk — morning ({td})\n\n{digest}"
        if len(body) > 12000:
            body = body[:11900] + "\n…(truncated)"
        post_text(url, body)

    return digest, []
