from langchain_core.messages import SystemMessage
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_investor_policy_analyst_supplement,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.config import get_config


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_global_news,
        ]

        # Static: instructions + policy — cached across all ticker runs for the same session.
        static_system = (
            "You are a helpful AI assistant, collaborating with other assistants."
            " Use the provided tools to progress towards answering the question."
            " If you are unable to fully answer, that's OK; another assistant with different tools"
            " will help where you left off. Execute what you can to make progress."
            " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
            " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
            f" You have access to the following tools: {', '.join([t.name for t in tools])}.\n"
            "You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(query, start_date, end_date) for company-specific or targeted news searches, and get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + get_investor_policy_analyst_supplement()
            + get_language_instruction()
        )
        # Dynamic: date + ticker change per call — kept outside the cached block
        dynamic_system = f"For your reference, the current date is {current_date}. {instrument_context}"

        system_msg = SystemMessage(content=[
            {"type": "text", "text": static_system, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_system},
        ])

        chain = llm.bind_tools(tools)
        result = chain.invoke([system_msg] + list(state["messages"]))

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
