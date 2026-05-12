"""Persisted UI/runtime overrides merged on top of DEFAULT_CONFIG.

Saved to ``~/.tradingagents/ui_runtime_config.json``. Cron and CLI do not read
this file unless explicitly wired; the Streamlit app documents that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from copy import deepcopy

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import DEFAULT_CORPORATE_AGENT_ROUTING

RUNTIME_FILENAME = "ui_runtime_config.json"

# Keys the UI may read/write in the JSON overlay (top-level merge).
OVERLAY_SCALAR_KEYS = (
    "memory_context_lookback_days",
    "memory_context_max_same_ticker",
    "memory_context_max_cross_ticker",
    "memory_event_log_prompt_days",
    "corporate_hierarchy_enabled",
    "llm_fallback_openrouter_model",
    "corporate_openrouter_base_url",
    "portfolio_advisor_planner_model",
    "portfolio_advisor_reasoning_model",
    "deep_think_llm",
    "quick_think_llm",
    "llm_provider",
    "backend_url",
)


def tradingagents_home(home: Optional[Path] = None) -> Path:
    base = home if home is not None else Path.home()
    return base / ".tradingagents"


def runtime_config_path(*, home: Optional[Path] = None) -> Path:
    return tradingagents_home(home) / RUNTIME_FILENAME


def load_runtime_overlay(*, home: Optional[Path] = None) -> Dict[str, Any]:
    path = runtime_config_path(home=home)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_runtime_overlay(data: Dict[str, Any], *, home: Optional[Path] = None) -> None:
    path = runtime_config_path(home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _deep_merge_agent_routing(base: Any, overlay: Any) -> Dict[str, Any]:
    b = deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(overlay, dict):
        return b
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(b.get(k), dict):
            inner = dict(b[k])
            inner.update(v)
            b[k] = inner
        else:
            b[k] = v
    return b


def merged_app_config(*, home: Optional[Path] = None) -> Dict[str, Any]:
    """Full config dict for UI and in-process advisor actions."""
    cfg = DEFAULT_CONFIG.copy()
    overlay = load_runtime_overlay(home=home)
    for key in OVERLAY_SCALAR_KEYS:
        if key not in overlay:
            continue
        val = overlay[key]
        ref = DEFAULT_CONFIG.get(key)
        if isinstance(ref, bool) and not isinstance(val, bool):
            cfg[key] = str(val).strip().lower() in ("true", "1", "yes", "on")
        elif isinstance(ref, int) and not isinstance(ref, bool):
            try:
                cfg[key] = int(val)
            except (TypeError, ValueError):
                pass
        elif val is None or val == "":
            if key in ("portfolio_advisor_planner_model", "portfolio_advisor_reasoning_model", "backend_url", "corporate_openrouter_base_url"):
                cfg[key] = None
            else:
                cfg[key] = val
        else:
            cfg[key] = val

    if "agent_llm_routing" in overlay and isinstance(overlay["agent_llm_routing"], dict):
        cfg["agent_llm_routing"] = _deep_merge_agent_routing(
            cfg.get("agent_llm_routing") or {},
            overlay["agent_llm_routing"],
        )
    return cfg


def build_overlay_from_scalars_and_routing(
    scalars: Dict[str, Any],
    agent_llm_routing: Dict[str, Any],
    *,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Merge into existing file: scalars + full routing dict."""
    current = load_runtime_overlay(home=home)
    out = dict(current)
    for k, v in scalars.items():
        if k in OVERLAY_SCALAR_KEYS:
            out[k] = v
    out["agent_llm_routing"] = agent_llm_routing
    return out


def effective_corporate_routing(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Same merge semantics as ``corporate_llm_factory._effective_routing_table`` (for UI display)."""
    base = deepcopy(DEFAULT_CORPORATE_AGENT_ROUTING)
    overrides = cfg.get("agent_llm_routing") or {}
    if isinstance(overrides, dict):
        for key, spec in overrides.items():
            if spec is None:
                continue
            if key not in base:
                base[key] = {}
            if isinstance(spec, dict):
                merged = {**base.get(key, {}), **spec}
                merged["provider"] = "openrouter"
                base[key] = merged
    for spec in base.values():
        if isinstance(spec, dict):
            spec["provider"] = "openrouter"
    return base
