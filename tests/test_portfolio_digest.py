# tests/test_portfolio_digest.py

from pathlib import Path

from tradingagents.clerk.portfolio_digest import build_daily_portfolio_markdown


def test_portfolio_digest_skips_without_etoro_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    md, used = build_daily_portfolio_markdown(cache_dir=tmp_path, trade_date="2026-05-15")
    assert not used
    assert "Skipped" in md or "skipped" in md.lower()
