# tradingagents/advisor/runner.py

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.default_config import DEFAULT_CONFIG

from tradingagents.advisor.llm_digest import generate_llm_digest
from tradingagents.advisor.notify import get_webhook_url, send_webhook
from tradingagents.advisor.positions import PositionSpec, load_positions_file
from tradingagents.advisor.prices import fetch_last_close
from tradingagents.advisor.rules import AdvisorAlert, evaluate_position_rules, format_digest_text
from tradingagents.advisor.state_store import DedupeStore

logger = logging.getLogger(__name__)


def _dedupe_key(a: AdvisorAlert, today: date) -> str:
    return f"{a.ticker}:{a.trigger_code}:{today.isoformat()}"


def run_advisor_once(
    positions_path: Path,
    *,
    as_of: Optional[date] = None,
    webhook_url: Optional[str] = None,
    use_dedupe: bool = True,
    with_llm_digest: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[AdvisorAlert]]:
    """Evaluate all positions, optionally notify webhook, return (full_text, alerts)."""
    cfg = (config or DEFAULT_CONFIG).copy()
    today = as_of or datetime.now().date()

    positions = load_positions_file(positions_path)
    tickers = [p.ticker for p in positions]
    prices = fetch_last_close(tickers)

    all_alerts: List[AdvisorAlert] = []
    for pos in positions:
        px = prices.get(pos.ticker)
        if px is None:
            logger.warning("Skipping %s — no price", pos.ticker)
            continue
        all_alerts.extend(evaluate_position_rules(pos, px, today))

    rule_text = format_digest_text(today, prices, all_alerts)

    llm_text = ""
    if with_llm_digest:
        llm_text = "\n\n---\nLLM briefing\n\n" + generate_llm_digest(
            positions, all_alerts, rule_text, cfg
        )

    full_text = rule_text + llm_text

    url = (webhook_url or "").strip() or get_webhook_url()
    if url and all_alerts:
        base_dir = Path(cfg["data_cache_dir"]) / "advisor"
        store = DedupeStore.load(base_dir) if use_dedupe else None
        to_send: List[AdvisorAlert] = []
        sent_keys = set()
        if store:
            for a in all_alerts:
                key = _dedupe_key(a, today)
                if store.should_send(key, today):
                    to_send.append(a)
        else:
            to_send = list(all_alerts)

        if to_send:
            body = format_digest_text(today, prices, to_send)
            if llm_text:
                body = body + llm_text
            ok = send_webhook(url, body)
            if ok and store:
                for a in to_send:
                    store.mark_sent(_dedupe_key(a, today), today)
            elif not ok:
                logger.warning("Webhook delivery failed; dedupe not updated")

    return full_text, all_alerts


def run_advisor_loop(
    positions_path: Path,
    interval_seconds: int,
    **kwargs: Any,
) -> None:
    """Run ``run_advisor_once`` forever (or until Ctrl+C)."""
    while True:
        try:
            text, alerts = run_advisor_once(positions_path, **kwargs)
            logger.info("Advisor tick: %d alert(s)", len(alerts))
            print(text)
        except Exception as e:
            logger.exception("Advisor tick failed: %s", e)
        time.sleep(max(60, int(interval_seconds)))
