# tradingagents/clerk/state.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set


@dataclass
class ClerkStateStore:
    """Per-ticker fingerprints of headlines we've already processed."""

    root: Path

    def _path(self, ticker: str) -> Path:
        safe = "".join(c for c in ticker.upper() if c.isalnum() or c in "._-")
        return self.root / f"{safe}_news_state.json"

    def load_seen(self, ticker: str) -> Set[str]:
        p = self._path(ticker)
        if not p.exists():
            return set()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            fps = data.get("seen_fingerprints") or []
            if isinstance(fps, list):
                return {str(x) for x in fps}
        except (json.JSONDecodeError, OSError):
            pass
        return set()

    def save_seen(self, ticker: str, fingerprints: List[str], max_keep: int = 200) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        uniq: List[str] = []
        seen_local: Set[str] = set()
        for fp in fingerprints:
            if fp not in seen_local:
                seen_local.add(fp)
                uniq.append(fp)
        tail = uniq[-max_keep:]
        payload: Dict[str, Any] = {"seen_fingerprints": tail}
        p = self._path(ticker)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
