"""One reasoning model pass for scheduled advisor jobs (no LangGraph).

Prompt branches by ``job_type`` so each scheduled job class produces a memo with
the section contract its downstream consumer expects. See ``_build_prompt``
below; the four templates share a header block, the VERDICT line, and the
DATA GAPS / output-rules tail, but each defines its own middle sections.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from tradingagents.agents.utils.event_log import append_event, format_recent_events_for_ticker
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.llm_clients import create_llm_client
from tradingagents.portfolio_advisor import messaging, price_util
from tradingagents.portfolio_advisor.prompt_limits import cfg_int

logger = logging.getLogger(__name__)


_OUTPUT_RULES = """Rules for this output (apply without exception):
- No dashes of any kind. No em dashes, en dashes, hyphens as separators or list bullets.
- No filler words (just, really, basically, simply, notably).
- No AI patterns (leverage, seamlessly, robust, comprehensive, actionable, transformative, it is worth noting, furthermore).
- Verdicts before reasoning. State the conclusion first.
- If a data point is missing, say so explicitly. Do not estimate or invent figures."""


_THESIS_CHECK_PROMPT = """You are the desk lead reviewing one open name. Advisory only. No trade orders.
{shared}

Deliver exactly these sections (plain text, no decorative separators):

THESIS CHECK {sym} {today}

VERDICT
State INTACT, WEAKENING, or BROKEN. One sentence. State it first.

HYPOTHESIS STATUS
One paragraph. Is the original investment thesis still supported by the evidence above?
Cite specific data points from memory or JSONL. Do not generalise.

RISK FLAGS
Up to three flags. Each: flag name, one sentence description, HIGH or MEDIUM or LOW.
If none: none.

NEXT CATALYST
What is the next event that would confirm or break the thesis? Date if known.

DATA GAPS
List any missing figures explicitly. Do not guess prices or dates not shown above.

{rules}
"""


_WEEKLY_SUMMARY_PROMPT = """You are the desk lead running a weekly pass on one open name. Advisory only. No trade orders.
{shared}

Deliver exactly these sections (plain text, no decorative separators):

WEEKLY SUMMARY {sym} {today}

VERDICT
State INTACT, WEAKENING, or BROKEN. One sentence. State it first.

PAST WEEK
Two to three sentences. What happened to price and thesis this week?
If nothing material: say so explicitly.

POSITION STATUS
Current gain or loss from entry. Any active rule triggers (pre-earnings trim, drawdown floor, double from entry)?
State the rule and the required action if triggered. If no triggers: none.

UPCOMING
Any known catalysts in the next 14 days? Earnings date if scheduled. If none: none.

DATA GAPS
List any missing figures explicitly. Do not guess prices or dates not shown above.

{rules}
"""


_POST_EARNINGS_PROMPT = """You are the desk lead running a post-earnings review on one open name. Advisory only. No trade orders.
{shared}

Deliver exactly these sections (plain text, no decorative separators):

POST EARNINGS REVIEW {sym} {today}

VERDICT
State INTACT, WEAKENING, or BROKEN. One sentence. State it first.

EARNINGS RESULT
Three to four sentences. Beat or miss on revenue, earnings, guidance. Be specific with numbers.
If numbers are not in the context above, say what is missing. Do not invent figures.

THESIS IMPACT
Did the print confirm or challenge the investment thesis? One paragraph.
Reference the thesis-break metrics if present in memory context.

REQUIRED ACTION
Explicit human action or none. If thesis is BROKEN: state full exit within 48 hours.
If WEAKENING: state what would confirm a break. If INTACT: none.

DATA GAPS
List any missing figures explicitly. Do not guess prices or dates not shown above.

{rules}
"""


_ROUTINE_MONITORING_PROMPT = """You are the desk lead doing a routine check on one open name. Advisory only. No trade orders.
{shared}

Deliver exactly these sections (plain text, no decorative separators):

ROUTINE CHECK {sym} {today}

VERDICT
State INTACT, WEAKENING, or BROKEN. One sentence. State it first.

STATUS
Three to five bullets. Price vs thesis, any rule triggers, what changed since last check.
If nothing changed: say so. Do not pad.

