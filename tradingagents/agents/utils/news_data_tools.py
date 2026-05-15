import hashlib
import os
import time

from langchain_core.tools import tool
from typing import Annotated, Optional
from tradingagents.dataflows.interface import route_to_vendor

_NEWS_CACHE_TTL_HOURS = 4.0


def _news_cache_dir() -> str:
    from tradingagents.dataflows.config import get_config
    return get_config()["data_cache_dir"]


def _news_cache_path(cache_key: str) -> str:
    safe_key = hashlib.sha256(cache_key.encode()).hexdigest()[:24]
    return os.path.join(_news_cache_dir(), f"news-{safe_key}.txt")


def _news_cache_get(cache_key: str) -> str | None:
    path = _news_cache_path(cache_key)
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < _NEWS_CACHE_TTL_HOURS * 3600:
            with open(path, encoding="utf-8") as f:
                return f.read()
    return None


def _news_cache_set(cache_key: str, value: str) -> None:
    os.makedirs(_news_cache_dir(), exist_ok=True)
    path = _news_cache_path(cache_key)
    with open(path, "w", encoding="utf-8") as f:
        f.write(value)


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    cache_key = f"news|{ticker.upper()}|{start_date}|{end_date}"
    cached = _news_cache_get(cache_key)
    if cached is not None:
        return cached
    result = route_to_vendor("get_news", ticker, start_date, end_date)
    _news_cache_set(cache_key, result)
    return result

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[Optional[int], "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[Optional[int], "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    cache_key = f"global_news|{curr_date}|{look_back_days}|{limit}"
    cached = _news_cache_get(cache_key)
    if cached is not None:
        return cached
    result = route_to_vendor("get_global_news", curr_date, look_back_days, limit)
    _news_cache_set(cache_key, result)
    return result

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
