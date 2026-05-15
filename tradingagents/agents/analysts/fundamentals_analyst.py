from langchain_core.messages import SystemMessage
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_fundamentals_summary,
    get_income_statement,
    get_investor_policy_full_instruction,
    get_insider_transactions,
    get_language_instruction,
)
from tradingagents.dataflows.config import get_config


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_fundamentals_summary,
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
        ]

        # Static: instructions + policy — cached across all ticker runs for the same session.
        # Anthropic prompt caching kicks in at 2048+ tokens; INVESTOR_POLICY_FULL alone is ~1500 tokens
        # and crosses the threshold once learned rules accumulate.
        static_system = (
            "You are a helpful AI assistant, collaborating with other assistants."
            " Use the provided tools to progress towards answering the question."
            " If you are unable to fully answer, that's OK; another assistant with different tools"
            " will help where you left off. Execute what you can to make progress."
            " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
            " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
            f" You have access to the following tools: {', '.join([t.name for t in tools])}.\n"
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + " Start by calling `get_fundamentals_summary` to get the key financial metrics (revenue, margins, FCF, debt, EPS) in a concise format. Then use `get_fundamentals` for company profile context. Only call `get_balance_sheet`, `get_cashflow`, or `get_income_statement` if you need detail beyond what the summary provides."
            + get_investor_policy_full_instruction()
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
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
