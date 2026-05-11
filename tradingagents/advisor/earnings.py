# tradingagents/advisor/earnings.py

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


def parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def next_earnings_from_yfinance(ticker: str) -> Optional[date]:
    """Best-effort next earnings date from yfinance (may be empty for some tickers)."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        cal = getattr(t, "calendar", None)
        if cal is None:
            return None
        # calendar can be DataFrame or dict-like depending on yfinance version
        if hasattr(cal, "empty") and cal.empty:
            return None
        if hasattr(cal, "T"):
            cal = cal.T
        # Try common keys
        if isinstance(cal, dict):
            for key in ("Earnings Date", "Earnings", "earningsDate"):
                val = cal.get(key)
                if val is not None:
                    return _coerce_calendar_value(val)
            return None
        # DataFrame: look for row or column
        try:
            import pandas as pd

            if hasattr(cal, "index") and "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"]
                if hasattr(val, "iloc"):
                    val = val.iloc[0]
                return _coerce_calendar_value(val)
            if "Earnings Date" in getattr(cal, "columns", []):
                val = cal["Earnings Date"].iloc[0]
                return _coerce_calendar_value(val)
        except Exception as e:
            logger.debug("yfinance calendar parse for %s: %s", ticker, e)
        return None
    except Exception as e:
        logger.warning("Could not fetch earnings calendar for %s: %s", ticker, e)
        return None


def _coerce_calendar_value(val) -> Optional[date]:
    if val is None:
        return None
    try:
        import pandas as pd

        if isinstance(val, pd.Timestamp):
            return val.date()
        if hasattr(val, "date") and callable(val.date):
            return val.date()
    except Exception:
        pass
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        return parse_iso_date(val)
    return None
