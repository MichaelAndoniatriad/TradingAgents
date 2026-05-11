# tradingagents/clerk/weekly.py

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.messages import HumanMessage

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

from tradingagents.clerk.notify import get_clerk_webhook_url, post_text
from tradingagents.clerk.watchlist import ClerkWatchlist
from tradingagents.clerk.weekly_queue import (
    collect_weekly_deep_queue,
    execute_deep_queue,
    format_deep_queue_markdown,
)

logger = logging.getLogger(__name__)


def _collect_daily_digests(cache_dir: Path, days: int = 7) -> str:
    daily = Path(cache_dir) / "clerk" / "daily"
    if not daily.exists():
        return "(no archived daily digest files in this window — weekly-only mode is normal)"
    end = date.today()
    want = [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    parts: List[str] = []
    for d in want:
        p = daily / f"{d}.md"
        if p.exists():
            parts.append(f"### {d}\n\n{p.read_text(encoding='utf-8')[:8000]}")
    if not parts:
        return f"(no digest files for the last {days} days in {daily})"
    return "\n\n".join(parts)


def _weekly_llm_summary(bundle_text: str, config: Dict[str, Any]) -> str:
    cfg = config.copy()
    provider = (cfg.get("llm_provider") or "openai").lower()
    kwargs: Dict[str, Any] = {}
    if provider == "google" and cfg.get("google_thinking_level"):
        kwargs["thinking_level"] = cfg["google_thinking_level"]
    if provider == "openai" and cfg.get("openai_reasoning_effort"):
        kwargs["reasoning_effort"] = cfg["openai_reasoning_effort"]
    if provider == "anthropic" and cfg.get("anthropic_effort"):
        kwargs["effort"] = cfg["anthropic_effort"]

    client = create_llm_client(
        provider=provider,
        model=cfg.get("quick_think_llm", "gpt-5.4-mini"),
        base_url=cfg.get("backend_url"),
        **kwargs,
    )
    llm = client.get_llm()
    prompt = (
        "You are a portfolio clerk summarizing the past week's automated morning digests.\n"
        "Produce:\n"
        "1) Three bullets: what mattered most across tickers and the portfolio snapshot narrative.\n"
        "2) 'Next week watch list': 5 concrete things to monitor (dates, events, metrics).\n"
        "3) One short paragraph: which queued deep-research names (if any) look highest priority vs "
        "noise — deep runs are expensive and should stay rare.\n"
        "Keep total under 350 words. No investment advice disclaimers beyond one short line.\n\n"
        "--- Past week digests (may be truncated) ---\n\n"
        f"{bundle_text[:24000]}"
    )
    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        content = getattr(msg, "content", str(msg))
        if isinstance(content, list):
            text_bits = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_bits.append(block.get("text", ""))
            content = "\n".join(text_bits) if text_bits else str(content)
        return str(content).strip()
    except Exception as e:
        logger.exception("Weekly LLM summary failed: %s", e)
        return f"(Weekly LLM summary unavailable: {e})"


def run_weekly_clerk(
    *,
    watchlist: Optional[Union[Path, ClerkWatchlist]] = None,
    days: int = 7,
    webhook_url: Optional[str] = None,
    with_llm: bool = True,
    config: Optional[Dict[str, Any]] = None,
    trade_date: Optional[str] = None,
    execute_deep_queue: bool = False,
    max_deep: int = 3,
) -> str:
    """Roll up morning logs; build deep-research queue; optional LLM + optional deep execution."""
    cfg = (config or DEFAULT_CONFIG).copy()
    td = trade_date or date.today().strftime("%Y-%m-%d")
    bundle = _collect_daily_digests(Path(cfg["data_cache_dir"]), days=days)

    wl: Optional[ClerkWatchlist] = None
    if isinstance(watchlist, Path):
        wl = ClerkWatchlist.from_path(watchlist)
    elif isinstance(watchlist, ClerkWatchlist):
        wl = watchlist

    queue_block = ""
    queue_entries: List[Tuple[str, List[str]]] = []
    deep_done: List[str] = []
    if wl is not None:
        queue_entries = collect_weekly_deep_queue(
            wl,
            trade_date=td,
            data_cache_dir=Path(cfg["data_cache_dir"]),
        )
        queue_block = "\n" + format_deep_queue_markdown(queue_entries) + "\n"
        iso_week = date.today().isocalendar()
        qpath = Path(cfg["data_cache_dir"]) / "clerk" / "weekly" / f"deep_queue_{iso_week[0]}-W{iso_week[1]:02d}.md"
        qpath.parent.mkdir(parents=True, exist_ok=True)
        qpath.write_text(queue_block.strip() + "\n", encoding="utf-8")

        if execute_deep_queue and queue_entries:
            deep_done = execute_deep_queue(
                queue_entries,
                trade_date=td,
                wl=wl,
                config=cfg,
                max_deep=max(0, int(max_deep)),
            )

    header = (
        f"# Clerk — weekly roll-up\n\n"
        f"_Generated (UTC): {datetime.utcnow().isoformat()}Z_\n\n"
        f"Window: last {days} day(s) of morning digests.\n\n"
    )
    bundle_for_llm = bundle + (queue_block if queue_block else "")
    llm_block = ""
    if with_llm:
        llm_block = "\n## LLM summary\n\n" + _weekly_llm_summary(bundle_for_llm, cfg) + "\n"

    digest = (
        header
        + "## Raw digests (concatenated)\n\n"
        + bundle
        + "\n"
        + queue_block
        + (f"\n## Deep research executed this pass\n\n{', '.join(deep_done)}\n" if deep_done else "")
        + llm_block
    )

    out_dir = Path(cfg["data_cache_dir"]) / "clerk" / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    iso_week = date.today().isocalendar()
    out_path = out_dir / f"{iso_week[0]}-W{iso_week[1]:02d}.md"
    out_path.write_text(digest, encoding="utf-8")

    url = (webhook_url or "").strip() or get_clerk_webhook_url()
    if url:
        body = digest if len(digest) < 14000 else digest[:13900] + "\n…(truncated)"
        post_text(url, f"Clerk — weekly roll-up\n\n{body}")

    return digest
