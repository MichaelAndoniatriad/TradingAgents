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
from tradingagents.portfolio_advisor import etoro_scan
from tradingagents.portfolio_advisor.candidates import (
    append_candidate_records,
    evaluate_candidates_with_evidence,
    queue_candidate_research_jobs,
    run_promoted_candidate_pm_comparison,
)

logger = logging.getLogger(__name__)


def load_monthly_candidate_items(path: Path) -> Tuple[List[Any], str]:
    """Return (candidate items, optional theme notes). Items may be strings or objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Monthly candidates JSON must be an object")
    raw = data.get("candidates") or data.get("tickers") or []
    if not isinstance(raw, list) or not raw:
        raise ValueError("'candidates' (or 'tickers') must be a non-empty array")
    theme = str(data.get("theme") or data.get("notes") or "").strip()
    return raw, theme


def load_monthly_candidates(path: Path) -> Tuple[List[str], str]:
    """Return (uppercased tickers, optional theme notes). Backwards-compatible helper."""
    raw, theme = load_monthly_candidate_items(path)
    tickers = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            tickers.append(item.strip().upper())
        elif isinstance(item, dict):
            t = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
            if t:
                tickers.append(t)
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
    raw_candidates, theme = load_monthly_candidate_items(candidates_path)
    try:
        _p, _t, live_raw, _rows = etoro_scan.fetch_portfolio_rows()
        live_tickers = {str(t).strip().upper() for t in live_raw if str(t).strip()}
    except Exception:
        live_tickers = set()
    candidate_records = evaluate_candidates_with_evidence(
        cfg,
        raw_candidates,
        live_tickers=live_tickers,
        theme=theme,
    )
    append_candidate_records(cfg, candidate_records)
    queued_light = queue_candidate_research_jobs(cfg, candidate_records)
    pm_compared = 0
    pm_compare_error = ""
    try:
        pm_compared = run_promoted_candidate_pm_comparison(
            cfg,
            candidate_records,
            live_tickers=live_tickers,
        )
    except Exception as e:
        logger.warning("candidate PM comparison failed: %s", e)
        pm_compare_error = str(e)

    eligible = [r for r in candidate_records if r.status in {"research_queued", "promoted"}]
    tickers = [r.ticker for r in eligible]
    cap = max(0, min(int(max_deep), len(tickers)))
    use_analysts = analysts or ["market", "social", "news", "fundamentals"]

    lines = [
        f"# Clerk — monthly lookout ({td})",
        "",
        f"_Generated (UTC): {datetime.utcnow().isoformat()}Z_",
        "",
        f"Candidates file: `{candidates_path}`",
        f"Theme / notes: {theme or '—'}",
        f"Candidate gate: {len(candidate_records)} reviewed, {len(eligible)} eligible, {queued_light} light checks queued.",
        f"PM candidate comparisons: {pm_compared}" + (f" (error: {pm_compare_error})" if pm_compare_error else ""),
        f"Deep runs this pass (cap {cap}): {', '.join(tickers[:cap]) if cap else 'none'}",
        "",
    ]

    lines.append("## Candidate gate\n")
    for r in candidate_records:
        fail = f" failures={','.join(r.gate_failures)}" if r.gate_failures else ""
        lines.append(f"- **{r.ticker}** — `{r.status}` priority={r.priority}{fail}. {r.next_action}")
    lines.append("")

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
    if not tickers:
        lines.append("\n_No candidates passed gates for deep research this month._\n")

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
