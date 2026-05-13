"""Tests for Streamlit UI runtime config overlay."""

from __future__ import annotations

from ui import user_config as uc


def test_runtime_roundtrip_merge(tmp_path):
    home = tmp_path
    assert uc.load_runtime_overlay(home=home) == {}
    uc.save_runtime_overlay({"memory_context_lookback_days": 42}, home=home)
    assert uc.load_runtime_overlay(home=home) == {"memory_context_lookback_days": 42}

    cfg = uc.merged_app_config(home=home)
    assert cfg["memory_context_lookback_days"] == 42

    uc.save_runtime_overlay(
        uc.build_overlay_from_scalars_and_routing(
            {"memory_context_lookback_days": 90},
            {"news_analyst": {"model": "google/gemini-2.0-flash-001"}},
            home=home,
        ),
        home=home,
    )
    cfg2 = uc.merged_app_config(home=home)
    assert cfg2["memory_context_lookback_days"] == 90
    assert cfg2["agent_llm_routing"]["news_analyst"]["model"] == "google/gemini-2.0-flash-001"

    eff = uc.effective_corporate_routing(cfg2)
    assert eff["news_analyst"]["model"] == "google/gemini-2.0-flash-001"
    assert "market_analyst" in eff


def test_runtime_json_invalid_graceful(tmp_path):
    p = uc.runtime_config_path(home=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json {{{", encoding="utf-8")
    assert uc.load_runtime_overlay(home=tmp_path) == {}
    assert isinstance(uc.merged_app_config(home=tmp_path), dict)
