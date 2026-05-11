"""Pause/resume flag for scheduled clerk runs (local cron / launchd).

When the marker file exists, `scripts/cron-clerk-*.sh` exits without running.
The Streamlit Clerk page toggles this file via Pause / Continue.
"""

from __future__ import annotations

from pathlib import Path


def clerk_scheduled_pause_marker() -> Path:
    d = Path.home() / ".tradingagents" / "automation"
    d.mkdir(parents=True, exist_ok=True)
    return d / "clerk_scheduled_automation_paused"


def is_clerk_scheduled_automation_paused() -> bool:
    return clerk_scheduled_pause_marker().is_file()


def set_clerk_scheduled_automation_paused(paused: bool) -> None:
    p = clerk_scheduled_pause_marker()
    if paused:
        p.touch()
    elif p.exists():
        p.unlink()