WATCH
One item to monitor before the next scheduled check. Be specific.

DATA GAPS
List any missing figures explicitly. Do not guess prices or dates not shown above.

{rules}
"""


_JOB_TYPE_PROMPTS = {
    "thesis_check": _THESIS_CHECK_PROMPT,
    "weekly_summary": _WEEKLY_SUMMARY_PROMPT,
    "post_earnings": _POST_EARNINGS_PROMPT,
    "routine_monitoring": _ROUTINE_MONITORING_PROMPT,
}


def _build_prompt(
    cfg: Dict[str, Any],
    jt: str,
    sym: str,
    today: str,
    px_line: str,
    md_ctx: str,
    ev_ctx: str,
) -> str:
    """Pick a per-job-type prompt and inject the shared header + output rules."""
    md_max = cfg_int(cfg, "portfolio_advisor_single_model_memory_chars", 6800, 500, 30000)
    ev_max = cfg_int(cfg, "portfolio_advisor_single_model_events_chars", 4800, 500, 30000)
    shared_header = (
        f"Ticker: {sym}\n"
        f"As of: {today}\n"
        f"Price line: {px_line}\n"
        f"Markdown memory (trimmed): {(md_ctx or 'none')[:md_max]}\n"
        f"JSONL tail (trimmed): {(ev_ctx or 'none')[:ev_max]}"
    )
    template = _JOB_TYPE_PROMPTS.get(jt, _ROUTINE_MONITORING_PROMPT)
    return template.format(sym=sym, today=today, shared=shared_header, rules=_OUTPUT_RULES)


def _reasoning_llm(cfg: Dict[str, Any]):
    model = (
        cfg.get("portfolio_advisor_single_model_reasoning_model")
        or cfg.get("portfolio_advisor_reasoning_model")
        or "deepseek/deepseek-r1"
    ).strip()
    provider = (cfg.get("llm_provider") or "openrouter").lower()
    if "/" in model and provider != "openrouter":
        provider = "openrouter"
    base = cfg.get("corporate_openrouter_base_url") or cfg.get("backend_url")
    return create_llm_client(provider, model, base_url=base).get_llm()


def run_single_model_analysis(
    cfg: Dict[str, Any],
    ticker: str,
    job_type: str,
) -> str:
    """Structured one shot memo for thesis_check, weekly_summary, post_earnings, routine_monitoring."""
    sym = (ticker or "").strip().upper()
    if not sym:
        raise ValueError("ticker required")
    jt = (job_type or "routine_monitoring").strip().lower()

    px = price_util.last_close_yfinance(sym)
    px_line = f"Last close from public feed: {px:.6f}" if px is not None else "Last close: missing (no public print returned)"

    mem = TradingMemoryLog(cfg)
    lookback = int(cfg.get("memory_context_lookback_days") or 90)
    ev_days = int(cfg.get("memory_event_log_prompt_days") or 30)
    md_ctx = mem.get_past_context(
        sym,
        n_same=int(cfg.get("memory_context_max_same_ticker") or 5),
        n_cross=int(cfg.get("memory_context_max_cross_ticker") or 2),
        lookback_days=lookback,
    )
    ev_ctx = format_recent_events_for_ticker(cfg, sym, days=ev_days, max_events=20)

    today = date.today().isoformat()
    prompt = _build_prompt(cfg, jt, sym, today, px_line, md_ctx, ev_ctx)
    llm = _reasoning_llm(cfg)
    msg = llm.invoke([HumanMessage(content=prompt)])
    content = getattr(msg, "content", str(msg))
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        content = "\n".join(parts) if parts else str(content)
    text = str(content).strip()
    if bool(cfg.get("portfolio_advisor_single_model_notify", False)):
        subj = f"{sym} {jt.replace('_', ' ')}"
        messaging.send_advisor_message(cfg, subj, messaging.ntfy_verdict(text, sym))
    append_event(
        cfg,
        {
            "ticker": sym,
            "event_type": "single_model_analysis",
            "key_data": {"job_type": jt, "date": today, "excerpt": text[:900]},
            "outcome": None,
        },
    )
    return text
