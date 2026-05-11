# tradingagents/clerk/watchlist.py

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class ClerkTriggers:
    """What qualifies as a good reason to run the full multi-agent graph.

    No percentage-based triggers — only information calendar / content signals.
    """

    deep_research_on_new_headlines: bool = True
    # If set, earnings within N calendar days (from yfinance calendar or per-ticker override).
    deep_research_earnings_within_days: Optional[int] = None
    # If any of these strings appears in a *new* headline (case-insensitive), trigger deep research.
    deep_research_keyword_hits: List[str] = field(default_factory=list)
    # Optional cheap LLM gate (off by default): model decides if the delta is material.
    use_llm_materiality_gate: bool = False


@dataclass
class ClerkWatchlist:
    tickers: List[str]
    triggers: ClerkTriggers
    # Subset of analyst keys when deep research runs: market, social, news, fundamentals
    deep_research_analysts: List[str] = field(
        default_factory=lambda: ["news", "fundamentals"]
    )
    output_language: str = "English"

    @classmethod
    def from_path(cls, path: Path) -> ClerkWatchlist:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Watchlist JSON must be an object")
        raw_tickers = data.get("tickers") or []
        if not isinstance(raw_tickers, list) or not raw_tickers:
            raise ValueError("'tickers' must be a non-empty array")
        tickers = [str(t).strip().upper() for t in raw_tickers if str(t).strip()]

        t_raw = data.get("triggers") or {}
        triggers = ClerkTriggers(
            deep_research_on_new_headlines=bool(
                t_raw.get("deep_research_on_new_headlines", True)
            ),
            deep_research_earnings_within_days=_optional_int(
                t_raw.get("deep_research_earnings_within_days")
            ),
            deep_research_keyword_hits=[
                str(x) for x in (t_raw.get("deep_research_keyword_hits") or []) if str(x).strip()
            ],
            use_llm_materiality_gate=bool(t_raw.get("use_llm_materiality_gate", False)),
        )

        analysts = data.get("deep_research_analysts") or ["news", "fundamentals"]
        if not isinstance(analysts, list):
            raise ValueError("deep_research_analysts must be a list")
        analysts = [str(a).strip().lower() for a in analysts]

        lang = str(data.get("output_language") or "English")

        return cls(
            tickers=tickers,
            triggers=triggers,
            deep_research_analysts=analysts,
            output_language=lang,
        )

    @classmethod
    def default_for_tickers(cls, tickers: List[str]) -> "ClerkWatchlist":
        uniq = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
        if not uniq:
            raise ValueError("tickers must be a non-empty list")
        return cls(
            tickers=uniq,
            triggers=ClerkTriggers(
                deep_research_on_new_headlines=True,
                deep_research_earnings_within_days=5,
                deep_research_keyword_hits=["guidance", "SEC", "investigation"],
                use_llm_materiality_gate=False,
            ),
            deep_research_analysts=["news", "fundamentals"],
            output_language="English",
        )

    def to_json_dict(self) -> dict:
        return {
            "tickers": list(self.tickers),
            "output_language": self.output_language,
            "deep_research_analysts": list(self.deep_research_analysts),
            "triggers": {
                "deep_research_on_new_headlines": self.triggers.deep_research_on_new_headlines,
                "deep_research_earnings_within_days": self.triggers.deep_research_earnings_within_days,
                "deep_research_keyword_hits": list(self.triggers.deep_research_keyword_hits),
                "use_llm_materiality_gate": self.triggers.use_llm_materiality_gate,
            },
            "_meta": {"source": "tradingagents.etoro"},
        }


def _optional_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    return int(val)
