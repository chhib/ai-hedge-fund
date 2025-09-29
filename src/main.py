import concurrent.futures
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END
from colorama import Fore, Style, init
import questionary
from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.graph.state import AgentState
from src.graph.custom_state_graph import CustomStateGraph
from src.utils.display import print_trading_output
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.progress import progress
from src.utils.visualize import save_graph_as_png
from src.tools.api import set_ticker_markets, get_financial_metrics, get_market_cap, search_line_items
from src.utils.api_key import get_api_key_from_state
from src.cli.input import (
    parse_cli_inputs,
)
from src.llm.cache import setup_llm_cache

import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json

# Load environment variables from .env file
load_dotenv()

# Setup LLM caching
setup_llm_cache()

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

    all_decisions = {}
    all_analyst_signals = {}

    try:
        # Create a single workflow for all analysts (this will be reused for each ticker)
        base_agent = create_workflow(selected_analysts if selected_analysts else None)

        def process_single_ticker(ticker: str):
            print(f"Processing ticker: {ticker}", flush=True)
            # Each ticker gets its own initial state
            initial_state = {
                "messages": [
                    HumanMessage(
                        content=f"Make trading decisions for {ticker} based on the provided data.",
                    )
                ],
                "data": {
                    "tickers": [ticker],  # Pass only the current ticker
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
            }
            final_state = base_agent.invoke(initial_state)

            return {
                "decisions": parse_hedge_fund_response(final_state["messages"][-1].content),
                "analyst_signals": final_state["data"]["analyst_signals"],
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tickers)) as executor:
            future_to_ticker = {executor.submit(process_single_ticker, ticker): ticker for ticker in tickers}
            for future in concurrent.futures.as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    result = future.result()
                    # Merge decisions dictionaries instead of appending to list
                    if result["decisions"]:
                        all_decisions.update(result["decisions"])

                    # Properly merge analyst signals to avoid overwriting data from previous tickers
                    for agent_name, signals in result["analyst_signals"].items():
                        if agent_name not in all_analyst_signals:
                            all_analyst_signals[agent_name] = {}
                        # Merge the ticker-specific signals for this agent
                        all_analyst_signals[agent_name].update(signals)
                except Exception as exc:
                    print(f'{ticker} generated an exception: {exc}')

        return {
            "decisions": all_decisions,
            "analyst_signals": all_analyst_signals,
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

def _fetch_data_for_ticker(ticker: str, end_date: str, exchange_rate_service, target_currency: str, api_key: str, state: AgentState):
    """Helper function to fetch all financial data for a single ticker."""
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
    return {
        "financial_metrics": financial_metrics,
        "line_items": line_items,
        "market_cap": market_cap,
    }


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

    # The _fetch_data_for_ticker function now takes a single ticker
    # We need to call it directly for the single ticker in the state
    ticker = tickers[0] # Assuming state["data"]["tickers"] will only contain one ticker now
    prefetched_data[ticker] = _fetch_data_for_ticker(ticker, end_date, exchange_rate_service, target_currency, api_key, state)
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
    workflow = CustomStateGraph(AgentState)
    workflow.add_node("start_node", start)
    workflow.add_node("prefetch_data", prefetch_financial_data)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())

    # Add selected analyst nodes to the main workflow
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    # Connect start -> prefetch
    workflow.add_edge("start_node", "prefetch_data")

    # Connect prefetch to all selected analysts (parallel execution)
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge("prefetch_data", node_name)

    # Connect all selected analysts to risk management (join point)
    # The state will be merged using the defined reducer for analyst_signals
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")

    # Compile the workflow
    return workflow.compile(
        checkpointer=None,
    )


if __name__ == "__main__":
    from src.tools.api import set_ticker_markets
    from src.data.exchange_rate_service import ExchangeRateService

    # Parse CLI inputs
    inputs = parse_cli_inputs(
        description="Run AI hedge fund analysis",
        require_tickers=True,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

    # Set ticker markets
    set_ticker_markets(inputs.ticker_markets)

    # Initialize exchange rate service if we have mixed markets
    exchange_rate_service = None
    if inputs.ticker_markets and len(set(inputs.ticker_markets.values())) > 1:
        from src.data.borsdata_client import BorsdataClient
        borsdata_client = BorsdataClient()
        exchange_rate_service = ExchangeRateService(borsdata_client)

    # Create portfolio structure
    portfolio = {
        "cash": inputs.initial_cash,
        "total_value": inputs.initial_cash,
        "margin_requirement": inputs.margin_requirement,
    }

    print(f"\n{Fore.CYAN}Starting AI hedge fund analysis...{Style.RESET_ALL}\n")

    # Run the hedge fund analysis
    result = run_hedge_fund(
        tickers=inputs.tickers,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
        portfolio=portfolio,
        show_reasoning=inputs.show_reasoning,
        selected_analysts=inputs.selected_analysts,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
        exchange_rate_service=exchange_rate_service,
        target_currency="USD",
    )

    # Display the results
    if result:
        print_trading_output(result)
    else:
        print(f"{Fore.RED}No results returned from analysis{Style.RESET_ALL}")
