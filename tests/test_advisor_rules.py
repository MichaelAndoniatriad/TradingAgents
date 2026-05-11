# tests/test_advisor_rules.py

from datetime import date

import pytest

from tradingagents.advisor.positions import PositionSpec, load_positions_file
from tradingagents.advisor.rules import evaluate_position_rules


def test_dd40_exits_early():
    pos = PositionSpec(ticker="TEST", entry_price=100.0, next_earnings_date=None, fetch_earnings_from_yfinance=False)
    alerts = evaluate_position_rules(pos, current_price=59.0, as_of=date(2026, 5, 1))
    codes = [a.trigger_code for a in alerts]
    assert "dd40" in codes
    assert len(alerts) == 1


def test_t3_double_half():
    pos = PositionSpec(ticker="TEST", entry_price=50.0, fetch_earnings_from_yfinance=False)
    alerts = evaluate_position_rules(pos, current_price=100.0, as_of=date(2026, 5, 1))
    assert any(a.trigger_code == "t3_double_half" for a in alerts)


def test_dd30_warning():
    pos = PositionSpec(ticker="TEST", entry_price=100.0, fetch_earnings_from_yfinance=False)
    alerts = evaluate_position_rules(pos, current_price=65.0, as_of=date(2026, 5, 1))
    assert any(a.trigger_code == "dd30" for a in alerts)


def test_t1_pre_earnings_trim():
    pos = PositionSpec(
        ticker="TEST",
        entry_price=100.0,
        next_earnings_date="2026-05-05",
        fetch_earnings_from_yfinance=False,
    )
    alerts = evaluate_position_rules(pos, current_price=120.0, as_of=date(2026, 5, 1))
    assert any(a.trigger_code == "t1_pre_earnings_trim" for a in alerts)


def test_t2_thesis_reminder_near_earnings():
    pos = PositionSpec(
        ticker="TEST",
        entry_price=100.0,
        next_earnings_date="2026-05-03",
        fetch_earnings_from_yfinance=False,
        thesis_break_metrics=["Revenue growth >20% YoY"],
    )
    alerts = evaluate_position_rules(pos, current_price=101.0, as_of=date(2026, 5, 1))
    assert any(a.trigger_code == "t2_thesis_reminder" for a in alerts)


def test_load_positions_file(tmp_path):
    p = tmp_path / "pos.json"
    p.write_text(
        '{"positions": [{"ticker": "AAA", "entry_price": 10.5, "notes": "x"}]}',
        encoding="utf-8",
    )
    rows = load_positions_file(p)
    assert len(rows) == 1
    assert rows[0].ticker == "AAA"
    assert rows[0].entry_price == 10.5


def test_load_positions_file_rejects_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"positions": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_positions_file(p)
