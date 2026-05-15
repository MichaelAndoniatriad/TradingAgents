"""Evidence retrieval for the advisor PM council.

This module is deliberately deterministic: no LLM calls, no summarization model.
It builds a compact case file from the records the system already wrote.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tradingagents.agents.utils.event_log import _iter_events
from tradingagents.portfolio_advisor import state

_ISO_DATE_RE = re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)")


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    ticker: str
    kind: str
    timestamp: str = ""
    summary: str = ""
    path: str = ""
    decision: str = ""
    staleness_days: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _staleness_days(raw_ts: Any) -> Optional[int]:
    dt = _parse_ts(raw_ts)
    if dt is None:
        return None
    return max(0, int((_utc_now() - dt).total_seconds() // 86400))


def _extract_dates(*parts: str) -> List[str]:
    out = set()
    for part in parts:
        out.update(_ISO_DATE_RE.findall(str(part or "")))
    return sorted(out)


def _summarize_text(text: str, limit: int = 280) -> str:
    return " ".join((text or "").split())[:limit]


def _event_ref(event_type: str, ticker: str, timestamp: str) -> str:
    return f"event:{event_type}:{ticker}:{timestamp[:10] or 'unknown'}"


def _decision_hint(event_type: str, key_data: Dict[str, Any], outcome: Any) -> str:
    if event_type == "outcome_recorded":
        return str(outcome or key_data.get("outcome_alignment") or "")
    if event_type == "full_graph_decision":
        bits = [str(key_data.get("rating") or "").strip(), str(key_data.get("confidence") or "").strip()]
        return " / ".join(b for b in bits if b)
    text = str(key_data.get("excerpt") or key_data.get("decision") or key_data.get("summary") or "")
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:120]


def event_evidence(cfg: Dict[str, Any], tickers: Iterable[str]) -> List[EvidenceRecord]:
    ticker_set = {str(t).strip().upper() for t in tickers if str(t).strip()}
    latest: Dict[str, Dict[str, Any]] = {}
    wanted = {"single_model_analysis", "full_graph_decision", "post_earnings_verdict", "outcome_recorded"}
    for row in _iter_events(cfg, max_lines=12000):
        et = str(row.get("event_type") or "")
        if et not in wanted:
            continue
        tk = str(row.get("ticker") or "").strip().upper()
        if tk not in ticker_set:
            continue
        ts = str(row.get("timestamp") or "")
        key = f"{tk}:{et}"
        if key not in latest or ts > str(latest[key].get("timestamp") or ""):
            latest[key] = row

    records: List[EvidenceRecord] = []
    for row in latest.values():
        tk = str(row.get("ticker") or "").strip().upper()
        et = str(row.get("event_type") or "")
        ts = str(row.get("timestamp") or "")
        kd = row.get("key_data") or {}
        excerpt = str(
            kd.get("summary")
            or kd.get("thesis")
            or kd.get("excerpt")
            or kd.get("decision")
            or ""
        )
        records.append(
            EvidenceRecord(
                id=_event_ref(et, tk, ts),
                ticker=tk,
                kind=et,
                timestamp=ts,
                summary=_summarize_text(excerpt or et),
                decision=_decision_hint(et, kd, row.get("outcome")),
                staleness_days=_staleness_days(ts),
            )
        )
    return records


def pending_job_evidence(pending_jobs: Iterable[Dict[str, Any]], tickers: Iterable[str]) -> List[EvidenceRecord]:
    ticker_set = {str(t).strip().upper() for t in tickers if str(t).strip()}
    records: List[EvidenceRecord] = []
    for j in pending_jobs:
        tk = str(j.get("ticker") or "").strip().upper()
        if tk and tk not in ticker_set:
            continue
        jid = str(j.get("id") or "").strip() or "unknown"
        ts = str(j.get("scheduled_at") or "")
        summary = (
            f"Pending {j.get('execution_tier') or 'single_model'} "
            f"{j.get('job_type') or 'routine_monitoring'} scheduled {ts or '?'}"
        )
        question = str(j.get("evidence_question") or j.get("reason") or "").strip()
        if question:
            summary += f"; question: {question[:180]}"
        records.append(
            EvidenceRecord(
                id=f"job:{jid}",
                ticker=tk,
                kind="pending_job",
                timestamp=ts,
                summary=summary,
                staleness_days=_staleness_days(ts),
            )
        )
    return records


def portfolio_evidence(tickers: Iterable[str]) -> List[EvidenceRecord]:
    records = []
    for tk in sorted({str(t).strip().upper() for t in tickers if str(t).strip()}):
        records.append(
            EvidenceRecord(
                id=f"context:portfolio_snapshot:{tk}",
                ticker=tk,
                kind="portfolio_snapshot",
                summary="Ticker is present in the live portfolio snapshot supplied to this PM cycle.",
            )
        )
    return records


def deep_report_evidence(cfg: Dict[str, Any], tickers: Iterable[str]) -> List[EvidenceRecord]:
    results_dir = Path(str(cfg.get("results_dir") or "")).expanduser()
    if not str(results_dir) or not results_dir.is_dir():
        return []
    records: List[EvidenceRecord] = []
    for tk in sorted({str(t).strip().upper() for t in tickers if str(t).strip()}):
        base = results_dir / "clerk_deep" / tk
        if not base.is_dir():
            continue
        files = [p for p in base.glob("*_clerk_triggered.md") if p.is_file()]
        if not files:
            continue
        latest = max(files, key=lambda p: p.stat().st_mtime)
        try:
            text = latest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        ts = ""
        for line in text.splitlines()[:8]:
            if line.startswith("Date:"):
                ts = line.split(":", 1)[1].strip()
                break
        if not ts:
            ts = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc).isoformat()
        decision = ""
        marker = "## Final decision"
        if marker in text:
            decision = _summarize_text(text.split(marker, 1)[1], 220)
        records.append(
            EvidenceRecord(
                id=f"file:clerk_deep:{tk}:{latest.name}",
                ticker=tk,
                kind="deep_report_file",
                timestamp=ts,
                summary=decision or f"Latest deep research report on disk: {latest.name}",
                path=str(latest),
                decision=decision,
                staleness_days=_staleness_days(ts),
            )
        )
    return records


def collect_pm_evidence(
    cfg: Dict[str, Any],
    tickers: Iterable[str],
    *,
    pending_jobs: Optional[List[Dict[str, Any]]] = None,
    max_records: int = 80,
) -> Dict[str, Any]:
    """Return PM-ready evidence, per-ticker refs, known dates, and stale tickers."""
    ticker_list = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    jobs = pending_jobs if pending_jobs is not None else state.list_pending_jobs(state.load_state(cfg))
    records: List[EvidenceRecord] = []
    records.extend(portfolio_evidence(ticker_list))
    records.extend(pending_job_evidence(jobs, ticker_list))
    records.extend(event_evidence(cfg, ticker_list))
    records.extend(deep_report_evidence(cfg, ticker_list))

    records.sort(key=lambda r: (r.ticker, r.kind, r.timestamp), reverse=False)
    evidence = [r.to_dict() for r in records[:max_records]]

    by_ticker: Dict[str, List[str]] = {}
    latest_full_graph_decisions: Dict[str, Dict[str, Any]] = {}
    known_dates = {_utc_now().strftime("%Y-%m-%d")}
    for r in records:
        if r.ticker:
            by_ticker.setdefault(r.ticker, []).append(r.id)
        known_dates.update(_extract_dates(r.timestamp, r.summary, r.decision))
        if r.kind == "full_graph_decision":
            prev = latest_full_graph_decisions.get(r.ticker)
            if prev is None or str(r.timestamp or "") > str(prev.get("timestamp") or ""):
                latest_full_graph_decisions[r.ticker] = r.to_dict()

    stale_after = int(cfg.get("portfolio_advisor_pm_evidence_stale_days") or 30)
    stale_tickers: Dict[str, Dict[str, Any]] = {}
    for tk in ticker_list:
        research = [
            r
            for r in records
            if r.ticker == tk
            and r.kind in {"single_model_analysis", "full_graph_decision", "post_earnings_verdict", "deep_report_file"}
        ]
        if not research:
            stale_tickers[tk] = {"reason": "missing_research", "staleness_days": None}
            continue
        latest = max(research, key=lambda r: r.timestamp or "")
        if latest.staleness_days is not None and latest.staleness_days > stale_after:
            stale_tickers[tk] = {
                "reason": "stale_research",
                "staleness_days": latest.staleness_days,
                "latest_ref": latest.id,
            }

    return {
        "evidence": evidence,
        "by_ticker": by_ticker,
        "known_dates": sorted(known_dates),
        "stale_after_days": stale_after,
        "stale_tickers": stale_tickers,
        "latest_full_graph_decisions": latest_full_graph_decisions,
    }
