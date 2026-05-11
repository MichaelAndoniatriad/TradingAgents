"""Scheduled clerk: lightweight daily scans, optional deep research on signal, weekly recap."""

from typing import Any

__all__ = ["run_morning_clerk", "run_weekly_clerk"]


def __getattr__(name: str) -> Any:
    if name == "run_morning_clerk":
        from tradingagents.clerk.morning import run_morning_clerk

        return run_morning_clerk
    if name == "run_weekly_clerk":
        from tradingagents.clerk.weekly import run_weekly_clerk

        return run_weekly_clerk
    raise AttributeError(name)
