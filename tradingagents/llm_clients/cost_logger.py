"""Token/cost logging for every LLM call.

Writes a JSONL line per LLM completion to ``$TRADINGAGENTS_COST_LOG`` (default
``~/.tradingagents/logs/cost.jsonl``) so spend can be aggregated offline.

Pricing is in USD per 1M tokens. Unknown models log with ``cost_usd=null``;
update ``PRICING`` when adding routing entries.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


PRICING: dict[str, tuple[float, float]] = {
    # OpenRouter slugs used by DEFAULT_CORPORATE_AGENT_ROUTING and advisor layer
    "deepseek/deepseek-v4-flash": (0.10, 0.40),
    "deepseek/deepseek-v4-pro": (0.27, 1.10),
    "deepseek/deepseek-r1": (0.55, 2.20),
    "deepseek/deepseek-chat": (0.27, 1.10),
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "openai/gpt-5.5": (5.00, 15.00),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/o1-mini": (3.00, 12.00),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
}


def _default_log_path() -> Path:
    override = os.environ.get("TRADINGAGENTS_COST_LOG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".tradingagents" / "logs" / "cost.jsonl"


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    rate = PRICING.get(model)
    if rate is None:
        return None
    in_per_m, out_per_m = rate
    return round((prompt_tokens * in_per_m + completion_tokens * out_per_m) / 1_000_000, 6)


_WRITE_LOCK = threading.Lock()


class CostLoggingCallback(BaseCallbackHandler):
    """Append one JSON record per LLM call to the cost log."""

    raise_error = False
    run_inline = True

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._log_path = log_path or _default_log_path()
        self._ensured = False

    def _ensure_dir(self) -> None:
        if self._ensured:
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensured = True

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> None:
        try:
            llm_output = response.llm_output or {}
            usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion_tokens = int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )
            model = (
                llm_output.get("model_name")
                or llm_output.get("model")
                or kwargs.get("invocation_params", {}).get("model")
                or "unknown"
            )
            if prompt_tokens == 0 and completion_tokens == 0:
                # langchain-openai sometimes parks usage on generation metadata
                for gen_group in response.generations:
                    for gen in gen_group:
                        info = getattr(gen, "generation_info", None) or {}
                        gen_usage = info.get("usage") or info.get("token_usage") or {}
                        prompt_tokens += int(
                            gen_usage.get("prompt_tokens") or gen_usage.get("input_tokens") or 0
                        )
                        completion_tokens += int(
                            gen_usage.get("completion_tokens")
                            or gen_usage.get("output_tokens")
                            or 0
                        )
                        message = getattr(gen, "message", None)
                        meta_usage = getattr(message, "usage_metadata", None) if message else None
                        if meta_usage:
                            prompt_tokens += int(meta_usage.get("input_tokens") or 0)
                            completion_tokens += int(meta_usage.get("output_tokens") or 0)

            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost_usd": estimate_cost_usd(model, prompt_tokens, completion_tokens),
                "tags": list(tags or []),
                "run_id": str(run_id) if run_id is not None else None,
                "parent_run_id": str(parent_run_id) if parent_run_id is not None else None,
            }
            self._ensure_dir()
            line = json.dumps(record, separators=(",", ":")) + "\n"
            with _WRITE_LOCK:
                with self._log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except Exception:
            # Never let cost logging break an LLM call.
            return


_DEFAULT_INSTANCE: Optional[CostLoggingCallback] = None
_INSTANCE_LOCK = threading.Lock()


def get_default_cost_callback() -> CostLoggingCallback:
    """Process-wide singleton so all LLM clients append to the same file."""
    global _DEFAULT_INSTANCE
    if _DEFAULT_INSTANCE is None:
        with _INSTANCE_LOCK:
            if _DEFAULT_INSTANCE is None:
                _DEFAULT_INSTANCE = CostLoggingCallback()
    return _DEFAULT_INSTANCE
