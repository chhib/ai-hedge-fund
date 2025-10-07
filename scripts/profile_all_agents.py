#!/usr/bin/env python3
"""
Comprehensive profiling script for all 16 analyst agents.

Measures end-to-end execution time for each agent with real data,
including data fetching, computation, and LLM calls.
"""

import time
import sys
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.analysts import ANALYST_CONFIG
from src.graph.state import AgentState
from src.data.borsdata_client import BorsdataClient
from src.tools.api import search_line_items, get_financial_metrics, get_prices, get_insider_trades, get_company_events, get_market_cap, set_ticker_markets


def load_sample_data(ticker: str):
    """Load sample data for a ticker."""
    print(f"  Loading data for {ticker}...")

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    # Fetch all data needed
    start_time = time.time()

    financial_line_items = search_line_items(
        ticker,
        [
            "net_income", "earnings_per_share", "revenue", "operating_income",
            "total_assets", "total_liabilities", "current_assets", "current_liabilities",
            "free_cash_flow", "research_and_development", "capital_expenditure",
            "working_capital", "gross_margin", "operating_margin",
            "cash_and_equivalents", "total_debt", "shareholders_equity",
            "outstanding_shares", "ebit", "ebitda", "book_value"
        ],
        end_date,
    )

    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5)
    prices = get_prices(ticker, start_date=start_date, end_date=end_date)
    insider_trades = get_insider_trades(ticker, end_date, limit=50)
    calendar_events = get_company_events(ticker, end_date, limit=50)
    market_cap = get_market_cap(ticker, end_date)

    data_load_time = time.time() - start_time

    print(f"    ✓ Loaded in {data_load_time:.2f}s: {len(financial_line_items)} line items, "
          f"{len(metrics)} metrics, {len(prices)} prices, {len(insider_trades)} trades, "
          f"{len(calendar_events)} events")

    return {
        'ticker': ticker,
        'financial_line_items': financial_line_items,
        'metrics': metrics,
        'prices': prices,
        'insider_trades': insider_trades,
        'calendar_events': calendar_events,
        'market_cap': market_cap,
        'end_date': end_date,
        'start_date': start_date,
        'data_load_time': data_load_time,
    }


def create_agent_state(data: dict) -> AgentState:
    """Create an AgentState with prefetched data."""
    ticker = data['ticker']

    state = {
        "messages": [],
        "data": {
            "tickers": [ticker],
            "start_date": data['start_date'],
            "end_date": data['end_date'],
            "analyst_signals": {},
            "show_reasoning": False,  # Disable reasoning output for cleaner profiling
            # Prefetched data
            "prefetched_financial_data": {
                ticker: {
                    "financial_metrics": data['metrics'],
                    "line_items": data['financial_line_items'],
                    "market_cap": data['market_cap'],
                    "insider_trades": data['insider_trades'],
                    "company_events": data['calendar_events'],
                    "prices": data['prices'],
                }
            }
        },
        "metadata": {
            "show_reasoning": False,
        }
    }

    return state


def profile_agent(agent_key: str, agent_config: dict, state: AgentState, ticker: str) -> dict:
    """Profile a single agent's execution."""
    agent_func = agent_config['agent_func']
    display_name = agent_config['display_name']

    print(f"  Profiling: {display_name:<30}", end=" ", flush=True)

    try:
        start_time = time.time()
        result = agent_func(state)
        execution_time = time.time() - start_time

        # Check if agent produced output
        signal_data = state["data"]["analyst_signals"].get(f"{agent_key}_agent", {})
        success = len(signal_data) > 0

        # Extract signal if available
        ticker_signal = signal_data.get(ticker, {})
        signal = ticker_signal.get("signal", "unknown")
        confidence = ticker_signal.get("confidence", 0)

        status = "✓" if success else "✗"
        print(f"{status} {execution_time:6.3f}s  signal={signal:8s}  confidence={confidence:5.1f}%")

        return {
            "agent_key": agent_key,
            "display_name": display_name,
            "execution_time": execution_time,
            "success": success,
            "signal": signal,
            "confidence": confidence,
            "error": None
        }

    except Exception as e:
        execution_time = time.time() - start_time
        print(f"✗ {execution_time:6.3f}s  ERROR: {str(e)[:60]}")

        return {
            "agent_key": agent_key,
            "display_name": display_name,
            "execution_time": execution_time,
            "success": False,
            "signal": "error",
            "confidence": 0,
            "error": str(e)
        }


