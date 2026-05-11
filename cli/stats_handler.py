import threading
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.messages import AIMessage


class StatsCallbackHandler(BaseCallbackHandler):
    """Callback handler that tracks LLM calls, tool calls, and token usage."""

    def __init__(
        self,
        *,
        model_pricing: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        # model_name -> {"llm_calls": int, "tokens_in": int, "tokens_out": int}
        self.model_stats: Dict[str, Dict[str, int]] = {}
        # model_name -> {"input_per_1m": float, "output_per_1m": float}
        self.model_pricing = model_pricing or {}
        # run_id -> model_name
        self._run_model: Dict[str, str] = {}

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when an LLM starts."""
        with self._lock:
            self.llm_calls += 1

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when a chat model starts."""
        with self._lock:
            self.llm_calls += 1
            run_id = str(kwargs.get("run_id") or "")
            model = self._extract_model_name(serialized=serialized, kwargs=kwargs)
            if run_id and model:
                self._run_model[run_id] = model
            if model:
                stats = self.model_stats.setdefault(
                    model, {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0}
                )
                stats["llm_calls"] += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from LLM response."""
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        if usage_metadata:
            with self._lock:
                input_tokens = int(usage_metadata.get("input_tokens", 0) or 0)
                output_tokens = int(usage_metadata.get("output_tokens", 0) or 0)
                self.tokens_in += input_tokens
                self.tokens_out += output_tokens
                model = self._extract_model_name(response=response, kwargs=kwargs)
                if model:
                    stats = self.model_stats.setdefault(
                        model, {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0}
                    )
                    stats["tokens_in"] += input_tokens
                    stats["tokens_out"] += output_tokens

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Increment tool call counter when a tool starts."""
        with self._lock:
            self.tool_calls += 1

    def get_stats(self) -> Dict[str, Any]:
        """Return current statistics."""
        with self._lock:
            priced_models = {}
            total_estimated_cost = 0.0
            for model_name, usage in self.model_stats.items():
                pricing = self.model_pricing.get(model_name) or {}
                input_per_1m = float(pricing.get("input_per_1m", 0.0) or 0.0)
                output_per_1m = float(pricing.get("output_per_1m", 0.0) or 0.0)
                estimated_cost = (
                    usage["tokens_in"] / 1_000_000 * input_per_1m
                    + usage["tokens_out"] / 1_000_000 * output_per_1m
                )
                total_estimated_cost += estimated_cost
                priced_models[model_name] = {
                    **usage,
                    "input_per_1m": input_per_1m,
                    "output_per_1m": output_per_1m,
                    "estimated_cost_usd": estimated_cost,
                }
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "models": priced_models,
                "estimated_cost_usd": total_estimated_cost,
            }

    def _extract_model_name(
        self,
        *,
        serialized: Optional[Dict[str, Any]] = None,
        response: Optional[LLMResult] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Best-effort model name extraction across providers/langchain wrappers."""
        kwargs = kwargs or {}
        # 1) Response metadata (most reliable at end of call)
        if response is not None and hasattr(response, "llm_output"):
            llm_output = getattr(response, "llm_output", {}) or {}
            for key in ("model_name", "model", "model_id"):
                value = llm_output.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        # 2) Callback kwargs may include invocation params
        invocation = kwargs.get("invocation_params") or kwargs.get("params") or {}
        if isinstance(invocation, dict):
            for key in ("model", "model_name", "model_id"):
                value = invocation.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        # 3) Serialized object from LangChain model
        data = serialized or {}
        if isinstance(data, dict):
            root_kwargs = data.get("kwargs", {}) if isinstance(data.get("kwargs"), dict) else {}
            for source in (data, root_kwargs):
                for key in ("model", "model_name", "model_id"):
                    value = source.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

        # 4) Fallback from run_id mapping captured on start
        run_id = str(kwargs.get("run_id") or "")
        if run_id:
            return self._run_model.get(run_id)
        return None
