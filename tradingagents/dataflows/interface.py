import os
import threading
import time
from collections import OrderedDict
from typing import Annotated

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
    get_stock_summary as get_yfinance_stock_summary,
    get_fundamentals_summary as get_yfinance_fundamentals_summary,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data",
            "get_stock_summary",
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
            "get_fundamentals_summary",
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    "get_stock_summary": {
        "yfinance": get_yfinance_stock_summary,
        "alpha_vantage": get_yfinance_stock_summary,  # no AV impl; fall through to yfinance
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    "get_fundamentals_summary": {
        "yfinance": get_yfinance_fundamentals_summary,
        "alpha_vantage": get_yfinance_fundamentals_summary,  # no AV impl; fall through to yfinance
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

# In-process TTL cache so the news, market, and fundamentals analysts (and any
# downstream agents in the same graph cycle) don't each independently re-fetch
# the same OHLCV/news/fundamentals payload. Disable with
# ``TRADINGAGENTS_VENDOR_CACHE_DISABLE=1``. Tune TTL via
# ``TRADINGAGENTS_VENDOR_CACHE_TTL_SECONDS`` (default 600s).
_VENDOR_CACHE_LOCK = threading.Lock()
_VENDOR_CACHE: "OrderedDict[tuple, tuple[float, object]]" = OrderedDict()
_VENDOR_CACHE_MAX_ENTRIES = 256


def _vendor_cache_enabled() -> bool:
    return os.environ.get("TRADINGAGENTS_VENDOR_CACHE_DISABLE") != "1"


def _vendor_cache_ttl() -> int:
    try:
        return int(os.environ.get("TRADINGAGENTS_VENDOR_CACHE_TTL_SECONDS", "600"))
    except ValueError:
        return 600


def _vendor_cache_key(method: str, args: tuple, kwargs: dict):
    try:
        return (method, args, tuple(sorted(kwargs.items())))
    except TypeError:
        return None


def _vendor_cache_get(key) -> tuple[bool, object]:
    if key is None:
        return False, None
    ttl = _vendor_cache_ttl()
    now = time.monotonic()
    with _VENDOR_CACHE_LOCK:
        hit = _VENDOR_CACHE.get(key)
        if hit is None:
            return False, None
        ts, value = hit
        if now - ts >= ttl:
            _VENDOR_CACHE.pop(key, None)
            return False, None
        _VENDOR_CACHE.move_to_end(key)
        return True, value


def _vendor_cache_put(key, value) -> None:
    if key is None:
        return
    with _VENDOR_CACHE_LOCK:
        _VENDOR_CACHE[key] = (time.monotonic(), value)
        _VENDOR_CACHE.move_to_end(key)
        while len(_VENDOR_CACHE) > _VENDOR_CACHE_MAX_ENTRIES:
            _VENDOR_CACHE.popitem(last=False)


def clear_vendor_cache() -> None:
    """Flush the per-cycle data cache (test hook / manual reset)."""
    with _VENDOR_CACHE_LOCK:
        _VENDOR_CACHE.clear()


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    cache_enabled = _vendor_cache_enabled()
    cache_key = _vendor_cache_key(method, args, kwargs) if cache_enabled else None
    if cache_enabled:
        hit, cached = _vendor_cache_get(cache_key)
        if hit:
            return cached

    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            result = impl_func(*args, **kwargs)
            if cache_enabled:
                _vendor_cache_put(cache_key, result)
            return result
        except AlphaVantageRateLimitError:
            continue  # Only rate limits trigger fallback

    raise RuntimeError(f"No available vendor for '{method}'")