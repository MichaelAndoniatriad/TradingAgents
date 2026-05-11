"""Decide whether the weekly portfolio email is worth sending."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Set

from tradingagents.advisor.earnings import next_earnings_from_yfinance
from tradingagents.agents.utils import event_log as el
from tradingagents.portfolio_advisor.price_util import weekly_return_pct_yfinance


def weekly_email_worth_sending(
    cfg: Dict[str, Any],
    digest: str,
    live: Set[str],
    *,
    attention_flag: bool,
) -> bool:
    """Return True when the weekly digest should go out on SMTP or webhook."""
    if attention_flag:
        return True
    u = (digest or "").upper()
    if "CRITICAL" in u or "HIGH" in u:
        return True
    for row in reversed(el._iter_events(cfg, max_lines=4000)):
        if str(row.get("event_type")) != "post_earnings_verdict":
            continue
        sym = str(row.get("ticker", "")).strip().upper()
        if sym not in live:
            continue
        kd = row.get("key_data") if isinstance(row.get("key_data"), dict) else {}
        ex = str(kd.get("excerpt", "")).upper()
        if "WEAKENING" in ex or "BROKEN" in ex:
            return True
    today = date.today()
    for sym in live:
        ed = next_earnings_from_yfinance(sym)
        if ed is None:
            continue
        d0 = (ed - today).days
        if 0 <= d0 <= 7:
            return True
    for sym in live:
        wr = weekly_return_pct_yfinance(sym, lookback_days=7)
        if wr is not None and abs(float(wr)) > 5.0:
            return True
    return False
