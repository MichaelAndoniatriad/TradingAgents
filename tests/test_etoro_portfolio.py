# tests/test_etoro_portfolio.py

import json
from pathlib import Path

from tradingagents.integrations.etoro.clerk_bridge import _normalize_ticker
from tradingagents.integrations.etoro.portfolio import (
    dedupe_positions,
    iter_positions,
    portfolio_headlines,
    summarize_portfolio,
)


def test_normalize_ticker():
    assert _normalize_ticker("nvda") == "NVDA"
    assert _normalize_ticker("AAPL-US") == "AAPL"


def test_dedupe_mirror_positions():
    fixture = Path(__file__).parent / "fixtures" / "etoro_pnl_minimal.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    cp = data["clientPortfolio"]
    raw = list(iter_positions(cp))
    assert len(raw) == 3
    deduped = dedupe_positions(raw)
    assert len(deduped) == 2


def test_portfolio_headlines():
    fixture = Path(__file__).parent / "fixtures" / "etoro_pnl_minimal.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    h = portfolio_headlines(data)
    assert h["open_positions"] == 2


def test_summarize_portfolio():
    fixture = Path(__file__).parent / "fixtures" / "etoro_pnl_minimal.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    meta = {
        101: {"symbolFull": "TEST1", "instrumentDisplayName": "One"},
        202: {"symbolFull": "TEST2-US", "instrumentDisplayName": "Two"},
    }
    text, rows = summarize_portfolio(data, meta)
    assert "TEST1" in text
    assert len(rows) == 2
