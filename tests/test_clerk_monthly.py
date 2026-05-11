# tests/test_clerk_monthly.py

import json
from pathlib import Path

from tradingagents.clerk.monthly import load_monthly_candidates


def test_load_monthly_candidates(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps({"candidates": ["aa", "bb"], "theme": "test"}),
        encoding="utf-8",
    )
    t, theme = load_monthly_candidates(p)
    assert t == ["AA", "BB"]
    assert theme == "test"
