import concurrent.futures
import warnings
from dotenv import load_dotenv

# Suppress LangChain deprecation warnings
warnings.filterwarnings("ignore", message=".*Importing debug from langchain root module.*", category=UserWarning)
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
from src.data.parallel_api_wrapper import run_parallel_fetch_ticker_data
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
    ticker_markets: dict[str, str] = None,
):
    # Start progress tracking
    progress.start()

    all_decisions = {}
    all_analyst_signals = {}

    try:
        # Create a single workflow for all analysts (this will be reused for each ticker)
        base_agent = create_workflow(selected_analysts if selected_analysts else None)

        # PERFORMANCE OPTIMIZATION: Pre-initialize expensive shared resources
        import time
        init_start = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] Pre-initializing shared resources...")

        # Pre-initialize currency service and BorsdataClient caches to avoid redundant API calls
        from src.tools.api import _borsdata_client

        # Pre-populate instrument caches (both Nordic and Global) to avoid repeated fetches
        print(f"[{time.strftime('%H:%M:%S')}] Pre-populating instrument caches...")
        try:
            # Pre-populate Nordic instruments cache
            _borsdata_client.get_instruments(force_refresh=False)
            print(f"[{time.strftime('%H:%M:%S')}] ✓ Nordic instruments cache populated")

            # Pre-populate Global instruments cache
            _borsdata_client.get_all_instruments(force_refresh=False)
            print(f"[{time.strftime('%H:%M:%S')}] ✓ Global instruments cache populated")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Warning: Could not pre-populate instrument caches: {e}")

        if exchange_rate_service:
            print(f"[{time.strftime('%H:%M:%S')}] Initializing currency mapping...")
            exchange_rate_service._initialize_currency_map()  # Do this once globally
            print(f"[{time.strftime('%H:%M:%S')}] ✓ Currency mapping initialized")

        init_end = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Shared resources initialized ({init_end - init_start:.2f}s)")

        # Now prefetch ALL data for ALL tickers in parallel
        prefetch_start = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] Prefetching data for all tickers in parallel...")

        # Use the new parallel fetcher
        all_prefetched_data = run_parallel_fetch_ticker_data(
            tickers=tickers,
            end_date=end_date,
            start_date=start_date,
            include_prices=True,
            include_metrics=True,
            include_line_items=True,
            include_insider_trades=True,
            include_events=True,
            include_market_caps=True,
            ticker_markets=ticker_markets,
        )

        prefetch_end = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Parallel prefetching completed for {len(all_prefetched_data)} tickers ({prefetch_end - prefetch_start:.2f}s total)")

        def process_single_analyst_ticker(analyst_key: str, ticker: str, prefetched_data: dict):
            """Process a single analyst for a single ticker - maximum parallelization"""
            analyst_start = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] Processing {analyst_key} for {ticker}", flush=True)

            # Get the specific analyst function
            from src.utils.analysts import get_analyst_nodes
            analyst_nodes = get_analyst_nodes()

            if analyst_key not in analyst_nodes:
                return None

            node_name, node_func = analyst_nodes[analyst_key]

            # Create minimal state for this specific analyst×ticker combination
            state = {
                "messages": [
                    HumanMessage(content=f"Analyze {ticker}")
                ],
                "data": {
                    "tickers": [ticker],
                    "portfolio": portfolio,
                    "start_date": start_date,
                    "end_date": end_date,
                    "analyst_signals": {},
                    "exchange_rate_service": exchange_rate_service,
                    "target_currency": target_currency,
                    # Use the pre-fetched data for ALL tickers
                    "prefetched_financial_data": prefetched_data
                },
                "metadata": {
                    "show_reasoning": show_reasoning,
                    "model_name": model_name,
                    "model_provider": model_provider,
                },
            }

            # Run the specific analyst (no additional API calls needed!)
            try:
                result_state = node_func(state)
                analyst_end = time.time()
                print(f"[{time.strftime('%H:%M:%S')}] ✓ {analyst_key} completed for {ticker} ({analyst_end - analyst_start:.2f}s)")
                return {
                    "analyst_key": analyst_key,
                    "ticker": ticker,
                    "signals": result_state["data"]["analyst_signals"],
                }
            except Exception as e:
                analyst_end = time.time()
                print(f"[{time.strftime('%H:%M:%S')}] ❌ Error in {analyst_key} for {ticker} ({analyst_end - analyst_start:.2f}s): {e}")
                return None

        # Create all analyst×ticker combinations for maximum parallelization
        analyst_ticker_combinations = [
            (analyst_key, ticker)
            for analyst_key in (selected_analysts if selected_analysts else ["jim_simons", "stanley_druckenmiller"])
            for ticker in tickers
        ]

        print(f"Running {len(analyst_ticker_combinations)} analyst×ticker combinations in parallel...")

        # Process all combinations in parallel with rate limiting consideration
        max_workers = min(len(analyst_ticker_combinations), 8)  # Limit to avoid overwhelming APIs
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_combo = {
                executor.submit(process_single_analyst_ticker, analyst_key, ticker, all_prefetched_data): (analyst_key, ticker)
                for analyst_key, ticker in analyst_ticker_combinations
            }

            for future in concurrent.futures.as_completed(future_to_combo):
                analyst_key, ticker = future_to_combo[future]
                try:
                    result = future.result()
                    if result:
                        # Merge analyst signals properly
                        for agent_name, signals in result["signals"].items():
                            if agent_name not in all_analyst_signals:
                                all_analyst_signals[agent_name] = {}
                            all_analyst_signals[agent_name].update(signals)
                except Exception as exc:
                    print(f'{analyst_key} for {ticker} generated an exception: {exc}')

        # Now run portfolio and risk management on the collected signals
        print("Running portfolio and risk management...")
        portfolio_state = {
            "messages": [
                HumanMessage(content="Analyze collected analyst signals and make portfolio decisions")
            ],
            "data": {
                "tickers": tickers,
                "portfolio": portfolio,
                "start_date": start_date,
                "end_date": end_date,
                "analyst_signals": all_analyst_signals,
                "exchange_rate_service": exchange_rate_service,
                "target_currency": target_currency,
            },
            "metadata": {
                "show_reasoning": show_reasoning,
                "model_name": model_name,
                "model_provider": model_provider,
            },
        }

        # Run risk and portfolio management
        portfolio_state = risk_management_agent(portfolio_state)
        portfolio_state = portfolio_management_agent(portfolio_state)

        # Extract final decisions
        if portfolio_state["messages"]:
            final_decisions = parse_hedge_fund_response(portfolio_state["messages"][-1].content)
            if final_decisions:
                all_decisions.update(final_decisions)

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



def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = CustomStateGraph(AgentState)
    workflow.add_node("start_node", start)

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

    # Connect start to all selected analysts (parallel execution)
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge("start_node", node_name)

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
        ticker_markets=inputs.ticker_markets,
    )

    # Display the results
    if result:
        print_trading_output(result)
    else:
        print(f"{Fore.RED}No results returned from analysis{Style.RESET_ALL}")
