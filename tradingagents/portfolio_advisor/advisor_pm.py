"""Advisor-level portfolio manager (PM): one structured LLM pass per cycle, logged to disk."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from tradingagents.agents.utils.event_log import append_event
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.structured import bind_structured
from tradingagents.dataflows.config import set_config
from tradingagents.llm_clients import create_llm_client
from tradingagents.portfolio_advisor import etoro_scan, state
from tradingagents.portfolio_advisor.models import AdvisorPMCycleResult
from tradingagents.portfolio_advisor.prompt_limits import cfg_int as _pm_int

logger = logging.getLogger(__name__)
_pm_memory_lock = threading.Lock()

# ---------------------------------------------------------------------------
# PM_CLAUDE.md + PM_MEMORY.md — structured memory system for the PM
# ---------------------------------------------------------------------------

_PM_CLAUDE_DEFAULT = """\
# Portfolio Manager Standing Instructions

You are the Portfolio Manager (PM) for a personal investment portfolio.

## Role
- Advisory only: you recommend, the human decides and executes.
- You hold the institutional memory: what we own, why, what the thesis is, what we learned.
- You are the human's intelligent partner — answer questions, flag risks, explain stances.

## Hard rules — never break these
- Never invent deadlines, cut rules, stop-loss triggers, position sizing rules, or trading constraints
  that the human has not explicitly stated. If you don't see it in the data you were given, it does not exist.
- Never say a ticker "must" be cut by a date or "should" be trimmed by X% unless the human told you so.
- If you are uncertain whether a rule exists, say "I don't have a rule for that — do you want to set one?"
- Pending jobs in the queue are SCHEDULED research jobs. They do not mean the ticker lacks analysis or is
  in crisis. Do not frame a May 26 scheduled job as "urgently awaiting thesis results."
- Only flag urgency when: (a) a job is overdue by >24h, (b) a catalyst is within 48h, or (c) the human
  explicitly asked for something and it hasn't run yet.

## When answering /ask questions via ntfy
- Answer directly. Verdict first, reasoning after.
- Stick to facts present in the portfolio snapshot, pending jobs, and memory. Do not extrapolate rules.
- Keep replies under 600 characters; the human reads them on a phone.

## When the human asks to run jobs sooner or immediately
- Use append_jobs to queue the relevant tickers right away. Do not just describe the situation.
- Pick the most appropriate job_type for each ticker (thesis_check, weekly_summary, post_earnings, or routine_monitoring).
- Use execution_tier "single_model" unless the human asks for a deep run.
- Execute immediately — no approval needed. Tell the human what you queued. They can reply CANCEL to undo.
- Example: human says "run NVDA sooner" -> append_jobs NVDA thesis_check single_model, notify "Queued NVDA thesis_check. Reply CANCEL to undo."

