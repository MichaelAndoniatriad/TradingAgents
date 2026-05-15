from __future__ import annotations

from tradingagents.portfolio_advisor.ticker_decision import extract_ticker_decision


def test_extract_ticker_decision_from_pm_markdown():
    md = (
        "> advisory\n\n"
        "**Rating**: Overweight\n\n"
        "**Confidence**: Medium\n\n"
        "**Executive Summary**: Consider adding only if revenue growth confirms. "
        "A thesis-break metric would be gross margin below 60%.\n\n"
        "**Investment Thesis**: The thesis is supported by demand, but would change if backlog weakens.\n\n"
        "**How to think about this**: Patient monitoring, not urgency."
    )

    decision = extract_ticker_decision(
        ticker="nvda",
        trade_date="2026-05-15",
        final_trade_decision=md,
        decision_id="dec1",
    )

    assert decision["decision_id"] == "dec1"
    assert decision["ticker"] == "NVDA"
    assert decision["rating"] == "Overweight"
    assert decision["confidence"] == "Medium"
    assert "revenue growth" in decision["summary"]
    assert "supported by demand" in decision["thesis"]
    assert decision["thesis_break_metrics"]
