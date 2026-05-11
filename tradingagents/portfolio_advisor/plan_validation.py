"""Validate advisor plan jobs against live prices and exit rules before persist."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.advisor.earnings import next_earnings_from_yfinance
from tradingagents.integrations.etoro.clerk_bridge import _normalize_ticker
from tradingagents.portfolio_advisor import messaging
from tradingagents.portfolio_advisor.models import AdvisorJobSpec, AdvisorPlanResult
from tradingagents.portfolio_advisor.price_util import last_close_yfinance

logger = logging.getLogger(__name__)


def _parse_iso(dt: str) -> datetime:
    s = (dt or "").strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _row_for_ticker(rows: List[Dict[str, Any]], ticker: str) -> Optional[Dict[str, Any]]:
    want = _normalize_ticker(ticker)
    for r in rows:
        sym = _normalize_ticker(str(r.get("symbolFull") or ""))
        if sym == want:
            return r
    return None


def _entry_price(row: Optional[Dict[str, Any]]) -> float:
    if not row:
        return 0.0
    v = row.get("openRate")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _is_long(row: Optional[Dict[str, Any]]) -> bool:
    if not row:
        return True
    ib = row.get("isBuy")
    return ib is not False


def _gain_dd_pct(entry: float, price: float, is_long: bool) -> Tuple[float, float]:
    """Return (gain_pct, drawdown_pct) where drawdown is loss magnitude as positive percent."""
    if entry <= 0 or price <= 0:
        return 0.0, 0.0
    if is_long:
        gain = (price - entry) / entry * 100.0
        dd = max(0.0, (entry - price) / entry * 100.0)
    else:
        gain = (entry - price) / entry * 100.0
        dd = max(0.0, (price - entry) / entry * 100.0)
    return gain, dd


def group_position_rows_by_ticker(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """All eToro lot rows for one normalized ticker (symbolFull), in input order."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows or []:
        sym = _normalize_ticker(str(r.get("symbolFull") or ""))
        if sym:
            out.setdefault(sym, []).append(r)
    return out


def weighted_avg_open_for_lots(rows_for_sym: List[Dict[str, Any]]) -> float:
    """Size weighted average open rate: sum(openRate * units) / sum(units)."""
    num = 0.0
    den = 0.0
    for r in rows_for_sym:
        er = _entry_price(r)
        try:
            u = float(r.get("units") or 0.0)
        except (TypeError, ValueError):
            u = 0.0
        if er > 0 and u > 0:
            num += er * u
            den += u
    if den <= 0:
        return 0.0
    return num / den


def representative_is_long_for_lots(rows_for_sym: List[Dict[str, Any]]) -> bool:
    """Use the first lot with positive units to infer side; default long."""
    for r in rows_for_sym:
        try:
            u = float(r.get("units") or 0.0)
        except (TypeError, ValueError):
            u = 0.0
        if u > 0:
            return _is_long(r)
    return _is_long(rows_for_sym[0]) if rows_for_sym else True


