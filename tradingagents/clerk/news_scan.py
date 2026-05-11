# tradingagents/clerk/news_scan.py

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _fingerprint(item: dict[str, Any]) -> str:
    title = str(item.get("title") or item.get("headline") or "")
    link = str(item.get("link") or item.get("uuid") or "")
    raw = f"{title}|{link}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


def _publish_ts(item: dict[str, Any]) -> Optional[int]:
    for key in ("providerPublishTime", "pubDate", "displayTime"):
        v = item.get(key)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def fetch_yfinance_news(ticker: str, limit: int = 20) -> List[dict[str, Any]]:
    """Return recent news items from yfinance (best-effort; may be empty)."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        news = getattr(t, "news", None) or []
        if not isinstance(news, list):
            return []
        return news[:limit]
    except Exception as e:
        logger.warning("yfinance news failed for %s: %s", ticker, e)
        return []


@dataclass
class NewsDelta:
    ticker: str
    new_items: List[dict[str, Any]]
    all_fingerprints: List[str]


def diff_news_against_seen(
    ticker: str,
    items: List[dict[str, Any]],
    seen_fps: set[str],
) -> NewsDelta:
    new_items: List[dict[str, Any]] = []
    fps: List[str] = []
    for it in items:
        fp = _fingerprint(it)
        fps.append(fp)
        if fp not in seen_fps:
            new_items.append(it)
    return NewsDelta(ticker=ticker, new_items=new_items, all_fingerprints=fps)


def format_headlines_for_digest(items: List[dict[str, Any]], max_lines: int = 8) -> str:
    lines = []
    for it in items[:max_lines]:
        title = str(it.get("title") or "(no title)")
        pub = _publish_ts(it)
        pub_s = ""
        if pub:
            from datetime import datetime, timezone

            try:
                pub_s = datetime.fromtimestamp(pub, tz=timezone.utc).strftime("%Y-%m-%d")
            except (OSError, ValueError):
                pub_s = ""
        suffix = f" ({pub_s})" if pub_s else ""
        lines.append(f"- {title}{suffix}")
    if len(items) > max_lines:
        lines.append(f"- … and {len(items) - max_lines} more")
    return "\n".join(lines) if lines else "(no headlines)"
