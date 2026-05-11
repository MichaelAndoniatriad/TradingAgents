# tradingagents/advisor/llm_digest.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from langchain_core.messages import HumanMessage

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

from tradingagents.advisor.positions import PositionSpec
from tradingagents.advisor.rules import AdvisorAlert

if TYPE_CHECKING:
    from typing import Any, Dict

logger = logging.getLogger(__name__)


def build_digest_prompt(
    positions: List[PositionSpec],
    alerts: List[AdvisorAlert],
    rule_digest_text: str,
) -> str:
    lines = [
        "You are a disciplined portfolio co-pilot. The user has binding mechanical rules already applied.",
        "Produce a short briefing (max 12 bullet points) that:",
        "1) Restates each CRITICAL/WARNING alert in plain language.",
        "2) Adds one sentence on execution priority if multiple alerts conflict.",
        "3) If no alerts, say holdings look routine and suggest what to monitor before the next check.",
        "",
        "Positions (ticker, entry, notes):",
    ]
    for p in positions:
        lines.append(
            f"- {p.ticker}: entry {p.entry_price:.4f}; notes: {p.notes or '—'}"
        )
        if p.thesis_break_metrics:
            lines.append(f"  Thesis-break metrics: {'; '.join(p.thesis_break_metrics)}")
    lines.append("")
    lines.append("Rule engine output:")
    lines.append(rule_digest_text or "(none)")
    return "\n".join(lines)


def generate_llm_digest(
    positions: List[PositionSpec],
    alerts: List[AdvisorAlert],
    rule_digest_text: str,
    config: "Dict[str, Any] | None" = None,
) -> str:
    """Single quick-model call for a narrative layer on top of deterministic rules."""
    cfg = (config or DEFAULT_CONFIG).copy()
    kwargs = {}
    provider = (cfg.get("llm_provider") or "openai").lower()
    if provider == "google" and cfg.get("google_thinking_level"):
        kwargs["thinking_level"] = cfg["google_thinking_level"]
    if provider == "openai" and cfg.get("openai_reasoning_effort"):
        kwargs["reasoning_effort"] = cfg["openai_reasoning_effort"]
    if provider == "anthropic" and cfg.get("anthropic_effort"):
        kwargs["effort"] = cfg["anthropic_effort"]

    client = create_llm_client(
        provider=provider,
        model=cfg.get("quick_think_llm", "gpt-5.4-mini"),
        base_url=cfg.get("backend_url"),
        **kwargs,
    )
    llm = client.get_llm()
    prompt = build_digest_prompt(positions, alerts, rule_digest_text)
    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        content = getattr(msg, "content", str(msg))
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = "\n".join(parts) if parts else str(content)
        return str(content).strip()
    except Exception as e:
        logger.exception("LLM digest failed: %s", e)
        return f"(LLM digest unavailable: {e})"
