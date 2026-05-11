# tradingagents/advisor/positions.py

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class PositionSpec:
    """One open position the advisor should monitor."""

    ticker: str
    entry_price: float
    # Optional ISO date YYYY-MM-DD for next known earnings (or leave unset and use yfinance).
    next_earnings_date: Optional[str] = None
    # When True (default), try yfinance for earnings if next_earnings_date is missing.
    fetch_earnings_from_yfinance: bool = True
    # Human-readable thesis-break checks (advisor surfaces reminders; automation is price/rules).
    thesis_break_metrics: List[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PositionSpec:
        ticker = str(raw.get("ticker", "")).strip().upper()
        if not ticker:
            raise ValueError("Each position requires a non-empty ticker")
        entry = raw.get("entry_price")
        if entry is None:
            raise ValueError(f"{ticker}: entry_price is required")
        entry_f = float(entry)
        if entry_f <= 0:
            raise ValueError(f"{ticker}: entry_price must be positive")

        ned = raw.get("next_earnings_date")
        if ned is not None and str(ned).strip() == "":
            ned = None

        fetch_cal = raw.get("fetch_earnings_from_yfinance", True)
        if isinstance(fetch_cal, str):
            fetch_cal = fetch_cal.strip().lower() in ("1", "true", "yes", "on")

        metrics = raw.get("thesis_break_metrics") or []
        if not isinstance(metrics, list):
            raise ValueError(f"{ticker}: thesis_break_metrics must be a list of strings")
        metrics = [str(m) for m in metrics]

        notes = str(raw.get("notes", "") or "")

        return cls(
            ticker=ticker,
            entry_price=entry_f,
            next_earnings_date=str(ned) if ned else None,
            fetch_earnings_from_yfinance=bool(fetch_cal),
            thesis_break_metrics=metrics,
            notes=notes,
        )


def load_positions_file(path: Path) -> list[PositionSpec]:
    """Load a JSON file with top-level key ``positions`` (array of objects)."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict) or "positions" not in data:
        raise ValueError("Positions file must be a JSON object with a 'positions' array")
    rows = data["positions"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("'positions' must be a non-empty array")
    return [PositionSpec.from_dict(r) for r in rows]
