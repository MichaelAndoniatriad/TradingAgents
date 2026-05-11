"""Append-only learned rules derived from resolved outcomes + reflections.

Rules are proposed by the quick LLM and written to disk; decision agents read
the tail of the file via get_investor_policy_* helpers in agent_utils.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def learned_rules_path_for_config(cfg: Dict[str, Any]) -> Optional[Path]:
    if not cfg.get("learned_rules_enabled", True):
        return None
    raw = cfg.get("learned_rules_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser()
    mem = cfg.get("memory_log_path")
    if not mem:
        return None
    return Path(mem).expanduser().parent / "learned_rules.md"


def read_learned_rules_excerpt(cfg: Dict[str, Any], max_chars: int = 6000) -> str:
    path = learned_rules_path_for_config(cfg)
    if path is None or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read learned rules file %s: %s", path, e)
        return ""
    text = text.strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _parse_json_string_list(content: str) -> List[str]:
    t = (content or "").strip()
    if not t:
        return []
    if "```" in t:
        chunks = re.split(r"```(?:json)?", t, flags=re.IGNORECASE)
        for chunk in chunks:
            chunk = chunk.strip()
            if chunk.startswith("["):
                t = chunk
                break
    try:
        data = json.loads(t)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[[\s\S]*\]", t)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except json.JSONDecodeError:
            return []
    return []


def propose_learned_rule_lines(
    llm: Any,
    *,
    ticker: str,
    trade_date: str,
    raw_return: float,
    alpha_return: float,
    benchmark_name: str,
    reflection: str,
    existing_excerpt: str,
    max_rules: int = 2,
) -> List[str]:
    """Ask the quick model for 0..max_rules short imperative desk rules."""
    excerpt = (existing_excerpt or "")[-8000:]
    prompt = (
        "You maintain an append-only list of trading-desk habits learned from real outcomes.\n"
        "Given the reflection and performance numbers, propose NEW rules only if they add "
        "something not already implied by the excerpt.\n\n"
        "Constraints:\n"
        "- Output a JSON array of strings only (no markdown fences, no prose outside JSON).\n"
        f"- At most {max_rules} rules; each rule is one imperative sentence, under 160 characters.\n"
        "- Rules must be consistent with normal risk management (no 'ignore stop losses').\n"
        "- If the excerpt already covers the lesson or there is nothing durable, output [].\n\n"
        f"Ticker: {ticker}\n"
        f"Decision date: {trade_date}\n"
        f"Raw return (over measurement window): {raw_return:+.1%}\n"
        f"Alpha vs {benchmark_name}: {alpha_return:+.1%}\n\n"
        f"Reflection:\n{reflection}\n\n"
        "--- Existing learned-rules tail (do not duplicate) ---\n"
        f"{excerpt if excerpt else '(empty)'}\n"
    )
    messages = [("human", prompt)]
    try:
        msg = llm.invoke(messages)
        raw = getattr(msg, "content", str(msg))
        if isinstance(raw, list):
            bits = []
            for block in raw:
                if isinstance(block, dict) and block.get("type") == "text":
                    bits.append(block.get("text", ""))
            raw = "\n".join(bits) if bits else str(raw)
        lines = _parse_json_string_list(str(raw))
        return lines[:max_rules]
    except Exception as e:
        logger.warning("learned-rules proposal failed: %s", e)
        return []


def append_learned_rules_block(
    cfg: Dict[str, Any],
    *,
    ticker: str,
    trade_date: str,
    raw_return: float,
    alpha_return: float,
    benchmark_name: str,
    rules: List[str],
) -> None:
    path = learned_rules_path_for_config(cfg)
    if path is None or not rules:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    block_lines = [
        "",
        f"### {trade_date} — {ticker} — raw {raw_return:+.1%}, alpha vs {benchmark_name} {alpha_return:+.1%}",
    ]
    for r in rules:
        block_lines.append(f"- {r}")
    block_lines.append("")
    block = "\n".join(block_lines)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        logger.warning("Could not append learned rules to %s: %s", path, e)


def maybe_extend_learned_rules_from_outcome(
    cfg: Dict[str, Any],
    quick_llm: Any,
    update: Dict[str, Any],
    benchmark_name: str,
) -> None:
    """Append 0–N new rules after a resolved pending entry (Phase B)."""
    if not cfg.get("learned_rules_enabled", True):
        return
    ticker = update["ticker"]
    trade_date = update["trade_date"]
    excerpt = read_learned_rules_excerpt(cfg, max_chars=12000)
    rules = propose_learned_rule_lines(
        quick_llm,
        ticker=ticker,
        trade_date=trade_date,
        raw_return=float(update["raw_return"]),
        alpha_return=float(update["alpha_return"]),
        benchmark_name=benchmark_name,
        reflection=str(update.get("reflection") or ""),
        existing_excerpt=excerpt,
    )
    append_learned_rules_block(
        cfg,
        ticker=ticker,
        trade_date=trade_date,
        raw_return=float(update["raw_return"]),
        alpha_return=float(update["alpha_return"]),
        benchmark_name=benchmark_name,
        rules=rules,
    )
