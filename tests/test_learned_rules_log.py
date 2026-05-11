"""Tests for append-only learned rules (outcome → quick LLM → learned_rules.md)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.utils import learned_rules_log as lr


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('["a", "b"]', ["a", "b"]),
        ("```json\n[]\n```", []),
        ("```\n[\"x\"]\n```", ["x"]),
        ("prefix [\"only\"] suffix", ["only"]),
        ("", []),
        ("not json", []),
    ],
)
def test_parse_json_string_list(raw, expected):
    assert lr._parse_json_string_list(raw) == expected


def test_learned_rules_path_respects_enabled_and_default(tmp_path):
    mem = tmp_path / "memory" / "trading_memory.md"
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text("x", encoding="utf-8")
    cfg = {
        "learned_rules_enabled": True,
        "learned_rules_path": None,
        "memory_log_path": str(mem),
    }
    p = lr.learned_rules_path_for_config(cfg)
    assert p == mem.parent / "learned_rules.md"


def test_learned_rules_path_disabled():
    cfg = {"learned_rules_enabled": False, "memory_log_path": "/tmp/x.md"}
    assert lr.learned_rules_path_for_config(cfg) is None


def test_append_and_read_roundtrip(tmp_path):
    mem = tmp_path / "m.md"
    cfg = {
        "learned_rules_enabled": True,
        "learned_rules_path": str(tmp_path / "lr.md"),
        "memory_log_path": str(mem),
    }
    lr.append_learned_rules_block(
        cfg,
        ticker="NVDA",
        trade_date="2026-01-10",
        raw_return=0.05,
        alpha_return=0.02,
        benchmark_name="SPY",
        rules=["Trim into strength before earnings when up 15%+."],
    )
    text = lr.read_learned_rules_excerpt(cfg, max_chars=5000)
    assert "NVDA" in text
    assert "Trim into strength" in text


def test_propose_calls_llm_and_caps_rules():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content='["r1", "r2", "r3", "r4"]')
    out = lr.propose_learned_rule_lines(
        llm,
        ticker="AAPL",
        trade_date="2026-01-01",
        raw_return=-0.02,
        alpha_return=-0.01,
        benchmark_name="SPY",
        reflection="Sized too large into a weak report.",
        existing_excerpt="",
        max_rules=2,
    )
    assert out == ["r1", "r2"]
    llm.invoke.assert_called_once()
