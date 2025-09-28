import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from colorama import Fore, Style, init
import questionary
from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.graph.state import AgentState
from src.utils.display import print_trading_output
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.progress import progress
from src.utils.visualize import save_graph_as_png
from src.tools.api import set_ticker_markets, get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.cli.input import (
    parse_cli_inputs,
)

import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json

# Load environment variables from .env file
load_dotenv()

init(autoreset=True)


def parse_hedge_fund_response(response):
    """Parses a JSON string and returns a dictionary."""
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}\nResponse: {repr(response)}")
        return None
    except TypeError as e:
        print(f"Invalid response type (expected string, got {type(response).__name__}): {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while parsing response: {e}\nResponse: {repr(response)}")
        return None


##### Run the Hedge Fund #####
def run_hedge_fund(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    show_reasoning: bool = False,
    selected_analysts: list[str] = [],
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
    exchange_rate_service: "ExchangeRateService" = None,
    target_currency: str = "USD",
):
    # Start progress tracking
    progress.start()

    try:
        # Build workflow (default to all analysts when none provided)
        workflow = create_workflow(selected_analysts if selected_analysts else None)
        agent = workflow.compile()

        final_state = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content="Make trading decisions based on the provided data.",
                    )
                ],
                "data": {
                    "tickers": tickers,
                    "portfolio": portfolio,
                    "start_date": start_date,
                    "end_date": end_date,
                    "analyst_signals": {},
                    "exchange_rate_service": exchange_rate_service,
                    "target_currency": target_currency,
                },
                "metadata": {
                    "show_reasoning": show_reasoning,
                    "model_name": model_name,
                    "model_provider": model_provider,
                },
            },
        )

        return {
            "decisions": parse_hedge_fund_response(final_state["messages"][-1].content),
            "analyst_signals": final_state["data"]["analyst_signals"],
        }
    finally:
        # Stop progress tracking
        progress.stop()


def _normalize_monetary_values(data, exchange_rate_service, target_currency):
    if not data or not exchange_rate_service:
        return data

    if isinstance(data, list):
        return [_normalize_monetary_values(item, exchange_rate_service, target_currency) for item in data]

    if not hasattr(data, 'currency') or data.currency == target_currency:
        return data

    rate = exchange_rate_service.get_rate(data.currency, target_currency)
    if rate is None:
        return data

    monetary_fields = [
        "market_cap", "enterprise_value", "net_debt", "earnings_per_share",
        "book_value_per_share", "free_cash_flow_per_share", "revenue_per_share",
        "ebit_per_share", "ebitda_per_share", "operating_cash_flow_per_share",
        "net_debt_per_share", "cash_per_share", "capital_expenditure",
        "depreciation_and_amortization", "net_income", "total_assets",
        "total_liabilities", "shareholders_equity",
        "dividends_and_other_cash_distributions",
        "issuance_or_purchase_of_equity_shares", "gross_profit", "revenue",
        "free_cash_flow", "current_assets", "current_liabilities"
    ]

    for field in monetary_fields:
        if hasattr(data, field) and getattr(data, field) is not None:
            setattr(data, field, getattr(data, field) * rate)
    
    data.currency = target_currency
    return data


def prefetch_financial_data(state: AgentState):
    """Pre-fetch all financial data needed by analysts to avoid duplicate API calls."""
    data = state["data"]
    tickers = data["tickers"]
    end_date = data["end_date"]
    exchange_rate_service = data.get("exchange_rate_service")
    target_currency = data.get("target_currency", "USD")

    # Extract API key if available
    api_key = None
    try:
        api_key = get_api_key_from_state(state, "BORSDATA_API_KEY")
    except:
        pass  # Continue without API key if not available

    # Store pre-fetched data in state
    prefetched_data = {}

    for ticker in tickers:
        progress.update_status("data_prefetch", ticker, "Fetching financial metrics")

        # Fetch all the data that analysts typically need
        financial_metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=api_key)
        financial_metrics = _normalize_monetary_values(financial_metrics, exchange_rate_service, target_currency)


        progress.update_status("data_prefetch", ticker, "Fetching line items")
        # Common line items used by multiple analysts
        line_items = search_line_items(
            ticker,
            [
                "capital_expenditure",
                "depreciation_and_amortization",
                "net_income",
                "outstanding_shares",
                "total_assets",
                "total_liabilities",
                "shareholders_equity",
                "dividends_and_other_cash_distributions",
                "issuance_or_purchase_of_equity_shares",
                "gross_profit",
                "revenue",
                "free_cash_flow",
                "current_assets",
                "current_liabilities",
            ],
            end_date,
            period="ttm",
            limit=10,
            api_key=api_key,
        )
        line_items = _normalize_monetary_values(line_items, exchange_rate_service, target_currency)

        progress.update_status("data_prefetch", ticker, "Fetching market cap")
        market_cap = get_market_cap(ticker, end_date, api_key=api_key)
        if market_cap and exchange_rate_service:
            # Assuming market_cap is a simple float and we need to know its currency.
            # The get_market_cap function does not return currency.
            # We will assume the currency of the market cap is the same as the financial_metrics.
            if financial_metrics:
                mc_currency = financial_metrics[0].currency
                rate = exchange_rate_service.get_rate(mc_currency, target_currency)
                if rate:
                    market_cap *= rate

        # Store all data for this ticker
        prefetched_data[ticker] = {
            "financial_metrics": financial_metrics,
            "line_items": line_items,
            "market_cap": market_cap,
        }

        progress.update_status("data_prefetch", ticker, "Done")

    # Add prefetched data to state
    state["data"]["prefetched_financial_data"] = prefetched_data
    progress.update_status("data_prefetch", None, "All data prefetched")

    return state


def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)
    workflow.add_node("prefetch_data", prefetch_financial_data)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())
    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("prefetch_data", node_name)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    # Connect start -> prefetch -> analysts -> risk management
    workflow.add_edge("start_node", "prefetch_data")

    # Connect selected analysts to risk management
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")
    return workflow


if __name__ == "__main__":
    inputs = parse_cli_inputs(
        description="Run the hedge fund trading system",
        require_tickers=True,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

    tickers = inputs.tickers
    selected_analysts = inputs.selected_analysts
    
    # Set ticker market mappings for proper API endpoint selection
    if inputs.ticker_markets:
        set_ticker_markets(inputs.ticker_markets)

    # Construct portfolio here
    portfolio = {
        "cash": inputs.initial_cash,
        "margin_requirement": inputs.margin_requirement,
        "margin_used": 0.0,
        "positions": {
            ticker: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
            for ticker in tickers
        },
        "realized_gains": {
            ticker: {
                "long": 0.0,
                "short": 0.0,
            }
            for ticker in tickers
        },
    }

    result = run_hedge_fund(
        tickers=tickers,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
        portfolio=portfolio,
        show_reasoning=inputs.show_reasoning,
        selected_analysts=inputs.selected_analysts,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
    )
    print_trading_output(result)
