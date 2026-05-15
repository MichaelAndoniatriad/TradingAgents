from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf
import os
from .stockstats_utils import StockstatsUtils, _clean_dataframe, yf_retry, load_ohlcv, filter_financials_by_date

def get_YFin_data_online(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    # Create ticker object
    ticker = yf.Ticker(symbol.upper())

    # Fetch historical data for the specified date range
    data = yf_retry(lambda: ticker.history(start=start_date, end=end_date))

    # Check if data is empty
    if data.empty:
        return (
            f"No data found for symbol '{symbol}' between {start_date} and {end_date}"
        )

    # Remove timezone info from index for cleaner output
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    # Round numerical values to 2 decimal places for cleaner display
    numeric_columns = ["Open", "High", "Low", "Close", "Adj Close"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(2)

    # Convert DataFrame to CSV string
    csv_string = data.to_csv()

    # Add header information
    header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string

def get_stock_stats_indicators_window(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[
        str, "The current trading date you are trading on, YYYY-mm-dd"
    ],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:

    best_ind_params = {
        # Moving Averages
        "close_50_sma": (
            "50 SMA: A medium-term trend indicator. "
            "Usage: Identify trend direction and serve as dynamic support/resistance. "
            "Tips: It lags price; combine with faster indicators for timely signals."
        ),
        "close_200_sma": (
            "200 SMA: A long-term trend benchmark. "
            "Usage: Confirm overall market trend and identify golden/death cross setups. "
            "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
        ),
        "close_10_ema": (
            "10 EMA: A responsive short-term average. "
            "Usage: Capture quick shifts in momentum and potential entry points. "
            "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
        ),
        # MACD Related
        "macd": (
            "MACD: Computes momentum via differences of EMAs. "
            "Usage: Look for crossovers and divergence as signals of trend changes. "
            "Tips: Confirm with other indicators in low-volatility or sideways markets."
        ),
        "macds": (
            "MACD Signal: An EMA smoothing of the MACD line. "
            "Usage: Use crossovers with the MACD line to trigger trades. "
            "Tips: Should be part of a broader strategy to avoid false positives."
        ),
        "macdh": (
            "MACD Histogram: Shows the gap between the MACD line and its signal. "
            "Usage: Visualize momentum strength and spot divergence early. "
            "Tips: Can be volatile; complement with additional filters in fast-moving markets."
        ),
        # Momentum Indicators
        "rsi": (
            "RSI: Measures momentum to flag overbought/oversold conditions. "
            "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
            "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
        ),
        # Volatility Indicators
        "boll": (
            "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
            "Usage: Acts as a dynamic benchmark for price movement. "
            "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
        ),
        "boll_ub": (
            "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
            "Usage: Signals potential overbought conditions and breakout zones. "
            "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
        ),
        "boll_lb": (
            "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
            "Usage: Indicates potential oversold conditions. "
            "Tips: Use additional analysis to avoid false reversal signals."
        ),
        "atr": (
            "ATR: Averages true range to measure volatility. "
            "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
            "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
        ),
        # Volume-Based Indicators
        "vwma": (
            "VWMA: A moving average weighted by volume. "
            "Usage: Confirm trends by integrating price action with volume data. "
            "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
        ),
        "mfi": (
            "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
            "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
            "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
        ),
    }

    if indicator not in best_ind_params:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    # Optimized: Get stock data once and calculate indicators for all dates
    try:
        indicator_data = _get_stock_stats_bulk(symbol, indicator, curr_date)
        
        # Generate the date range we need
        current_dt = curr_date_dt
        date_values = []
        
        while current_dt >= before:
            date_str = current_dt.strftime('%Y-%m-%d')
            
            # Look up the indicator value for this date
            if date_str in indicator_data:
                indicator_value = indicator_data[date_str]
            else:
                indicator_value = "N/A: Not a trading day (weekend or holiday)"
            
            date_values.append((date_str, indicator_value))
            current_dt = current_dt - relativedelta(days=1)
        
        # Build the result string
        ind_string = ""
        for date_str, value in date_values:
            ind_string += f"{date_str}: {value}\n"
        
    except Exception as e:
        print(f"Error getting bulk stockstats data: {e}")
        # Fallback to original implementation if bulk method fails
        ind_string = ""
        curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        while curr_date_dt >= before:
            indicator_value = get_stockstats_indicator(
                symbol, indicator, curr_date_dt.strftime("%Y-%m-%d")
            )
            ind_string += f"{curr_date_dt.strftime('%Y-%m-%d')}: {indicator_value}\n"
            curr_date_dt = curr_date_dt - relativedelta(days=1)

    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "No description available.")
    )

    return result_str


def _get_stock_stats_bulk(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to calculate"],
    curr_date: Annotated[str, "current date for reference"]
) -> dict:
    """
    Optimized bulk calculation of stock stats indicators.
    Fetches data once and calculates indicator for all available dates.
    Returns dict mapping date strings to indicator values.
    """
    from stockstats import wrap

    data = load_ohlcv(symbol, curr_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    
    # Calculate the indicator for all rows at once
    df[indicator]  # This triggers stockstats to calculate the indicator
    
    # Create a dictionary mapping date strings to indicator values
    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]
        
        # Handle NaN/None values
        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)
    
    return result_dict