## Memory discipline
- Write memory_note as if briefing your next self: what mattered, what changed, what to watch.
- One tight paragraph. No filler. No AI patterns.
"""

_PM_MEMORY_SEPARATOR = "\n---\n"


def _pm_claude_path(cfg: Dict[str, Any]) -> Path:
    return state.advisor_dir(cfg) / "PM_CLAUDE.md"


def _pm_memory_structured_path(cfg: Dict[str, Any]) -> Path:
    return state.advisor_dir(cfg) / "PM_MEMORY.md"


def _ensure_pm_claude_md(cfg: Dict[str, Any]) -> None:
    p = _pm_claude_path(cfg)
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_PM_CLAUDE_DEFAULT, encoding="utf-8")


def _read_pm_claude_md(cfg: Dict[str, Any]) -> str:
    p = _pm_claude_path(cfg)
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_pm_memory_structured(cfg: Dict[str, Any]) -> str:
    p = _pm_memory_structured_path(cfg)
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    cap = _pm_int(cfg, "portfolio_advisor_pm_memory_md_prompt_chars", 6000, 500, 30000)
    return text[-cap:] if len(text) > cap else text


def _write_pm_memory_update(cfg: Dict[str, Any], memory_note: str, trigger: str) -> None:
    note = (memory_note or "").strip()
    if not note:
        return
    p = _pm_memory_structured_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"## {ts} — {trigger}\n{note}\n"
    existing = ""
    if p.is_file():
        try:
            existing = p.read_text(encoding="utf-8")
        except OSError:
            pass
    new_content = (existing + _PM_MEMORY_SEPARATOR + entry) if existing else entry
    max_chars = _pm_int(cfg, "portfolio_advisor_pm_memory_md_max_chars", 40000, 2000, 200000)
    if len(new_content) > max_chars:
        new_content = new_content[-max_chars:]
        idx = new_content.find("\n## ")
        if idx > 0:
            new_content = new_content[idx + 1:]
    p.write_text(new_content, encoding="utf-8")


def pm_log_path(cfg: Dict[str, Any]) -> Path:
    raw = cfg.get("portfolio_advisor_pm_log_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser()
    return state.advisor_dir(cfg) / "pm_council.jsonl"


_PM_ADVISOR_SENTINEL = "<!-- TRADINGAGENTS_PM_ADVISOR_LOG -->"


def _pm_unified_memory(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("portfolio_advisor_pm_unified_memory", True))


def pm_memory_path(cfg: Dict[str, Any]) -> Path:
    """Markdown trail for PM cycles: unified ``memory_log_path`` or advisor-local ``pm_memory.md``."""
    if _pm_unified_memory(cfg):
        raw = cfg.get("memory_log_path")
        if isinstance(raw, str) and raw.strip():
            p = Path(raw).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        logger.warning(
            "portfolio_advisor_pm_unified_memory is on but memory_log_path is unset; "
            "using advisor_dir/pm_memory.md"
        )
    return state.advisor_dir(cfg) / "pm_memory.md"


def _trading_memory_tail_for_pm(cfg: Dict[str, Any]) -> str:
    """Recent tail of LangGraph trading memory for PM prompt (unified mode only)."""
    if not _pm_unified_memory(cfg):
        return ""
    raw = cfg.get("memory_log_path")
    if not (isinstance(raw, str) and raw.strip()):
        return "(memory_log_path not set.)"
    try:
        mx = int(cfg.get("portfolio_advisor_pm_trading_memory_prompt_chars") or 6000)
    except (TypeError, ValueError):
        mx = 6000
    mx = max(400, min(mx, 50000))
    path = Path(raw).expanduser()
    if not path.is_file():
        return "(trading memory file not created yet.)"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"(could not read trading memory file: {e})"
    tail = text[-mx:] if len(text) > mx else text
    s = tail.strip()
    return s if s else "(empty)"


def _trading_memory_prompt_block(cfg: Dict[str, Any]) -> str:
    """Omit the whole section when unified memory has nothing substantive (saves prompt tokens)."""
    if not _pm_unified_memory(cfg):
        return ""
    tail = _trading_memory_tail_for_pm(cfg)
    if tail in (
        "(memory_log_path not set.)",
        "(trading memory file not created yet.)",
        "(empty)",
    ) or tail.startswith("(could not read trading memory file"):
        return ""
    return (
        "LangGraph trading memory log (recent tail; same file as PM markdown when unified):\n"
        f"{tail}\n\n"
    )


def _recent_analysis_block(cfg: Dict[str, Any], tickers: List[str]) -> str:
    """Build a block of the most recent analysis verdict per ticker from the event log.

    Reads single_model_analysis and full_graph_decision events so the PM
    can see what research actually found, not just that jobs were queued.
    """
    try:
        from tradingagents.agents.utils.event_log import _iter_events
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        ticker_set = {t.strip().upper() for t in tickers if t.strip()}
        # latest result per ticker
        latest: Dict[str, Dict[str, Any]] = {}
        for row in _iter_events(cfg, max_lines=5000):
            ts = str(row.get("timestamp") or "")
            if ts < cutoff:
                continue
            et = str(row.get("event_type") or "")
            if et not in ("single_model_analysis", "full_graph_decision"):
                continue
            tk = str(row.get("ticker") or "").strip().upper()
            if tk not in ticker_set:
                continue
            if tk not in latest or ts > latest[tk].get("timestamp", ""):
                latest[tk] = row
        if not latest:
            return ""
        lines = ["Latest research results (from completed jobs):"]
        for tk in sorted(latest):
            row = latest[tk]
            kd = row.get("key_data") or {}
            excerpt = (kd.get("excerpt") or kd.get("decision") or "")[:300].replace("\n", " ").strip()
            jt = kd.get("job_type") or row.get("event_type", "")
            ts = str(row.get("timestamp") or "")[:10]
            lines.append(f"  {tk} [{jt} {ts}]: {excerpt}")
        return "\n".join(lines) + "\n\n"
    except Exception as e:
        logger.debug("_recent_analysis_block failed: %s", e)
        return ""


def _pm_model(cfg: Dict[str, Any]) -> str:
    raw = cfg.get("portfolio_advisor_pm_model")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return (cfg.get("portfolio_advisor_reasoning_model") or "anthropic/claude-sonnet-4-6").strip()


def _pm_provider(cfg: Dict[str, Any], model: str) -> str:
    if "/" in model:
        return "openrouter"
    return (cfg.get("llm_provider") or "openrouter").lower()


def _provider_kwargs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    prov = (cfg.get("llm_provider") or "openai").lower()
    if prov == "google" and cfg.get("google_thinking_level"):
        kwargs["thinking_level"] = cfg["google_thinking_level"]
    if prov == "openai" and cfg.get("openai_reasoning_effort"):
        kwargs["reasoning_effort"] = cfg["openai_reasoning_effort"]
    if prov == "anthropic" and cfg.get("anthropic_effort"):
        kwargs["effort"] = cfg["anthropic_effort"]
    return kwargs


def _pm_json_for_prompt(cfg: Dict[str, Any], obj: Any) -> str:
    if bool(cfg.get("portfolio_advisor_pm_compact_prompt_json", True)):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(obj, indent=2, ensure_ascii=False)


def load_recent_pm_cycles(cfg: Dict[str, Any], *, limit: int = 30) -> List[Dict[str, Any]]:
    """Newest-first parsed rows from the PM JSONL log."""
    path = pm_log_path(cfg)
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines()[-8000:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out.reverse()
    if limit > 0:
        out = out[:limit]
    return out


def _append_pm_jsonl(cfg: Dict[str, Any], row: Dict[str, Any]) -> None:
    path = pm_log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def _append_pm_memory_md(
    cfg: Dict[str, Any],
    *,
    trigger: str,
    result: AdvisorPMCycleResult,
    actions_taken: Optional[Dict[str, Any]] = None,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"{_PM_ADVISOR_SENTINEL}\n",
        f"\n## PM cycle — {ts} — trigger `{trigger}`\n",
        "### Executive summary\n",
        (result.executive_summary or "").strip() + "\n",
        "### Stances\n",
    ]
    for s in result.stances:
        lines.append(f"- **{s.ticker}** — _{s.stance}_ — {s.rationale}\n")
    if result.forward_tasks:
        lines.append("\n### Forward tasks\n")
        for t in result.forward_tasks:
            lines.append(f"- {t}\n")
    if (result.memory_note or "").strip():
        lines.extend(["\n### Memory note (for next cycle)\n", result.memory_note.strip() + "\n"])
    if actions_taken and actions_taken.get("apply_enabled", True):
        lines.append("\n### Actions taken (automation)\n")
        if actions_taken.get("replan_outcome") is not None:
            lines.append(f"- Replan: `{actions_taken.get('replan_outcome')}`\n")
        if actions_taken.get("replan_error"):
            lines.append(f"- Replan error: {actions_taken.get('replan_error')}\n")
        ja = int(actions_taken.get("jobs_appended") or 0)
        if ja:
            lines.append(f"- Extra jobs appended: {ja}\n")
        if actions_taken.get("jobs_skipped"):
            lines.append(f"- Skipped tickers (not in book): {', '.join(actions_taken['jobs_skipped'])}\n")
    block = "".join(lines)
    if _pm_unified_memory(cfg) and isinstance(cfg.get("memory_log_path"), str) and str(cfg["memory_log_path"]).strip():
        block = block + TradingMemoryLog._SEPARATOR
    with _pm_memory_lock:
        path = pm_memory_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)


def _prior_pm_context(cfg: Dict[str, Any]) -> str:
    n = _pm_int(cfg, "portfolio_advisor_pm_prior_cycles", 2, 0, 8)
    if n <= 0:
        return ""
    prev = load_recent_pm_cycles(cfg, limit=n)
    if not prev:
        return ""
    ex_cap = _pm_int(cfg, "portfolio_advisor_pm_prior_executive_chars", 450, 80, 4000)
    mem_cap = _pm_int(cfg, "portfolio_advisor_pm_prior_memory_note_chars", 700, 0, 8000)
    total_cap = _pm_int(cfg, "portfolio_advisor_pm_prior_context_total_chars", 2600, 200, 20000)
    chunks = []
    for row in reversed(prev):
        r = row.get("result") or {}
        if not isinstance(r, dict):
            continue
        mem = str(r.get("memory_note") or "").strip()
        if mem_cap > 0 and len(mem) > mem_cap:
            mem = mem[:mem_cap] + "…"
        ex = str(r.get("executive_summary") or "").strip()[:ex_cap]
        chunks.append(f"Previous summary:\n{ex}\nPrevious memory note:\n{mem or '(none)'}\n")
    joined = "\n---\n".join(chunks)
    return joined[:total_cap]


def _content_from_llm_message(msg: Any) -> str:
    content = getattr(msg, "content", str(msg))
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        content = "\n".join(parts) if parts else str(content)
    return str(content).strip()


def _coerce_pm_result_from_text(text: str) -> AdvisorPMCycleResult:
    raw = text.strip()
    try:
        return AdvisorPMCycleResult.model_validate_json(raw)
    except Exception:
        return AdvisorPMCycleResult(
            executive_summary=raw[:8000] if raw else "(empty LLM response)",
            stances=[],
            forward_tasks=[],
            memory_note="",
            request_replan=False,
            replan_rationale="",
            append_jobs=[],
        )


# ---------------------------------------------------------------------------
# Pending approval — PM proposes actions, human confirms via ntfy YES/NO
# ---------------------------------------------------------------------------

def _pending_approval_path(cfg: Dict[str, Any]) -> Path:
    return state.advisor_dir(cfg) / "pending_approval.json"


def save_pending_approval(cfg: Dict[str, Any], result: AdvisorPMCycleResult) -> None:
    """Save proposed PM actions to disk, waiting for human YES/NO."""
    path = _pending_approval_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_replan": result.request_replan,
        "replan_rationale": result.replan_rationale or "",
        "append_jobs": [j.model_dump() for j in (result.append_jobs or [])],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_pending_approval(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    path = _pending_approval_path(cfg)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def discard_pending_approval(cfg: Dict[str, Any]) -> None:
    path = _pending_approval_path(cfg)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def format_approval_prompt(result: AdvisorPMCycleResult) -> str:
    """Build a short phone-readable summary of what the PM wants to do."""
    lines: List[str] = []
    if result.request_replan:
        reason = (result.replan_rationale or "priorities shifted").strip()[:120]
        lines.append(f"Replan full job queue: {reason}")
    for j in (result.append_jobs or [])[:5]:
        tier = "deep" if j.execution_tier == "full_graph" else "quick"
        lines.append(f"Queue {j.ticker} {j.job_type} ({tier}): {(j.rationale or '').strip()[:80]}")
    if not lines:
        return ""
    return "Proposed actions:\n" + "\n".join(f"  {l}" for l in lines) + "\n\nReply YES to approve or NO to skip."


# ---------------------------------------------------------------------------
# Last-action log — lets the user CANCEL the most recent PM-queued jobs
# ---------------------------------------------------------------------------

def _last_action_path(cfg: Dict[str, Any]) -> Path:
    return state.advisor_dir(cfg) / "last_action.json"


def save_last_action(
    cfg: Dict[str, Any],
    job_ids: List[str],
    had_replan: bool = False,
    description: str = "",
) -> None:
    p = _last_action_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_ids": job_ids,
                "had_replan": had_replan,
                "description": description,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def cancel_last_action(cfg: Dict[str, Any]) -> str:
    """Cancel jobs queued by the last PM action. Returns a status string."""
    p = _last_action_path(cfg)
    if not p.is_file():
        return "No recent action to cancel."
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Could not read last action."
    job_ids = set(data.get("job_ids") or [])
    if not job_ids:
        return "No jobs recorded in last action."
    st = state.load_state(cfg)
    cancelled: List[str] = []
    for j in st.get("jobs") or []:
        if j.get("id") in job_ids and j.get("status") == "pending":
            j["status"] = "cancelled"
            j["cancel_reason"] = "Cancelled by user via ntfy"
            cancelled.append(j.get("ticker", "?"))
    state.save_state(cfg, st)
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
    if cancelled:
        note = " (replan cannot be undone)" if data.get("had_replan") else ""
        return f"Cancelled: {', '.join(cancelled)}{note}"
    return "Jobs already ran or were not found in queue."


def execute_pending_approval(cfg: Dict[str, Any]) -> str:
    """Execute whatever is in pending_approval.json. Returns a status string."""
    pending = load_pending_approval(cfg)
    if not pending:
        return "No pending actions found."
    discard_pending_approval(cfg)

    parts: List[str] = []

    if pending.get("request_replan"):
        try:
            from tradingagents.portfolio_advisor.service import run_replan
            run_replan(cfg, ignore_weekday=True)
            parts.append("Replan queued.")
        except Exception as e:
            parts.append(f"Replan failed: {e}")

    jobs = pending.get("append_jobs") or []
    if jobs:
        try:
            _payload, _pt, tickers, _rows = etoro_scan.fetch_portfolio_rows()
            live = etoro_scan.current_ticker_set(tickers)
            st = state.load_state(cfg)
            now = datetime.now(timezone.utc)
            new_rows: List[Dict[str, Any]] = []
            skipped: List[str] = []
            for i, job in enumerate(jobs[:5]):
                tid = str(job.get("ticker") or "").strip().upper()
                if not tid or tid not in live:
                    skipped.append(tid or "?")
                    continue
                when = now + timedelta(minutes=1)
                new_rows.append({
                    "id": uuid.uuid4().hex[:20],
                    "ticker": tid,
                    "scheduled_at": when.isoformat(),
                    "kind": "deep_research",
                    "reason": str(job.get("rationale") or "Human-approved PM job")[:500],
                    "status": "pending",
                    "created_at": now.isoformat(),
                    "execution_tier": str(job.get("execution_tier") or "single_model"),
                    "job_type": str(job.get("job_type") or "thesis_check"),
                    "flags": ["PM_APPROVED"],
                })
            if new_rows:
                state.append_jobs(st, new_rows)
                state.save_state(cfg, st)
                tickers_queued = [r["ticker"] for r in new_rows]
                save_last_action(
                    cfg,
                    job_ids=[r["id"] for r in new_rows],
                    had_replan=bool(pending.get("request_replan")),
                    description="Queued: " + ", ".join(tickers_queued),
                )
                _trigger_run_due_async()
                parts.append(f"Queued: {', '.join(tickers_queued)}")
            if skipped:
                parts.append(f"Skipped (not in book): {', '.join(skipped)}")
        except Exception as e:
            parts.append(f"Job append failed: {e}")

    return " | ".join(parts) if parts else "Done (no actions to execute)."


def apply_pm_cycle_followups(cfg: Dict[str, Any], result: AdvisorPMCycleResult) -> Dict[str, Any]:
    """Execute PM-structured replan / extra job requests (Phase 3). Never raises."""
    actions: Dict[str, Any] = {
        "apply_enabled": bool(cfg.get("portfolio_advisor_pm_apply_actions", True)),
    }
    if not actions["apply_enabled"]:
        return actions

    actions["replan_outcome"] = None
    actions["replan_error"] = None
    actions["jobs_appended"] = 0
    actions["jobs_skipped"] = []

    if result.request_replan:
        try:
            from tradingagents.portfolio_advisor.service import run_replan

            token = run_replan(
                cfg,
                ignore_weekday=bool(cfg.get("portfolio_advisor_pm_replan_ignore_weekday", True)),
            )
            actions["replan_outcome"] = token
        except Exception as e:
            logger.exception("PM-requested replan failed")
            actions["replan_error"] = str(e)

    specs = list(result.append_jobs or [])[:5]
    if not specs:
        return actions

    try:
        _payload, _pt, tickers, _rows = etoro_scan.fetch_portfolio_rows()
        live = etoro_scan.current_ticker_set(tickers)
    except Exception as e:
        logger.warning("PM append_jobs: portfolio fetch failed: %s", e)
        actions["jobs_fetch_error"] = str(e)
        return actions

    st = state.load_state(cfg)
    now = datetime.now(timezone.utc)
    new_rows: List[Dict[str, Any]] = []
    for i, job in enumerate(specs):
        tid = str(job.ticker or "").strip().upper()
        if not tid or tid not in live:
            actions["jobs_skipped"].append(tid or "?")
            continue
        when = now + timedelta(minutes=1)
        new_rows.append(
            {
                "id": uuid.uuid4().hex[:20],
                "ticker": tid,
                "scheduled_at": when.isoformat(),
                "kind": "deep_research",
                "reason": (job.rationale or "PM-requested follow-up").strip()[:500],
                "status": "pending",
                "created_at": now.isoformat(),
                "execution_tier": str(job.execution_tier or "single_model").strip(),
                "job_type": str(job.job_type or "thesis_check").strip(),
                "flags": ["PM_APPEND"],
            }
        )
    if new_rows:
        state.append_jobs(st, new_rows)
        state.save_state(cfg, st)
        actions["jobs_appended"] = len(new_rows)
        save_last_action(
            cfg,
            job_ids=[r["id"] for r in new_rows],
            had_replan=bool(actions.get("replan_outcome")),
            description="Queued: " + ", ".join(r["ticker"] for r in new_rows),
        )
        _trigger_run_due_async()
    return actions


def _trigger_run_due_async() -> None:
    """Launch run-due in a background subprocess so queued jobs start immediately."""
    try:
        root = Path(__file__).resolve().parent.parent.parent
        env = os.environ.copy()
        env_file = root / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip())
        env["PYTHONPATH"] = str(root) + ((":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
        subprocess.Popen(
            [sys.executable, "-m", "cli.main", "advisor", "portfolio", "run-due"],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except Exception as e:
        logger.warning("Failed to trigger async run-due: %s", e)


def _notify_action_stances(cfg: Dict[str, Any], result: AdvisorPMCycleResult) -> None:
    """Update action log from PM stances; push alert for new/changed sell/trim. Silent on error."""
    try:
        from tradingagents.portfolio_advisor import messaging
        from tradingagents.portfolio_advisor.action_log import upsert_action, mark_done
        action_stances = [s for s in (result.stances or []) if s.stance in ("sell", "trim")]
        # Auto-close items where stance has improved away from sell/trim
        for s in (result.stances or []):
            if s.stance not in ("sell", "trim"):
                mark_done(cfg, s.ticker)
        if not action_stances:
            return
        lines = []
        for s in action_stances:
            upsert_action(cfg, s.ticker, s.stance, (s.rationale or "").strip(), source="pm_cycle")
            lines.append(f"{s.ticker} {s.stance.upper()}: {(s.rationale or '').strip()[:120]}")
        body = "Action required:\n" + "\n".join(lines)
        messaging.send_advisor_message(cfg, "Action required", body)
    except Exception as e:
        logger.debug("_notify_action_stances failed silently: %s", e)


def run_pm_cycle(
    cfg: Dict[str, Any],
    *,
    trigger: str = "manual",
    extra_context: Optional[str] = None,
    hold_for_approval: bool = False,
) -> AdvisorPMCycleResult:
    """Run one PM council pass: portfolio snapshot + state → structured plan → logs."""
    set_config(cfg)
    trigger_s = (trigger or "manual").strip()[:80] or "manual"

    _ensure_pm_claude_md(cfg)
    pm_claude = _read_pm_claude_md(cfg)
    pm_memory = _read_pm_memory_structured(cfg)

    _payload, portfolio_text, tickers, _rows = etoro_scan.fetch_portfolio_rows()
    if not tickers:
        raise RuntimeError("No tickers in eToro portfolio export.")

    st = state.load_state(cfg)
    summ = st.get("last_bootstrap_summary")
    summ_txt = ""
    summ_max = _pm_int(cfg, "portfolio_advisor_pm_bootstrap_summary_chars", 4000, 0, 20000)
    if isinstance(summ, dict) and summ and summ_max > 0:
        summ_txt = _pm_json_for_prompt(cfg, summ)[:summ_max]

    pend = [j for j in (st.get("jobs") or []) if isinstance(j, dict) and j.get("status") == "pending"]
    job_cap = _pm_int(cfg, "portfolio_advisor_pm_pending_jobs_cap", 12, 0, 100)
    pend_preview = _pm_json_for_prompt(
        cfg,
        [
            {
                "ticker": j.get("ticker"),
                "scheduled_at": j.get("scheduled_at"),
                "tier": j.get("execution_tier"),
                "type": j.get("job_type"),
            }
            for j in pend[:job_cap]
        ],
    )

    model = _pm_model(cfg)
    provider = _pm_provider(cfg, model)
    base = cfg.get("corporate_openrouter_base_url") or cfg.get("backend_url")

    snap_max = _pm_int(cfg, "portfolio_advisor_pm_portfolio_snapshot_chars", 7000, 1000, 50000)
    portfolio_excerpt = (portfolio_text or "")[:snap_max]
    extra_cap = _pm_int(cfg, "portfolio_advisor_pm_extra_context_chars", 3200, 0, 20000)
    extra_excerpt = (extra_context or "").strip()[:extra_cap] if extra_cap > 0 else ""

    prior_txt = _prior_pm_context(cfg)
    prior_block = f"Prior PM context (most recent cycles):\n{prior_txt}\n\n" if prior_txt else ""
    tm_block = _trading_memory_prompt_block(cfg)
    claude_block = f"{pm_claude}\n\n" if pm_claude else ""
    memory_block = f"Your working memory (PM_MEMORY.md — recent notes to self):\n{pm_memory}\n\n" if pm_memory else ""

    prompt = f"""{claude_block}You are the portfolio manager for a research stack. Advisory only: no trade orders, no claims that trades executed.

