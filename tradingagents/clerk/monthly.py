# tradingagents/clerk/monthly.py
"""Monthly 'lookout': deep research on a small candidate list + consolidated LLM read."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

from tradingagents.clerk.deep_runner import run_deep_research, save_deep_report
from tradingagents.clerk.notify import get_clerk_webhook_url, post_text

logger = logging.getLogger(__name__)


def load_monthly_candidates(path: Path) -> Tuple[List[str], str]:
    """Return (uppercased tickers, optional theme notes)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Monthly candidates JSON must be an object")
    raw = data.get("candidates") or data.get("tickers") or []
    if not isinstance(raw, list) or not raw:
        raise ValueError("'candidates' (or 'tickers') must be a non-empty array")
    tickers = [str(t).strip().upper() for t in raw if str(t).strip()]
    theme = str(data.get("theme") or data.get("notes") or "").strip()
    return tickers, theme


def _summarize_monthly(
    sections: List[str],
    theme: str,
    config: Dict[str, Any],
) -> str:
    cfg = config.copy()
    provider = (cfg.get("llm_provider") or "openai").lower()
    kwargs: Dict[str, Any] = {}
    if provider == "google" and cfg.get("google_thinking_level"):
        kwargs["thinking_level"] = cfg["google_thinking_level"]
    if provider == "openai" and cfg.get("openai_reasoning_effort"):
        kwargs["reasoning_effort"] = cfg["openai_reasoning_effort"]
    if provider == "anthropic" and cfg.get("anthropic_effort"):
        kwargs["effort"] = cfg["anthropic_effort"]

    client = create_llm_client(
        provider=provider,
        model=cfg.get("deep_think_llm") or cfg.get("quick_think_llm", "gpt-5.4-mini"),
        base_url=cfg.get("backend_url"),
        **kwargs,
    )
    llm = client.get_llm()
    body = "\n\n---\n\n".join(sections)[:28000]
    prompt = (
        "You are a research director doing a **monthly portfolio lookout**.\n"
        "Each section below is a full multi-agent dossier summary for one candidate name.\n"
        "Your job:\n"
        "1) Rank the candidates for potential portfolio fit (highest conviction first).\n"
        "2) State clearly which **one** name (if any) deserves capital this month and why — "
        "or recommend **none** if every dossier fails basic quality / risk gates.\n"
        "3) Two sentences on what would change your mind next month.\n"
        f"Theme / notes from the user file: {theme or '(none)'}\n"
        "Stay under 400 words. Not personalized investment advice — analytical memo only.\n\n"
        "--- Candidate dossiers (truncated) ---\n\n"
        f"{body}"
    )
    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        content = getattr(msg, "content", str(msg))
        if isinstance(content, list):
            bits = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    bits.append(block.get("text", ""))
            content = "\n".join(bits) if bits else str(content)
        return str(content).strip()
    except Exception as e:
        logger.exception("Monthly lookout LLM failed: %s", e)
        return f"(Monthly synthesis unavailable: {e})"


def run_monthly_lookout(
    candidates_path: Path,
    *,
    trade_date: Optional[str] = None,
    max_deep: int = 2,
    analysts: Optional[List[str]] = None,
    webhook_url: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Run capped deep research on candidates + one consolidation memo."""
    cfg = (config or DEFAULT_CONFIG).copy()
    td = trade_date or date.today().strftime("%Y-%m-%d")
    tickers, theme = load_monthly_candidates(candidates_path)
    cap = max(1, min(int(max_deep), len(tickers)))
    use_analysts = analysts or ["market", "social", "news", "fundamentals"]

    lines = [
        f"# Clerk — monthly lookout ({td})",
        "",
        f"_Generated (UTC): {datetime.utcnow().isoformat()}Z_",
        "",
        f"Candidates file: `{candidates_path}`",
        f"Theme / notes: {theme or '—'}",
        f"Deep runs this pass (cap {cap}): {', '.join(tickers[:cap])}",
        "",
    ]

    sections: List[str] = []
    for t in tickers[:cap]:
        try:
            final_state, decision = run_deep_research(t, td, use_analysts, cfg)
            save_deep_report(
                results_dir=Path(cfg["results_dir"]),
                ticker=t,
                trade_date=td,
                final_state=final_state,
            )
            dec = str(decision)[:4000]
            sections.append(f"## {t}\n\n**Final signal (trimmed):**\n{dec}\n")
            lines.append(f"- **{t}:** deep research saved under `results/.../clerk_deep/{t}/`.")
        except Exception as e:
            logger.exception("Monthly deep failed for %s", t)
            lines.append(f"- **{t}:** FAILED — {e}")
            sections.append(f"## {t}\n\n(error: {e})\n")

    if len(tickers) > cap:
        lines.append(
            f"\n_Not run this month (over cap): {', '.join(tickers[cap:])}. "
            f"Raise `max_deep` or trim the candidate list._\n"
        )

    synth = _summarize_monthly(sections, theme, cfg)
    lines.append("\n## Monthly synthesis (LLM)\n\n")
    lines.append(synth)
    lines.append("")

    digest = "\n".join(lines)

    out_dir = Path(cfg["data_cache_dir"]) / "clerk" / "monthly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{td}.md"
    out_path.write_text(digest, encoding="utf-8")

    url = (webhook_url or "").strip() or get_clerk_webhook_url()
    if url:
        body = digest if len(digest) < 14000 else digest[:13900] + "\n…(truncated)"
        post_text(url, f"Clerk — monthly lookout\n\n{body}")

    return digest
