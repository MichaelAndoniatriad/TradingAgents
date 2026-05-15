from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.agents.utils.agent_utils import (
    get_investor_policy_full_instruction,
    get_language_instruction,
)


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        # Static: role + policy — cached across all ticker runs for the same session.
        static_system = (
            "You are a Bear Analyst making the case against investing in the stock. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.\n\n"
            "Key points to focus on:\n\n"
            "- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.\n"
            "- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.\n"
            "- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.\n"
            "- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.\n"
            "- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts."
            + get_investor_policy_full_instruction()
            + get_language_instruction()
        )
        # Dynamic: reports + debate history change per call.
        dynamic_user = (
            f"Resources available:\n\n"
            f"Market research report: {market_research_report}\n"
            f"Social media sentiment report: {sentiment_report}\n"
            f"Latest world affairs news: {news_report}\n"
            f"Company fundamentals report: {fundamentals_report}\n"
            f"Conversation history of the debate: {history}\n"
            f"Last bull argument: {current_response}\n"
            f"Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the stock."
        )

        messages = [
            SystemMessage(content=[
                {"type": "text", "text": static_system, "cache_control": {"type": "ephemeral"}},
            ]),
            HumanMessage(content=dynamic_user),
        ]

        response = llm.invoke(messages)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
