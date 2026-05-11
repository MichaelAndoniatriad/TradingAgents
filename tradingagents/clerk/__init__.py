"""Scheduled clerk: daily digest, weekly deep-research queue, monthly lookout."""

from typing import Any

__all__ = ["run_morning_clerk", "run_weekly_clerk", "run_monthly_lookout"]


def __getattr__(name: str) -> Any:
    if name == "run_morning_clerk":
        from tradingagents.clerk.morning import run_morning_clerk

        return run_morning_clerk
    if name == "run_weekly_clerk":
        from tradingagents.clerk.weekly import run_weekly_clerk

        return run_weekly_clerk
    if name == "run_monthly_lookout":
        from tradingagents.clerk.monthly import run_monthly_lookout

        return run_monthly_lookout
    raise AttributeError(name)