def profile_all_agents(ticker: str):
    """Profile all agents with a single ticker."""
    print(f"\n{'='*80}")
    print(f"PROFILING ALL AGENTS WITH {ticker}")
    print(f"{'='*80}\n")

    # Pre-populate caches
    print("Initializing Börsdata client...")
    client = BorsdataClient()
    client.get_instruments()
    client.get_all_instruments()

    # Set ticker market for proper routing
    if ticker.endswith(" B") or ticker.endswith(" A"):
        set_ticker_markets({ticker: "Nordic"})
    else:
        set_ticker_markets({ticker: "global"})

    # Load data once
    print("\nLoading data...")
    data = load_sample_data(ticker)

    # Create state
    state = create_agent_state(data)

    # Profile each agent
    print(f"\nProfiling {len(ANALYST_CONFIG)} agents...\n")
    results = []

    for agent_key, agent_config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]['order']):
        result = profile_agent(agent_key, agent_config, state, ticker)
        results.append(result)

    return results, data['data_load_time']


def print_summary(results: list, data_load_time: float):
    """Print summary statistics."""
    print(f"\n{'='*80}")
    print("PROFILING SUMMARY")
    print(f"{'='*80}\n")

    # Calculate statistics
    total_time = sum(r['execution_time'] for r in results)
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful

    print(f"Data Loading Time:     {data_load_time:6.2f}s")
    print(f"Total Agent Execution: {total_time:6.2f}s")
    print(f"Overall Total:         {data_load_time + total_time:6.2f}s")
    print(f"Successful Agents:     {successful}/{len(results)}")
    if failed > 0:
        print(f"Failed Agents:         {failed}")

    # Sort by execution time
    sorted_results = sorted(results, key=lambda x: x['execution_time'], reverse=True)

    print(f"\n{'─'*80}")
    print("SLOWEST AGENTS (Top 10)")
    print(f"{'─'*80}\n")
    print(f"{'Rank':<6} {'Agent':<30} {'Time':<10} {'Signal':<10} {'Confidence':<12}")
    print(f"{'─'*80}")

    for i, result in enumerate(sorted_results[:10], 1):
        time_str = f"{result['execution_time']:.3f}s"
        conf_str = f"{result['confidence']:.1f}%" if result['confidence'] > 0 else "N/A"
        print(f"{i:<6} {result['display_name']:<30} {time_str:<10} {result['signal']:<10} {conf_str:<12}")

    # Show errors if any
    errors = [r for r in results if not r['success']]
    if errors:
        print(f"\n{'─'*80}")
        print("ERRORS")
        print(f"{'─'*80}\n")
        for result in errors:
            error_msg = result['error'] or "Unknown error"
            print(f"  {result['display_name']}: {error_msg[:100]}")

    # Performance categories
    print(f"\n{'─'*80}")
    print("PERFORMANCE CATEGORIES")
    print(f"{'─'*80}\n")

    fast = [r for r in results if r['execution_time'] < 1.0]
    medium = [r for r in results if 1.0 <= r['execution_time'] < 5.0]
    slow = [r for r in results if r['execution_time'] >= 5.0]

    print(f"Fast (<1s):     {len(fast):2d} agents")
    print(f"Medium (1-5s):  {len(medium):2d} agents")
    print(f"Slow (≥5s):     {len(slow):2d} agents")

    if slow:
        print(f"\nSlow agents requiring optimization:")
        for r in slow:
            print(f"  • {r['display_name']}: {r['execution_time']:.2f}s")

    # LLM vs Non-LLM analysis
    print(f"\n{'─'*80}")
    print("KEY INSIGHTS")
    print(f"{'─'*80}\n")

    avg_time = total_time / len(results)
    print(f"Average agent execution time: {avg_time:.2f}s")
    print(f"Fastest agent: {sorted_results[-1]['display_name']} ({sorted_results[-1]['execution_time']:.2f}s)")
    print(f"Slowest agent: {sorted_results[0]['display_name']} ({sorted_results[0]['execution_time']:.2f}s)")
    print(f"Speedup potential: {sorted_results[0]['execution_time'] / sorted_results[-1]['execution_time']:.1f}x")


def main():
    """Main profiling entry point."""
    print("="*80)
    print("COMPREHENSIVE AGENT PROFILING TOOL")
    print("="*80)
    print(f"Started at: {datetime.now()}")
    print(f"Testing {len(ANALYST_CONFIG)} analyst agents")

    # Use a ticker with good data coverage
    ticker = "ABB"  # ABB - Swedish engineering stock with complete data

    try:
        results, data_load_time = profile_all_agents(ticker)
        print_summary(results, data_load_time)

        # Save results to JSON
        output_file = "profiling_results.json"
        with open(output_file, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "data_load_time": data_load_time,
                "results": results
            }, f, indent=2)

        print(f"\n✓ Results saved to {output_file}")

    except KeyboardInterrupt:
        print("\n\nProfiling interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"\nFinished at: {datetime.now()}")
    print("="*80)


if __name__ == "__main__":
    main()
