"""Pydantic models for LLM-produced portfolio advisor schedules."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class AdvisorJobSpec(BaseModel):
    """One scheduled unit of work proposed by the advisor LLM."""

    ticker: str = Field(description="Uppercase equity symbol, e.g. NVDA or 7203.T")
    scheduled_at: str = Field(
        description="ISO-8601 datetime in UTC for when to run deep research, e.g. 2026-05-14T21:00:00+00:00",
    )
    action: Literal["deep_research", "watch_only", "skip"] = Field(
        description="deep_research = queue a full graph run; watch_only = narrative only (no graph); skip = ignore",
    )
    rationale: str = Field(
        default="",
        description="One or two sentences: why this timing and action.",
    )
    execution_tier: Literal["single_model", "full_graph"] = Field(
        default="single_model",
        description="single_model: one reasoning LLM pass; full_graph: TradingAgentsGraph.propagate",
    )
    job_type: Literal[
        "thesis_check",
        "weekly_summary",
        "post_earnings",
        "routine_monitoring",
    ] = Field(
        default="routine_monitoring",
        description=(
            "Type of analysis this job should run. Determines prompt branching in "
            "single_model_analysis._build_prompt."
        ),
    )
    flags: List[str] = Field(
        default_factory=list,
        description="Planner or validator flags e.g. PRE_EARNINGS_TRIM_ACTIVE",
    )


class AdvisorPlanResult(BaseModel):
    """Structured plan returned by the portfolio advisor LLM."""

    executive_summary: str = Field(
        description="Plain-language portfolio memo for the investor (advisory only, no orders).",
    )
    jobs: List[AdvisorJobSpec] = Field(
        description="Up to 15 prioritized jobs; prefer catalysts within 21 days and larger risk names.",
    )
    immediate_actions: List[str] = Field(
        default_factory=list,
        description="Urgent notes for the human right now (e.g. consider exit, trim, or wait).",
    )