Authority: the human controls the real portfolio and every execution decision. LangGraph and lighter single-model passes are research tools — treat their outputs as inputs, not as orders or fills.

Execution tiers (for append_jobs only): "full_graph" runs the full multi-agent pipeline on one ticker; "single_model" is a faster desk-style pass (thesis_check, weekly_summary, post_earnings, routine_monitoring).

Trigger for this cycle: {trigger_s}

{memory_block}Portfolio snapshot (truncated):
{portfolio_excerpt}

Live tickers (normalized): {", ".join(sorted(etoro_scan.current_ticker_set(tickers)))}

Pending advisor jobs preview (JSON):
{pend_preview}

Last bootstrap summary (JSON, may be empty):
{summ_txt or "(none)"}

{prior_block}{tm_block}Extra notes from caller (may be empty):
{extra_excerpt or "(none)"}

Structured output fields (use defaults when unsure):
- request_replan: set true only when the pending job queue should be fully rebuilt via the planner LLM
  (cancels current pending jobs). Set replan_rationale when true.
- append_jobs: up to five extra pending jobs to queue without relying on the planner (use live tickers only).
  Each entry: ticker, execution_tier single_model or full_graph, job_type thesis_check|weekly_summary|post_earnings|routine_monitoring, rationale.
  If you set request_replan true, you may still append_jobs; they are added after the replan finishes.
