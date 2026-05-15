from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve full historical stock price data (OHLCV) for a given ticker symbol.
    Returns a raw CSV with up to 5 years of daily OHLCV rows.
    Prefer get_stock_summary for analyst prompts — only use this when full history is needed.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted dataframe containing the stock price data for the specified ticker symbol in the specified date range.
    """
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)


@tool
def get_stock_summary(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current trading date in yyyy-mm-dd format"],
    days: Annotated[int, "number of recent trading days to include in the OHLCV table, default 60"] = 60,
) -> str:
    """
    Retrieve a concise stock price summary instead of the full multi-year CSV.
    Returns last N days of OHLCV, 52-week high/low, price vs 50-day and 200-day SMA,
    average volume, and trend direction. Use this as the default tool for market analysis.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        curr_date (str): Current trading date in yyyy-mm-dd format
        days (int): Number of recent trading days to include (default 60)
    Returns:
        str: Concise summary with key price stats and recent OHLCV table.
    """
    return route_to_vendor("get_stock_summary", symbol, curr_date, days)
