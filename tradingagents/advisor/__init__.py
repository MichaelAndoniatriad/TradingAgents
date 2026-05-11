"""Live position management advisor: rule-based alerts and optional LLM digest."""

from typing import TYPE_CHECKING, Any

__all__ = ["run_advisor_once", "run_advisor_loop"]

if TYPE_CHECKING:
    from tradingagents.advisor.runner import run_advisor_loop as run_advisor_loop_t
    from tradingagents.advisor.runner import run_advisor_once as run_advisor_once_t


def __getattr__(name: str) -> Any:
    if name == "run_advisor_once":
        from tradingagents.advisor.runner import run_advisor_once

        return run_advisor_once
    if name == "run_advisor_loop":
        from tradingagents.advisor.runner import run_advisor_loop

        return run_advisor_loop
    raise AttributeError(name)
