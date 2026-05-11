# tradingagents/advisor/prices.py

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def fetch_last_close(tickers: List[str]) -> Dict[str, float]:
    """Fetch last close price per ticker via yfinance (best-effort)."""
    out: Dict[str, float] = {}
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance is required for advisor price checks")
        return out

    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="5d")
            if hist is None or hist.empty:
                logger.warning("No price history for %s", t)
                continue
            close = float(hist["Close"].iloc[-1])
            out[t.upper()] = close
        except Exception as e:
            logger.warning("Price fetch failed for %s: %s", t, e)
    return out
