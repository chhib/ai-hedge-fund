#!/usr/bin/env python3
"""
Profiling script for CPU-heavy analyst routines.

Focuses on Jim Simons and Stanley Druckenmiller agents which have been identified
as having heavy numpy/pandas calculations.
"""

import cProfile
import pstats
import io
from pstats import SortKey
import sys
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.agents.jim_simons import (
    analyze_statistical_patterns,
    analyze_mean_reversion,
    analyze_momentum_indicators,
    analyze_anomalies,
    analyze_cross_sectional_factors,
    compute_risk_metrics,
)
from src.agents.stanley_druckenmiller import (
    analyze_growth_and_momentum,
    analyze_insider_activity,
    analyze_calendar_context,
    analyze_risk_reward,
    analyze_druckenmiller_valuation,
)
from src.tools.api import search_line_items, get_financial_metrics, get_prices, get_insider_trades, get_company_events
from src.data.borsdata_client import BorsdataClient


def load_sample_data():
    """Load sample data for a representative ticker."""
    # Use a Nordic ticker that's available in Börsdata
    ticker = "ERIC B"  # Ericsson B - Swedish stock
    print(f"Loading sample data for {ticker}...")

    # Pre-populate instrument caches to avoid caching overhead in profiling
    client = BorsdataClient()
    client.get_instruments()
    client.get_all_instruments()

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    # Fetch all data needed for both analysts
    financial_line_items = search_line_items(
        ticker,
        [
            "net_income", "earnings_per_share", "revenue", "operating_income",
            "total_assets", "total_liabilities", "current_assets", "current_liabilities",
            "free_cash_flow", "research_and_development", "capital_expenditure",
            "working_capital", "gross_margin", "operating_margin",
            "cash_and_equivalents", "total_debt", "shareholders_equity",
            "outstanding_shares", "ebit", "ebitda"
        ],
        end_date,
    )

    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5)
    prices = get_prices(ticker, start_date=start_date, end_date=end_date)
    insider_trades = get_insider_trades(ticker, end_date, limit=50)
    calendar_events = get_company_events(ticker, end_date, limit=50)

    print(f"  Loaded {len(financial_line_items)} financial line items")
    print(f"  Loaded {len(metrics)} metrics")
    print(f"  Loaded {len(prices)} prices")
    print(f"  Loaded {len(insider_trades)} insider trades")
    print(f"  Loaded {len(calendar_events)} calendar events")

    return {
        'financial_line_items': financial_line_items,
        'metrics': metrics,
        'prices': prices,
        'insider_trades': insider_trades,
        'calendar_events': calendar_events,
        'market_cap': 3_000_000_000_000  # Approximate AAPL market cap
    }


def profile_jim_simons_functions(data):
    """Profile all Jim Simons analysis functions."""
    print("\n" + "="*80)
    print("PROFILING JIM SIMONS AGENT FUNCTIONS")
    print("="*80)

    functions = [
        ('analyze_statistical_patterns', analyze_statistical_patterns, [data['financial_line_items']]),
        ('analyze_mean_reversion', analyze_mean_reversion, [data['financial_line_items']]),
        ('analyze_momentum_indicators', analyze_momentum_indicators, [data['financial_line_items']]),
        ('analyze_anomalies', analyze_anomalies, [data['financial_line_items']]),
        ('analyze_cross_sectional_factors', analyze_cross_sectional_factors, [data['financial_line_items']]),
        ('compute_risk_metrics', compute_risk_metrics, [data['financial_line_items']]),
    ]

    results = {}

    for func_name, func, args in functions:
        print(f"\n{'-'*80}")
        print(f"Profiling: {func_name}")
        print(f"{'-'*80}")

        profiler = cProfile.Profile()
        profiler.enable()

        # Run the function multiple times to get better statistics
        for _ in range(100):
            result = func(*args)

        profiler.disable()

        # Capture stats
        s = io.StringIO()
        stats = pstats.Stats(profiler, stream=s)
        stats.strip_dirs()
        stats.sort_stats(SortKey.CUMULATIVE)
        stats.print_stats(20)  # Top 20 functions

        results[func_name] = s.getvalue()

        # Print summary
        print(f"\nResult: {result}")
        print(f"\nTop 10 functions by cumulative time:")
        s = io.StringIO()
        stats = pstats.Stats(profiler, stream=s)
        stats.strip_dirs()
        stats.sort_stats(SortKey.CUMULATIVE)
        stats.print_stats(10)
        print(s.getvalue())

    return results


