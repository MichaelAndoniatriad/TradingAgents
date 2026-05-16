"""Tests for CostLoggingCallback token extraction and cost estimation.

Covers the three usage-extraction paths in on_llm_end and the versioned-slug
pricing lookup added in the ecaa05c fix.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from tradingagents.llm_clients.cost_logger import (
    CostLoggingCallback,
    estimate_cost_usd,
)


# ---------------------------------------------------------------------------
# estimate_cost_usd — pricing table lookups
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,prompt,completion,expected", [
    # Direct slug
    ("google/gemini-2.0-flash-001", 1000, 500, round((1000 * 0.10 + 500 * 0.40) / 1_000_000, 6)),
    # Versioned slugs added explicitly (ecaa05c)
    ("anthropic/claude-4.5-sonnet-20250929", 10_000, 2_000, round((10_000 * 3.00 + 2_000 * 15.00) / 1_000_000, 6)),
    ("anthropic/claude-4.6-sonnet-20260217", 10_000, 2_000, round((10_000 * 3.00 + 2_000 * 15.00) / 1_000_000, 6)),
    ("deepseek/deepseek-v4-pro-20260423", 10_000, 2_000, round((10_000 * 0.27 + 2_000 * 1.10) / 1_000_000, 6)),
    ("deepseek/deepseek-v4-flash-20260423", 10_000, 2_000, round((10_000 * 0.10 + 2_000 * 0.40) / 1_000_000, 6)),
    ("openai/gpt-5.5-20260423", 10_000, 2_000, round((10_000 * 5.00 + 2_000 * 15.00) / 1_000_000, 6)),
    # Future date suffix not in table — strips to base slug
    ("deepseek/deepseek-v4-flash-20991231", 1_000, 100, round((1_000 * 0.10 + 100 * 0.40) / 1_000_000, 6)),
    ("openai/gpt-5.5-20991231", 1_000, 100, round((1_000 * 5.00 + 100 * 15.00) / 1_000_000, 6)),
    # Completely unknown model
    ("unknown/model-xyz", 1_000, 500, None),
])
def test_estimate_cost_usd(model, prompt, completion, expected):
    result = estimate_cost_usd(model, prompt, completion)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Helpers to build mock LLMResult objects shaped like each provider returns
# ---------------------------------------------------------------------------

def _make_message_mock(usage_metadata: dict | None = None) -> MagicMock:
    msg = MagicMock()
    msg.usage_metadata = usage_metadata
    return msg


def _make_gen_mock(generation_info: dict | None = None, message=None) -> MagicMock:
    gen = MagicMock()
    gen.generation_info = generation_info or {}
    gen.message = message
    return gen


def _make_llm_result(
    llm_output: dict | None = None,
    gen_info: dict | None = None,
    usage_metadata: dict | None = None,
    model_name: str = "openai/gpt-5.5-20260423",
) -> MagicMock:
    """Build a minimal mock LLMResult matching langchain-core's structure."""
    result = MagicMock()
    result.llm_output = llm_output or {}
    message = _make_message_mock(usage_metadata)
    gen = _make_gen_mock(generation_info=gen_info, message=message)
    result.generations = [[gen]]
    return result


# ---------------------------------------------------------------------------
# Callback tests — each using the shape a specific provider actually returns
# ---------------------------------------------------------------------------

def _run_callback(llm_result, tags: list[str] | None = None) -> dict:
    """Run the callback with a temp log file and return the written record."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = Path(f.name)
    cb = CostLoggingCallback(log_path=log_path)
    cb.on_llm_end(llm_result, tags=tags or [])
    line = log_path.read_text().strip()
    log_path.unlink(missing_ok=True)
    return json.loads(line)


def test_callback_openai_router_pattern():
    """OpenRouter via langchain-openai: usage is in llm_output['token_usage']."""
    result = _make_llm_result(
        llm_output={
            "model_name": "openai/gpt-5.5-20260423",
            "token_usage": {
                "prompt_tokens": 11_207,
                "completion_tokens": 2_168,
                "total_tokens": 13_375,
            },
        },
    )
    rec = _run_callback(result)
    assert rec["model"] == "openai/gpt-5.5-20260423"
    assert rec["prompt_tokens"] == 11_207
    assert rec["completion_tokens"] == 2_168
    assert rec["cost_usd"] == pytest.approx(
        estimate_cost_usd("openai/gpt-5.5-20260423", 11_207, 2_168)
    )
    assert rec["cost_usd"] is not None


def test_callback_anthropic_openrouter_pattern():
    """Anthropic via OpenRouter: versioned slug in model_name, token_usage in llm_output."""
    result = _make_llm_result(
        llm_output={
            "model_name": "anthropic/claude-4.5-sonnet-20250929",
            "token_usage": {
                "prompt_tokens": 12_274,
                "completion_tokens": 2_527,
            },
        },
    )
    rec = _run_callback(result)
    assert rec["model"] == "anthropic/claude-4.5-sonnet-20250929"
    assert rec["prompt_tokens"] == 12_274
    assert rec["cost_usd"] is not None


def test_callback_gemini_generation_info_pattern():
    """Gemini via langchain-google: usage in generation_info (llm_output is empty)."""
    result = _make_llm_result(
        llm_output={"model_name": "google/gemini-2.0-flash-001"},
        gen_info={
            "usage": {
                "prompt_tokens": 1_087,
                "completion_tokens": 115,
            }
        },
    )
    rec = _run_callback(result)
    assert rec["model"] == "google/gemini-2.0-flash-001"
    assert rec["prompt_tokens"] == 1_087
    assert rec["completion_tokens"] == 115
    assert rec["cost_usd"] is not None


def test_callback_usage_metadata_pattern():
    """Fallback: usage in message.usage_metadata (input_tokens / output_tokens keys)."""
    result = _make_llm_result(
        llm_output={"model_name": "deepseek/deepseek-v4-pro-20260423"},
        usage_metadata={"input_tokens": 11_052, "output_tokens": 2_312},
    )
    rec = _run_callback(result)
    assert rec["model"] == "deepseek/deepseek-v4-pro-20260423"
    assert rec["prompt_tokens"] == 11_052
    assert rec["completion_tokens"] == 2_312
    assert rec["cost_usd"] is not None


def test_callback_unknown_model_logs_null_cost():
    """Unknown models write the record with cost_usd=null — never crash."""
    result = _make_llm_result(
        llm_output={
            "model_name": "provider/unknown-future-model",
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )
    rec = _run_callback(result)
    assert rec["prompt_tokens"] == 100
    assert rec["cost_usd"] is None
