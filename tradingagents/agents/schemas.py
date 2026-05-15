"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class ConfidenceLevel(str, Enum):
    """How strongly the evidence supports the advisory rating (Portfolio Manager)."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing: start with half the intended allocation, "
            "add the remainder over 2–4 weeks if the thesis confirms, cap new "
            "risk at roughly 5% of portfolio per name, average up not down, and "
            "list 2–3 measurable thesis-break metrics to monitor."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description=(
            "Optional sizing guidance, e.g. '2.5% now, add to 5% over 3 weeks "
            "if thesis confirms' — must respect the desk cap (~5% per new position) "
            "and staged entry (half now, half later)."
        ),
    )


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "Advisory stance for the human reader only (this software does not "
            "place trades). Exactly one of Buy / Overweight / Hold / Underweight / "
            "Sell, based on the analysts' debate — describe what *you* would "
            "consider doing with the position, not an executed order."
        ),
    )
    confidence: ConfidenceLevel = Field(
        description=(
            "Conviction in the advisory stance: High = evidence aligns strongly; "
            "Medium = mixed or timing-sensitive; Low = thin data, conflicting "
            "signals, or elevated uncertainty — the human should size skepticism accordingly."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise personal action plan for the investor: what to consider "
            "doing, key levels, time horizon, and what would change the view. "
            "Two to four sentences. Advisory only."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    investor_framing: str = Field(
        description=(
            "Two or three sentences for the human reader: how to mentally frame "
            "this name right now (patience vs urgency, what deserves calm monitoring "
            "vs real worry). Supportive, disciplined tone — not hype, not fear-mongering. "
            "This is guidance for reflection, not therapy or personalized investment advice."
        ),
    )
    stance_vs_prior: Optional[str] = Field(
        default=None,
        description=(
            "If past lessons in the prompt support a comparison, one or two sentences "
            "on what changed or stayed the same versus that implicit prior stance. "
            "Otherwise null or omit."
        ),
    )
    price_target: Optional[float] = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )


# ---------------------------------------------------------------------------
# Research And Execution (merged Research Manager + Trader)
# ---------------------------------------------------------------------------


class ResearchExecutionPlan(BaseModel):
    """Combined output: investment plan (from Research Manager) + trade proposal (from Trader).

    Replaces the two-node Research Manager → Trader sequence with a single
    LLM call that produces both artifacts.  Each render helper slices the
    relevant fields so the downstream state fields keep their existing shape.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "Investment recommendation: Buy / Overweight / Hold / Underweight / Sell. "
            "Reserve Hold for situations where the evidence on both sides is genuinely balanced."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key arguments (from the debate or analyst "
            "reports), ending with which view carried the recommendation. Speak naturally."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps: staged position sizing (start with half, add remainder "
            "over 2–4 weeks if thesis confirms), ~5% cap per name, average up not down, "
            "and 2–3 measurable thesis-break metrics to monitor."
        ),
    )
    trade_action: TraderAction = Field(
        description="Immediate transaction direction consistent with the recommendation: Buy, Hold, or Sell.",
    )
    trade_reasoning: str = Field(
        description=(
            "2–4 sentences justifying the trade action, anchored in the analyst reports "
            "and the investment plan above."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description=(
            "Optional sizing guidance consistent with the staged-entry policy, "
            "e.g. '2.5% now, add to 5% over 3 weeks if thesis confirms'."
        ),
    )


def render_research_execution_plan_part(plan: ResearchExecutionPlan) -> str:
    """Render the investment-plan portion (stored in AgentState.investment_plan)."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


def render_research_execution_trade_part(plan: ResearchExecutionPlan) -> str:
    """Render the trade-proposal portion (stored in AgentState.trader_investment_plan)."""
    parts = [
        f"**Action**: {plan.trade_action.value}",
        "",
        f"**Reasoning**: {plan.trade_reasoning}",
    ]
    if plan.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {plan.entry_price}"])
    if plan.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {plan.stop_loss}"])
    if plan.position_sizing:
        parts.extend(["", f"**Position Sizing**: {plan.position_sizing}"])
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{plan.trade_action.value.upper()}**"])
    return "\n".join(parts)


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        "> **Advisory only — for your review.** This software does not place trades "
        "or send orders to a broker. Use the sections below as a planning memo.",
        "",
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Confidence**: {decision.confidence.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
        "",
        f"**How to think about this**: {decision.investor_framing}",
    ]
    if decision.stance_vs_prior:
        parts.extend(["", f"**Versus prior context**: {decision.stance_vs_prior}"])
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)
