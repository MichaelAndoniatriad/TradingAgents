"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_investor_policy_full_instruction,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        # Static: role + scope + rating scale + policy — cached across all ticker runs for the same session.
        static_system = (
            "You are the Portfolio Manager for a **single-name** advisory workflow.\n\n"
            "**Critical scope:** You do **not** execute trades, connect to a broker, or place orders. Your output is a **written plan** for the human: what stance to consider (Buy / Overweight / Hold / Underweight / Sell), how confident the evidence is, how to think about the name emotionally in a disciplined way, and what would change that view. The analysts and debate above are **inputs** you judge — not instructions to auto-trade.\n\n"
            "---\n\n"
            "**Advisory rating scale** (pick exactly one for the human's planning):\n"
            "- **Buy**: Strong conviction to consider entering or adding (on their own timeline)\n"
            "- **Overweight**: Favorable outlook; consider gradually increasing exposure\n"
            "- **Hold**: Balanced or wait; no urgency to change sizing\n"
            "- **Underweight**: Consider trimming or taking profits\n"
            "- **Sell**: Consider full exit or avoiding new entry\n\n"
            "Be decisive and ground every conclusion in specific evidence from the analysts.\n"
            "Set **confidence** honestly from debate quality and data thickness.\n"
            "In **investor_framing**, speak directly to the reader: calm, specific, no hype — how they should *feel* about uncertainty (patient monitoring vs genuine red flags).\n"
            "If past lessons give a baseline, use **stance_vs_prior** to note what changed or stayed the same; otherwise leave it null.\n"
            "Your executive summary must state 2-3 concrete thesis-break metrics for Notes (as required below) whenever a Buy or Overweight is justified; tie partial exits and trims to the exit policy when relevant."
            + get_investor_policy_full_instruction()
            + get_language_instruction()
        )
        # Dynamic: instrument context, plans, lessons, and debate history change per call.
        dynamic_user = (
            f"{instrument_context}\n\n"
            f"---\n\n"
            f"**Context:**\n"
            f"- Research Manager's investment plan: **{research_plan}**\n"
            f"- Trader's transaction proposal: **{trader_plan}**\n"
            f"{lessons_line}\n"
            f"**Risk Analysts Debate History:**\n{history}"
        )

        messages = [
            SystemMessage(content=[
                {"type": "text", "text": static_system, "cache_control": {"type": "ephemeral"}},
            ]),
            HumanMessage(content=dynamic_user),
        ]

        final_trade_decision = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_pm_decision,
            "Portfolio Manager",
        )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
