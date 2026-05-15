"""Structured ticker-decision extraction from graph PM markdown."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tradingagents.agents.utils.rating import parse_rating

_SECTION_RE = re.compile(r"\*\*(?P<label>[^*]+)\*\*:\s*(?P<body>.*?)(?=\n\n\*\*|\Z)", re.S)


def _section_map(markdown: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for match in _SECTION_RE.finditer(markdown or ""):
        key = " ".join(match.group("label").strip().lower().split())
        out[key] = " ".join(match.group("body").strip().split())
    return out


def _extract_thesis_break_metrics(*texts: str) -> List[str]:
    metrics: List[str] = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
            s = sentence.strip()
            if not s:
                continue
            low = s.lower()
            if any(term in low for term in ("thesis-break", "thesis break", "break metric", "would change")):
                metrics.append(s[:220])
            if len(metrics) >= 4:
                return metrics
    return metrics


def extract_ticker_decision(
    *,
    ticker: str,
    trade_date: str,
    final_trade_decision: str,
    decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a stable structured ticker decision from PM markdown.

    The graph PM already produces structured output, but downstream storage
    persists the rendered markdown. This extractor keeps that existing contract
    while giving the advisor council a normalized event payload.
    """
    sym = str(ticker or "").strip().upper()
    text = str(final_trade_decision or "").strip()
    sections = _section_map(text)
    rating = parse_rating(text)
    confidence = sections.get("confidence", "")
    summary = sections.get("executive summary", "")
    thesis = sections.get("investment thesis", "")
    framing = sections.get("how to think about this", "")
    return {
        "decision_id": decision_id or uuid.uuid4().hex[:20],
        "ticker": sym,
        "trade_date": str(trade_date or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rating": rating,
        "confidence": confidence,
        "summary": summary,
        "thesis": thesis,
        "investor_framing": framing,
        "thesis_break_metrics": _extract_thesis_break_metrics(summary, thesis, framing),
        "next_review": None,
        "evidence_refs": [],
        "excerpt": text[:900],
    }
