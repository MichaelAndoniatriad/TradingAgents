# tests/test_clerk_triggers.py

from datetime import date
from pathlib import Path

import pytest

from tradingagents.clerk.triggers import collect_deep_research_reasons
from tradingagents.clerk.watchlist import ClerkTriggers, ClerkWatchlist


def test_collect_new_headlines():
    tr = ClerkTriggers(deep_research_on_new_headlines=True)
    r = collect_deep_research_reasons(
        "TEST",
        date(2026, 5, 1),
        tr,
        new_headline_items=[{"title": "Something happened"}],
        bootstrap_baseline=False,
    )
    assert "new_headlines" in r


def test_bootstrap_suppresses_triggers():
    tr = ClerkTriggers(deep_research_on_new_headlines=True)
    r = collect_deep_research_reasons(
        "TEST",
        date(2026, 5, 1),
        tr,
        new_headline_items=[{"title": "Huge"}],
        bootstrap_baseline=True,
    )
    assert r == []


def test_keyword_in_new_headline():
    tr = ClerkTriggers(
        deep_research_on_new_headlines=False,
        deep_research_keyword_hits=["SEC"],
    )
    r = collect_deep_research_reasons(
        "TEST",
        date(2026, 5, 1),
        tr,
        new_headline_items=[{"title": "Company receives SEC inquiry"}],
        bootstrap_baseline=False,
    )
    assert "keyword_in_new_headline" in r


def test_earnings_window(monkeypatch):
    from tradingagents.clerk import triggers as trg

    monkeypatch.setattr(
        trg,
        "next_earnings_from_yfinance",
        lambda ticker: date(2026, 5, 4),
    )
    tr = ClerkTriggers(deep_research_earnings_within_days=5)
    r = collect_deep_research_reasons(
        "TEST",
        date(2026, 5, 1),
        tr,
        new_headline_items=[],
        bootstrap_baseline=False,
    )
    assert any(x.startswith("earnings_within") for x in r)


def test_watchlist_from_path(tmp_path: Path):
    p = tmp_path / "w.json"
    p.write_text(
        '{"tickers": ["abc"], "deep_research_analysts": ["news"], '
        '"triggers": {"deep_research_on_new_headlines": false}}',
        encoding="utf-8",
    )
    wl = ClerkWatchlist.from_path(p)
    assert wl.tickers == ["ABC"]
    assert wl.deep_research_analysts == ["news"]
    assert wl.triggers.deep_research_on_new_headlines is False


def test_watchlist_requires_tickers(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text('{"tickers": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        ClerkWatchlist.from_path(p)