def get_stockstats_indicator(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[
        str, "The current trading date you are trading on, YYYY-mm-dd"
    ],
) -> str:

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    curr_date = curr_date_dt.strftime("%Y-%m-%d")

    try:
        indicator_value = StockstatsUtils.get_stock_stats(
            symbol,
            indicator,
            curr_date,
        )
    except Exception as e:
        print(
            f"Error getting stockstats indicator data for indicator {indicator} on {curr_date}: {e}"
        )
        return ""

    return str(indicator_value)


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date (not used for yfinance)"] = None
):
    """Get company fundamentals overview from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        info = yf_retry(lambda: ticker_obj.info)

        if not info:
            return f"No fundamentals data found for symbol '{ticker}'"

        fields = [
            ("Name", info.get("longName")),
            ("Sector", info.get("sector")),
            ("Industry", info.get("industry")),
            ("Market Cap", info.get("marketCap")),
            ("PE Ratio (TTM)", info.get("trailingPE")),
            ("Forward PE", info.get("forwardPE")),
            ("PEG Ratio", info.get("pegRatio")),
            ("Price to Book", info.get("priceToBook")),
            ("EPS (TTM)", info.get("trailingEps")),
            ("Forward EPS", info.get("forwardEps")),
            ("Dividend Yield", info.get("dividendYield")),
            ("Beta", info.get("beta")),
            ("52 Week High", info.get("fiftyTwoWeekHigh")),
            ("52 Week Low", info.get("fiftyTwoWeekLow")),
            ("50 Day Average", info.get("fiftyDayAverage")),
            ("200 Day Average", info.get("twoHundredDayAverage")),
            ("Revenue (TTM)", info.get("totalRevenue")),
            ("Gross Profit", info.get("grossProfits")),
            ("EBITDA", info.get("ebitda")),
            ("Net Income", info.get("netIncomeToCommon")),
            ("Profit Margin", info.get("profitMargins")),
            ("Operating Margin", info.get("operatingMargins")),
            ("Return on Equity", info.get("returnOnEquity")),
            ("Return on Assets", info.get("returnOnAssets")),
            ("Debt to Equity", info.get("debtToEquity")),
            ("Current Ratio", info.get("currentRatio")),
            ("Book Value", info.get("bookValue")),
            ("Free Cash Flow", info.get("freeCashflow")),
        ]

        lines = []
        for label, value in fields:
            if value is not None:
                lines.append(f"{label}: {value}")

        header = f"# Company Fundamentals for {ticker.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving fundamentals for {ticker}: {str(e)}"


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None
):
    """Get balance sheet data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())

        if freq.lower() == "quarterly":
            data = yf_retry(lambda: ticker_obj.quarterly_balance_sheet)
        else:
            data = yf_retry(lambda: ticker_obj.balance_sheet)

        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            return f"No balance sheet data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Balance Sheet data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving balance sheet for {ticker}: {str(e)}"


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None
):
    """Get cash flow data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())

        if freq.lower() == "quarterly":
            data = yf_retry(lambda: ticker_obj.quarterly_cashflow)
        else:
            data = yf_retry(lambda: ticker_obj.cashflow)

        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            return f"No cash flow data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Cash Flow data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving cash flow for {ticker}: {str(e)}"


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None
):
    """Get income statement data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())

        if freq.lower() == "quarterly":
            data = yf_retry(lambda: ticker_obj.quarterly_income_stmt)
        else:
            data = yf_retry(lambda: ticker_obj.income_stmt)

        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            return f"No income statement data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Income Statement data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving income statement for {ticker}: {str(e)}"


