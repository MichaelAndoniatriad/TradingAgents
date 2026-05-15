# TradingAgents/graph/conditional_logic.py

import logging

from tradingagents.agents.utils.agent_states import AgentState

logger = logging.getLogger(__name__)

# Ordered so that a keyword earlier in the list wins when multiple match.
# All keys are lowercase; values are the normalised stance.
_RATING_KEYWORDS: dict[str, str] = {
    "overweight": "bullish",
    "buy": "bullish",
    "bullish": "bullish",
    "underweight": "bearish",
    "sell": "bearish",
    "bearish": "bearish",
    "hold": "neutral",
    "neutral": "neutral",
}


def _extract_rating(text: str) -> str | None:
    """Return the first normalised rating found in *text*, or None."""
    lower = text.lower()
    for kw, rating in _RATING_KEYWORDS.items():
        if kw in lower:
            return rating
    return None


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if social media analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""
        debate = state["investment_debate_state"]

        # Convergence check — only meaningful once both sides have spoken at least once.
        if debate["count"] >= 2:
            bull_rating = _extract_rating(debate["bull_history"][-500:])
            bear_rating = _extract_rating(debate["bear_history"][-500:])
            if bull_rating and bear_rating and bull_rating == bear_rating:
                logger.info(
                    "Investment debate converged on '%s' after %d exchanges — stopping early",
                    bull_rating,
                    debate["count"],
                )
                return "Research And Execution"

        if debate["count"] >= 2 * self.max_debate_rounds:
            return "Research And Execution"
        if debate["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        risk = state["risk_debate_state"]

        # Convergence check — requires aggressive and conservative to have each spoken.
        if risk["count"] >= 2:
            agg_rating = _extract_rating(risk["current_aggressive_response"])
            con_rating = _extract_rating(risk["current_conservative_response"])
            if agg_rating and con_rating and agg_rating == con_rating:
                logger.info(
                    "Risk debate converged on '%s' after %d exchanges — stopping early",
                    agg_rating,
                    risk["count"],
                )
                return "Portfolio Manager"

        if risk["count"] >= 2 * self.max_risk_discuss_rounds:
            return "Portfolio Manager"
        if risk["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        # Conservative goes back to Aggressive (neutral debator removed from graph)
        return "Aggressive Analyst"