def profile_stanley_druckenmiller_functions(data):
    """Profile all Stanley Druckenmiller analysis functions."""
    print("\n" + "="*80)
    print("PROFILING STANLEY DRUCKENMILLER AGENT FUNCTIONS")
    print("="*80)

    functions = [
        ('analyze_growth_and_momentum', analyze_growth_and_momentum,
         [data['metrics'], data['financial_line_items'], data['prices']]),
        ('analyze_insider_activity', analyze_insider_activity, [data['insider_trades']]),
        ('analyze_calendar_context', analyze_calendar_context, [data['calendar_events']]),
        ('analyze_risk_reward', analyze_risk_reward,
         [data['financial_line_items'], data['prices']]),
        ('analyze_druckenmiller_valuation', analyze_druckenmiller_valuation,
         [data['financial_line_items'], data['market_cap']]),
    ]

    results = {}

    for func_name, func, args in functions:
        print(f"\n{'-'*80}")
        print(f"Profiling: {func_name}")
        print(f"{'-'*80}")

        profiler = cProfile.Profile()
        profiler.enable()

        # Run the function multiple times to get better statistics
        for _ in range(100):
            result = func(*args)

        profiler.disable()

        # Capture stats
        s = io.StringIO()
        stats = pstats.Stats(profiler, stream=s)
        stats.strip_dirs()
        stats.sort_stats(SortKey.CUMULATIVE)
        stats.print_stats(20)  # Top 20 functions

        results[func_name] = s.getvalue()

        # Print summary
        print(f"\nResult: {result}")
        print(f"\nTop 10 functions by cumulative time:")
        s = io.StringIO()
        stats = pstats.Stats(profiler, stream=s)
        stats.strip_dirs()
        stats.sort_stats(SortKey.CUMULATIVE)
        stats.print_stats(10)
        print(s.getvalue())

    return results


def profile_combined_workflow(data):
    """Profile the complete analyst workflow for both agents."""
    print("\n" + "="*80)
    print("PROFILING COMBINED WORKFLOW (10 iterations)")
    print("="*80)

    def run_jim_simons_workflow():
        """Run complete Jim Simons analysis."""
        analyze_statistical_patterns(data['financial_line_items'])
        analyze_mean_reversion(data['financial_line_items'])
        analyze_momentum_indicators(data['financial_line_items'])
        analyze_anomalies(data['financial_line_items'])
        analyze_cross_sectional_factors(data['financial_line_items'])
        compute_risk_metrics(data['financial_line_items'])

    def run_druckenmiller_workflow():
        """Run complete Druckenmiller analysis."""
        analyze_growth_and_momentum(data['metrics'], data['financial_line_items'], data['prices'])
        analyze_insider_activity(data['insider_trades'])
        analyze_calendar_context(data['calendar_events'])
        analyze_risk_reward(data['financial_line_items'], data['prices'])
        analyze_druckenmiller_valuation(data['financial_line_items'], data['market_cap'])

    # Profile Jim Simons workflow
    print("\nJim Simons Complete Workflow:")
    profiler = cProfile.Profile()
    profiler.enable()

    for _ in range(10):
        run_jim_simons_workflow()

    profiler.disable()

    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.strip_dirs()
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats(30)
    print(s.getvalue())

    # Profile Druckenmiller workflow
    print("\n" + "-"*80)
    print("Stanley Druckenmiller Complete Workflow:")
    profiler = cProfile.Profile()
    profiler.enable()

    for _ in range(10):
        run_druckenmiller_workflow()

    profiler.disable()

    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.strip_dirs()
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats(30)
    print(s.getvalue())


def main():
    """Main profiling entry point."""
    print("="*80)
    print("ANALYST PROFILING TOOL")
    print("="*80)
    print(f"Started at: {datetime.now()}")

    # Load sample data
    data = load_sample_data()

    # Profile individual functions
    jim_simons_results = profile_jim_simons_functions(data)
    druckenmiller_results = profile_stanley_druckenmiller_functions(data)

    # Profile combined workflows
    profile_combined_workflow(data)

    print("\n" + "="*80)
    print("PROFILING COMPLETE")
    print("="*80)
    print(f"Finished at: {datetime.now()}")
    print("\nKey findings:")
    print("- Check the cumulative time for each function")
    print("- Look for numpy/pandas operations in the hot paths")
    print("- Consider vectorization opportunities for loops")
    print("- Identify redundant calculations that could be cached")


if __name__ == "__main__":
    main()
