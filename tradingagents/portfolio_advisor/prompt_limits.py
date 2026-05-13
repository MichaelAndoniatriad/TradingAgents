"""Shared integer limits for portfolio-advisor LLM prompts (chars, row counts)."""

from __future__ import annotations

from typing import Any, Dict


def cfg_int(cfg: Dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(cfg.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))
