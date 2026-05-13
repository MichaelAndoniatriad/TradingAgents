"""Tests for clerk_deep prior-report helpers (bootstrap resume + graph context)."""

from __future__ import annotations

from pathlib import Path

from tradingagents.clerk import deep_runner as dr


def test_has_clerk_report_for_trade_date(tmp_path: Path) -> None:
    sym = "TEST"
    td = "2026-05-13"
    p = tmp_path / "clerk_deep" / sym / f"{td}_clerk_triggered.md"
    assert dr.has_clerk_report_for_trade_date(tmp_path, sym, td) is False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    assert dr.has_clerk_report_for_trade_date(tmp_path, sym, td) is True


def test_load_latest_prior_clerk_report_text_picks_newest(tmp_path: Path) -> None:
    base = tmp_path / "clerk_deep" / "ZZ"
    base.mkdir(parents=True, exist_ok=True)
    old = base / "2026-01-01_clerk_triggered.md"
    new = base / "2026-05-10_clerk_triggered.md"
    old.write_text("OLD", encoding="utf-8")
    new.write_text("NEWER_BODY", encoding="utf-8")
    out = dr.load_latest_prior_clerk_report_text(results_dir=tmp_path, ticker="zz", max_chars=10_000)
    assert "NEWER" in out
    assert "OLD" not in out


def test_load_latest_prior_clerk_report_text_truncates(tmp_path: Path) -> None:
    base = tmp_path / "clerk_deep" / "AB"
    base.mkdir(parents=True, exist_ok=True)
    f = base / "2026-05-01_clerk_triggered.md"
    f.write_text("A" * 500, encoding="utf-8")
    out = dr.load_latest_prior_clerk_report_text(results_dir=tmp_path, ticker="AB", max_chars=200)
    assert "truncated" in out
    assert len(out) <= 250
