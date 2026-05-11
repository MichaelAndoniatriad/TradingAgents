"""Read live eToro positions for the portfolio advisor."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Set, Tuple

from tradingagents.integrations.etoro.clerk_bridge import _normalize_ticker
from tradingagents.integrations.etoro.client import EtoroClient
from tradingagents.integrations.etoro.portfolio import (
    dedupe_positions,
    instrument_id_from_position,
    iter_positions,
    portfolio_headlines,
    summarize_portfolio,
)


def etoro_keys_configured() -> bool:
    return bool(
        (os.environ.get("ETORO_API_KEY") or "").strip()
        and (os.environ.get("ETORO_USER_KEY") or "").strip()
    )


def fetch_portfolio_rows() -> Tuple[Dict[str, Any], str, List[str], List[Dict[str, Any]]]:
    """Same as ``fetch_portfolio_bundle`` but also returns ``summarize_portfolio`` rows."""
    if not etoro_keys_configured():
        raise RuntimeError(
            "eToro keys missing: set ETORO_API_KEY and ETORO_USER_KEY in the environment."
        )
    client = EtoroClient()
    payload = client.get_portfolio_pnl()
    cp = payload.get("clientPortfolio") or {}
    positions = dedupe_positions(iter_positions(cp))
    ids: List[int] = []
    for p in positions:
        iid = instrument_id_from_position(p)
        if iid is not None:
            ids.append(iid)
    meta = client.get_instruments_metadata(ids) if ids else {}
    text, rows = summarize_portfolio(payload, meta)
    tickers = sorted(
        {
            _normalize_ticker(str(r.get("symbolFull") or ""))
            for r in rows
            if _normalize_ticker(str(r.get("symbolFull") or ""))
        }
    )
    hl = portfolio_headlines(payload)
    head = (
        f"Headlines: available_balance={hl.get('credit')!r}, "
        f"unrealized_pnl={hl.get('unrealized_pnl')!r}, "
        f"open_positions={hl.get('open_positions')!r}\n"
    )
    return payload, head + text, tickers, rows


def fetch_portfolio_bundle() -> Tuple[Dict[str, Any], str, List[str]]:
    """Return (raw_pnl_payload, summary_text, tickers_upper).

    Raises RuntimeError if keys missing or API fails.
    """
    payload, text, tickers, _rows = fetch_portfolio_rows()
    return payload, text, tickers


def current_ticker_set(tickers: List[str]) -> Set[str]:
    return {t.upper().strip() for t in tickers if t and str(t).strip()}