def validate_advisor_plan(
    cfg: Dict[str, Any],
    plan: AdvisorPlanResult,
    rows: List[Dict[str, Any]],
    *,
    thesis_metrics: Optional[Dict[str, List[str]]] = None,
) -> Tuple[AdvisorPlanResult, List[Dict[str, Any]]]:
    """Return validated plan and override detail rows for JSONL."""
    thesis_metrics = thesis_metrics or {}
    if isinstance(thesis_metrics, dict) and thesis_metrics:
        tm: Dict[str, List[str]] = {}
        for k, v in thesis_metrics.items():
            kk = str(k).strip().upper()
            if isinstance(v, list):
                tm[kk] = [str(x) for x in v]
            elif v:
                tm[kk] = [str(v)]
            else:
                tm[kk] = []
        thesis_metrics = tm
    else:
        thesis_metrics = {}

    now = datetime.now(timezone.utc)
    overrides: List[Dict[str, Any]] = []
    new_jobs: List[AdvisorJobSpec] = []
    critical_bodies: List[str] = []

    for spec in plan.jobs:
        if spec.action != "deep_research":
            new_jobs.append(spec)
            continue

        t = spec.ticker.strip().upper()
        row = _row_for_ticker(rows, t)
        entry = _entry_price(row)
        is_long = _is_long(row)
        px = last_close_yfinance(t)
        if px is None or entry <= 0:
            mut = spec.model_copy(deep=True)
            mut.execution_tier = "full_graph"
            urgent = now + timedelta(hours=24)
            try:
                when = _parse_iso(mut.scheduled_at)
                if when > urgent:
                    mut.scheduled_at = _iso_utc(urgent)
            except ValueError:
                mut.scheduled_at = _iso_utc(urgent)
            flags = list(mut.flags or [])
            if "URGENT_VALIDATION_NO_PRICE" not in flags:
                flags.append("URGENT_VALIDATION_NO_PRICE")
            mut.flags = flags
            new_jobs.append(mut)
            overrides.append(
                {
                    "ticker": t,
                    "change": "urgent_full_graph_missing_price_or_entry",
                    "reason": "cannot_validate_without_price_or_entry",
                    "now_scheduled_at": mut.scheduled_at,
                    "was_scheduled_at": spec.scheduled_at,
                }
            )
            continue

        gain, dd = _gain_dd_pct(entry, px, is_long)

        if dd >= 40.0:
            msg = (
                f"Plan validation CRITICAL: {t} drawdown from entry is about {dd:.1f}% "
                f"(entry {entry:.4f}, last about {px:.4f}). No new schedule for this name. Exit per policy."
            )
            critical_bodies.append(msg)
            overrides.append(
                {
                    "ticker": t,
                    "change": "removed_job",
                    "reason": "dd40",
                    "entry": entry,
                    "price": px,
                    "drawdown_pct": dd,
                    "was_scheduled_at": spec.scheduled_at,
                }
            )
            continue

        mut = spec.model_copy(deep=True)

        if dd >= 30.0:
            try:
                when = _parse_iso(mut.scheduled_at)
                cap = now + timedelta(days=7)
                if when > cap:
                    old = mut.scheduled_at
                    mut.scheduled_at = _iso_utc(cap)
                    overrides.append(
                        {
                            "ticker": t,
                            "change": "clamped_schedule",
                            "reason": "dd30_max_7d",
                            "was_scheduled_at": old,
                            "now_scheduled_at": mut.scheduled_at,
                        }
                    )
            except ValueError:
                mut.scheduled_at = _iso_utc(now + timedelta(days=7))
                overrides.append(
                    {
                        "ticker": t,
                        "change": "fixed_bad_date_dd30",
                        "now_scheduled_at": mut.scheduled_at,
                    }
                )

        ed = next_earnings_from_yfinance(t)
        if ed is not None and gain >= 15.0:
            days_to = (ed - date.today()).days
            if 0 <= days_to <= 14:
                flags = list(mut.flags or [])
                if "PRE_EARNINGS_TRIM_ACTIVE" not in flags:
                    flags.append("PRE_EARNINGS_TRIM_ACTIVE")
                    mut.flags = flags
                    overrides.append(
                        {
                            "ticker": t,
                            "change": "flag_pre_earnings_trim",
                            "earnings_date": ed.isoformat(),
                            "gain_pct": gain,
                        }
                    )

        metrics = thesis_metrics.get(t, [])
        if not metrics and mut.execution_tier == "single_model":
            mut.execution_tier = "full_graph"
            overrides.append(
                {
                    "ticker": t,
                    "change": "tier_upgrade_full_graph_no_metrics",
                    "reason": "no_thesis_break_metrics",
                    "execution_tier": "full_graph",
                }
            )

        new_jobs.append(mut)

    for body in critical_bodies:
        try:
            messaging.send_advisor_message(
                cfg,
                "[TradingAgents] Plan validation CRITICAL",
                body,
            )
        except Exception as e:
            logger.warning("plan validation critical message failed: %s", e)

    out_plan = AdvisorPlanResult(
        executive_summary=plan.executive_summary,
        jobs=new_jobs,
        immediate_actions=list(plan.immediate_actions or []),
    )
    return out_plan, overrides