def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"]
):
    """Get insider transactions data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        data = yf_retry(lambda: ticker_obj.insider_transactions)

        if data is None or data.empty:
            return f"No insider transactions data found for symbol '{ticker}'"

        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()

        # Add header information
        header = f"# Insider Transactions data for {ticker.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving insider transactions for {ticker}: {str(e)}"


def get_stock_summary(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current trading date, YYYY-MM-DD"],
    days: Annotated[int, "number of recent trading days to include in OHLCV table"] = 60,
) -> str:
    """Return a concise OHLCV summary: last N days, 52-week range, SMA context, and trend direction.

    Use this instead of get_stock_data to avoid injecting the full 5-year CSV into the prompt.
    """
    try:
        data = load_ohlcv(symbol, curr_date)
        if data.empty:
            return f"No data found for {symbol}"

        data = data.copy()
        data["Date"] = pd.to_datetime(data["Date"])
        data = data.sort_values("Date").reset_index(drop=True)

        close = data["Close"]
        current_price = round(float(close.iloc[-1]), 2)

        # 52-week range
        one_year_ago = pd.to_datetime(curr_date) - pd.DateOffset(weeks=52)
        year_data = data[data["Date"] >= one_year_ago]
        week52_high = round(float(year_data["High"].max()), 2) if not year_data.empty else None
        week52_low = round(float(year_data["Low"].min()), 2) if not year_data.empty else None

        # SMAs
        sma50 = round(float(close.tail(50).mean()), 2) if len(close) >= 50 else round(float(close.mean()), 2)
        sma200 = round(float(close.tail(200).mean()), 2) if len(close) >= 200 else round(float(close.mean()), 2)

        # Volume
        avg_vol_30d = int(data["Volume"].tail(30).mean())
        avg_vol_full = int(data["Volume"].mean())

        # Trend direction based on SMA relationships
        if current_price > sma50 and sma50 > sma200:
            trend = "uptrend (price > 50 SMA > 200 SMA)"
        elif current_price < sma50 and sma50 < sma200:
            trend = "downtrend (price < 50 SMA < 200 SMA)"
        elif current_price > sma50 and sma50 < sma200:
            trend = "mixed/recovering (price above 50 SMA, but 50 SMA still below 200 SMA)"
        elif current_price < sma50 and sma50 > sma200:
            trend = "mixed/weakening (price below 50 SMA, but 50 SMA still above 200 SMA)"
        else:
            trend = "sideways"

        lines = [
            f"# Stock Summary for {symbol.upper()} as of {curr_date}",
            f"Current Price: {current_price}",
            f"52-Week High: {week52_high if week52_high is not None else 'N/A'}",
            f"52-Week Low: {week52_low if week52_low is not None else 'N/A'}",
            f"50-Day SMA: {sma50} (price is {'above' if current_price > sma50 else 'below'})",
            f"200-Day SMA: {sma200} (price is {'above' if current_price > sma200 else 'below'})",
            f"30-Day Avg Volume: {avg_vol_30d:,}",
            f"Full-Period Avg Volume: {avg_vol_full:,}",
            f"Trend: {trend}",
            f"",
            f"## Last {days} Trading Days (OHLCV)",
        ]

        recent = data.tail(days).copy()
        recent["Date"] = recent["Date"].dt.strftime("%Y-%m-%d")
        for col in ["Open", "High", "Low", "Close"]:
            if col in recent.columns:
                recent[col] = recent[col].round(2)

        return "\n".join(lines) + "\n" + recent.to_csv(index=False)

    except Exception as e:
        return f"Error retrieving stock summary for {symbol}: {str(e)}"


def get_fundamentals_summary(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Return key financial metrics extracted from income statement, balance sheet, and cash flow.

    Returns revenue trend, margins, net income, FCF, debt, and EPS for the last 4 quarters.
    Use this instead of get_balance_sheet + get_income_statement to reduce prompt size.
    """
    try:
        ticker_obj = yf.Ticker(ticker.upper())

        income_q = yf_retry(lambda: ticker_obj.quarterly_income_stmt)
        balance_q = yf_retry(lambda: ticker_obj.quarterly_balance_sheet)
        cashflow_q = yf_retry(lambda: ticker_obj.quarterly_cashflow)
        info = yf_retry(lambda: ticker_obj.info) or {}

        income_q = filter_financials_by_date(income_q, curr_date)
        balance_q = filter_financials_by_date(balance_q, curr_date)
        cashflow_q = filter_financials_by_date(cashflow_q, curr_date)

        lines = [f"# Fundamentals Summary for {ticker.upper()}"]
        if curr_date:
            lines.append(f"# As of {curr_date}")
        lines.append("")

        def _fmt_m(val):
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return "N/A"
            return f"${val / 1e6:.1f}M"

        def _fmt_pct(val):
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return "N/A"
            return f"{val * 100:.1f}%"

        def _get_row(df, *names):
            for name in names:
                if not df.empty and name in df.index:
                    return df.loc[name]
            return None

        def _col_label(col):
            try:
                return pd.Timestamp(col).strftime("%Y-%m")
            except Exception:
                return str(col)

        # Revenue — last 4 quarters + YoY growth
        revenue = _get_row(income_q, "Total Revenue")
        if revenue is not None:
            cols = revenue.dropna().index[:4]
            lines.append("## Revenue (last 4 quarters)")
            for col in cols:
                lines.append(f"  {_col_label(col)}: {_fmt_m(revenue[col])}")
            if len(cols) >= 4:
                v0, v3 = revenue[cols[0]], revenue[cols[3]]
                if v3 and not pd.isna(v3) and v3 != 0:
                    lines.append(f"  YoY Growth (latest vs 4Q ago): {_fmt_pct((v0 - v3) / abs(v3))}")
            lines.append("")

        # Gross Margin and Operating Margin (latest quarter)
        gross_profit = _get_row(income_q, "Gross Profit")
        op_income = _get_row(income_q, "Operating Income", "EBIT")
        if revenue is not None:
            latest_col = revenue.dropna().index[:1]
            if len(latest_col) > 0:
                col = latest_col[0]
                rev_val = revenue.get(col)
                if rev_val and not pd.isna(rev_val) and rev_val != 0:
                    if gross_profit is not None and col in gross_profit.index:
                        lines.append(f"Gross Margin (latest Q): {_fmt_pct(gross_profit[col] / rev_val)}")
                    if op_income is not None and col in op_income.index:
                        lines.append(f"Operating Margin (latest Q): {_fmt_pct(op_income[col] / rev_val)}")
            lines.append("")

        # Net Income — last 4 quarters
        net_income = _get_row(income_q, "Net Income")
        if net_income is not None:
            cols = net_income.dropna().index[:4]
            lines.append("## Net Income (last 4 quarters)")
            for col in cols:
                lines.append(f"  {_col_label(col)}: {_fmt_m(net_income[col])}")
            lines.append("")

        # Free Cash Flow — last 4 quarters
        fcf = _get_row(cashflow_q, "Free Cash Flow")
        if fcf is None:
            # Fallback: Operating CF - CapEx
            ocf = _get_row(cashflow_q, "Operating Cash Flow")
            capex = _get_row(cashflow_q, "Capital Expenditure")
            if ocf is not None and capex is not None:
                fcf = ocf.add(capex, fill_value=0)
        if fcf is not None:
            cols = fcf.dropna().index[:4]
            lines.append("## Free Cash Flow (last 4 quarters)")
            for col in cols:
                lines.append(f"  {_col_label(col)}: {_fmt_m(fcf[col])}")
            lines.append("")

        # Total Debt and Debt/Equity
        total_debt = _get_row(balance_q, "Total Debt", "Long Term Debt")
        if total_debt is not None:
            cols = total_debt.dropna().index[:1]
            if len(cols) > 0:
                lines.append(f"Total Debt (latest Q): {_fmt_m(total_debt[cols[0]])}")
        de_ratio = info.get("debtToEquity")
        if de_ratio is not None:
            lines.append(f"Debt/Equity Ratio: {de_ratio:.2f}")
        lines.append("")

        # EPS — last 4 quarters + YoY growth
        eps = _get_row(income_q, "Diluted EPS", "Basic EPS")
        if eps is not None:
            cols = eps.dropna().index[:4]
            lines.append("## EPS (last 4 quarters)")
            for col in cols:
                val = eps[col]
                lines.append(f"  {_col_label(col)}: {'N/A' if pd.isna(val) else f'{val:.2f}'}")
            if len(cols) >= 4:
                v0, v3 = eps[cols[0]], eps[cols[3]]
                if not pd.isna(v0) and not pd.isna(v3) and v3 != 0:
                    lines.append(f"  YoY Growth (latest vs 4Q ago): {_fmt_pct((v0 - v3) / abs(v3))}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving fundamentals summary for {ticker}: {str(e)}"