- push_note: one short observation worth pushing to the human right now — deadline approaching, unexpected finding,
  stance change, catalyst within 48h. Max 280 chars. Leave empty if nothing urgent or new. This goes straight
  to the human's phone, so only fill it when you genuinely have something they need to know unprompted.

Deliver structured output only. Stances must use tickers you see above. forward_tasks should be concrete
(research X, schedule replan, verify Y thesis, respond to risk flag, etc.). memory_note is what you want your next self to read first.
"""
    client = create_llm_client(
        provider=provider,
        model=model,
        base_url=base,
        **_provider_kwargs(cfg),
    )
    llm = client.get_llm()
    structured = bind_structured(llm, AdvisorPMCycleResult, "AdvisorPMCycle")
    if structured is not None:
        try:
            out = structured.invoke([HumanMessage(content=prompt)])
            if isinstance(out, AdvisorPMCycleResult):
                result = out
            else:
                result = _coerce_pm_result_from_text(_content_from_llm_message(out))
        except Exception as e:
            logger.warning("PM structured cycle failed: %s", e)
            raw = llm.invoke([HumanMessage(content=prompt)])
            result = _coerce_pm_result_from_text(_content_from_llm_message(raw))
    else:
        raw = llm.invoke([HumanMessage(content=prompt)])
        result = _coerce_pm_result_from_text(_content_from_llm_message(raw))

    has_proposed_actions = bool(result.request_replan or result.append_jobs)
    if hold_for_approval and has_proposed_actions:
        save_pending_approval(cfg, result)
        actions_taken = {"apply_enabled": False, "held_for_approval": True}
    else:
        actions_taken = apply_pm_cycle_followups(cfg, result)

    # Proactive alert for action stances on automated cycles (ntfy questions already surface stances in the reply)
    if trigger_s not in ("ntfy_question",):
        _notify_action_stances(cfg, result)

    # Push note — PM-initiated observation, any trigger
    note = (result.push_note or "").strip()
    if note:
        try:
            from tradingagents.portfolio_advisor import messaging
            messaging.send_advisor_message(cfg, "PM", note[:280])
        except Exception as e:
            logger.debug("push_note send failed: %s", e)

    ts = datetime.now(timezone.utc).isoformat()
    row = {
        "timestamp": ts,
        "trigger": trigger_s,
        "model": model,
        "result": result.model_dump(),
        "actions_taken": actions_taken,
    }
    _append_pm_jsonl(cfg, row)
    _append_pm_memory_md(cfg, trigger=trigger_s, result=result, actions_taken=actions_taken)
    _write_pm_memory_update(cfg, result.memory_note, trigger_s)

    st2 = state.load_state(cfg)
    st2["last_pm_cycle_iso"] = ts
    ex = (result.executive_summary or "").strip()
    st2["last_pm_executive_prefix"] = ex[:500] + ("…" if len(ex) > 500 else "")
    state.save_state(cfg, st2)

    excerpt = ex[:900] if ex else ""
    append_event(
        cfg,
        {
            "ticker": "*",
            "event_type": "advisor_pm_cycle",
            "key_data": {
                "trigger": trigger_s,
                "model": model,
                "stance_tickers": [s.ticker for s in result.stances[:24]],
                "forward_tasks_n": len(result.forward_tasks),
                "excerpt": excerpt,
                "request_replan": bool(result.request_replan),
                "replan_outcome": actions_taken.get("replan_outcome"),
                "replan_error": actions_taken.get("replan_error"),
                "jobs_appended": int(actions_taken.get("jobs_appended") or 0),
            },
            "outcome": None,
        },
    )
    return result


def run_pm_after_full_graph_if_enabled(
    cfg: Dict[str, Any],
    *,
    ticker: str,
    trade_date: str,
    final_state: Dict[str, Any],
) -> None:
    """Run advisor PM immediately after a full LangGraph deep run (best-effort; never raises)."""
    if not bool(cfg.get("portfolio_advisor_pm_enabled", True)):
        return
    if not bool(cfg.get("portfolio_advisor_pm_after_each_langgraph", True)):
        return
    sym = str(ticker or "").strip().upper()
    td = str(trade_date or "").strip()
    dec = str((final_state or {}).get("final_trade_decision") or "").strip()
    extra = (
        f"A full-graph (LangGraph) run just finished for {sym} (trade_date={td}).\n"
        "The human owns the portfolio; use this decision as one input and set portfolio-level next steps.\n\n"
        f"Final decision text (truncated):\n{dec[:2800]}"
    )
    try:
        run_pm_cycle(cfg, trigger="after_langgraph", extra_context=extra)
    except Exception:
        logger.exception("Advisor PM after LangGraph failed for %s", sym)


def _outcome_lines_for_removed(cfg: Dict[str, Any], removed: List[str]) -> List[str]:
    """Return short outcome summary lines for recently closed tickers (best-effort)."""
    from tradingagents.agents.utils import event_log as el

    lines: List[str] = []
    try:
        events = list(el._iter_events(cfg, max_lines=8000))
    except Exception:
        return lines
    seen: set = set()
    for row in reversed(events):
        et = str(row.get("event_type") or "")
        if et not in ("outcome_recorded", "partial_close_outcome"):
            continue
        sym = str(row.get("ticker") or "").strip().upper()
        if sym not in removed or sym in seen:
            continue
        seen.add(sym)
        kd = row.get("key_data") if isinstance(row.get("key_data"), dict) else {}
        align = str(row.get("outcome") or kd.get("outcome_alignment") or "unknown")
        pnl = kd.get("pnl_pct")
        decision = kd.get("decision_was") or ""
        pnl_str = f"{float(pnl):+.1f}%" if pnl is not None else "n/a"
        lines.append(f"- {sym}: decision={decision or 'unknown'}, alignment={align}, pnl_proxy={pnl_str}")
        if len(seen) >= 8:
            break
    return lines


def optional_pm_cycle_on_portfolio_change(
    cfg: Dict[str, Any],
    *,
    trigger: str,
    old_portfolio_text_hash: Optional[str],
    new_portfolio_text_hash: str,
    tickers_added: Optional[List[str]] = None,
    tickers_removed: Optional[List[str]] = None,
) -> None:
    """Run a PM cycle when the live book or snapshot fingerprint changed (Phase 4). Best-effort."""
    if not bool(cfg.get("portfolio_advisor_pm_enabled", True)):
        return
    if not bool(cfg.get("portfolio_advisor_pm_cycle_on_portfolio_change", True)):
        return
    ta = [str(x).strip().upper() for x in (tickers_added or []) if str(x).strip()]
    tr = [str(x).strip().upper() for x in (tickers_removed or []) if str(x).strip()]
    h_changed = bool(
        old_portfolio_text_hash
        and new_portfolio_text_hash
        and str(old_portfolio_text_hash) != str(new_portfolio_text_hash)
    )
    if not h_changed and not ta and not tr:
        return
    lines: List[str] = []
    if ta or tr:
        lines.append(
            f"Tickers added: {', '.join(ta) if ta else '(none)'}; "
            f"removed: {', '.join(tr) if tr else '(none)'}"
        )
    if h_changed:
        lines.append(
            "Portfolio snapshot fingerprint changed: "
            f"{str(old_portfolio_text_hash)[:16]}… → {str(new_portfolio_text_hash)[:16]}…"
        )

    # Outcome feedback: look up alignment for each removed ticker and surface it to the PM.
    if tr:
        outcome_lines = _outcome_lines_for_removed(cfg, tr)
        if outcome_lines:
            lines.append("\nOutcome alignments for closed positions (yfinance proxy, not eToro fills):")
            lines.extend(outcome_lines)

    extra = "\n".join(lines) if lines else "Portfolio change signal (no ticker list diff captured)."
    try:
        run_pm_cycle(cfg, trigger=trigger, extra_context=extra)
    except Exception:
        logger.exception("PM cycle on portfolio change failed (trigger=%s)", trigger)
