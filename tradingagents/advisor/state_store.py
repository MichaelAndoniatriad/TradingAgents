# tradingagents/advisor/state_store.py

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Set


@dataclass
class DedupeStore:
    """Avoid re-sending the same alert every run (per calendar day per trigger)."""

    path: Path
    _sent_on_day: Dict[str, str]  # dedupe_key -> YYYY-MM-DD last sent

    @classmethod
    def load(cls, base_dir: Path) -> DedupeStore:
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / "advisor_dedupe.json"
        data: Dict[str, str] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    inner = raw.get("keys") if isinstance(raw.get("keys"), dict) else raw
                    if isinstance(inner, dict):
                        data = {str(k): str(v) for k, v in inner.items() if not str(k).startswith("_")}
            except (json.JSONDecodeError, OSError):
                data = {}
        return cls(path=path, _sent_on_day=data)

    def should_send(self, dedupe_key: str, today: date) -> bool:
        return self._sent_on_day.get(dedupe_key) != today.isoformat()

    def mark_sent(self, dedupe_key: str, today: date) -> None:
        self._sent_on_day[dedupe_key] = today.isoformat()
        self._persist()

    def mark_many(self, keys: Set[str], today: date) -> None:
        day = today.isoformat()
        for k in keys:
            self._sent_on_day[k] = day
        self._persist()

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_updated": datetime.utcnow().isoformat() + "Z",
            "keys": self._sent_on_day,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
