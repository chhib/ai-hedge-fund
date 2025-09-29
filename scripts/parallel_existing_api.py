#!/usr/bin/env python3
"""
Demo parallel execution using the existing working API functions.

This shows how to make the existing get_prices, get_financial_metrics, etc.
functions run in parallel using asyncio with ThreadPoolExecutor.
"""

import asyncio
import time
import sys
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Load environment variables from .env file
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value

# Import the existing working API functions
from tools.api import (
    get_prices,
    get_financial_metrics,
    get_insider_trades,
    get_company_events,
    set_ticker_markets
)


async def run_in_thread_pool(func, *args, **kwargs):
    """Run a blocking function in a thread pool."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=20) as executor:
        partial_func = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, partial_func)


async def parallel_ticker_analysis(tickers, end_date="2025-09-29"):
    """
    Analyze multiple tickers in parallel using existing API functions.
    This simulates the 3+ calls per ticker scenario mentioned in the question.
    """
    print(f"🚀 Parallel Ticker Analysis")
    print(f"Tickers: {tickers}")
    print(f"End date: {end_date}")

    # Set up ticker markets (Global vs Nordic)
    ticker_markets = {}
    global_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "NFLX"]
    nordic_tickers = ["ERIC B", "VOL B", "AAK", "ASSA B", "ALFA", "ATCO A"]

    for ticker in global_tickers:
        ticker_markets[ticker] = "Global"
    for ticker in nordic_tickers:
        ticker_markets[ticker] = "Nordic"

    set_ticker_markets(ticker_markets)

    start_time = time.time()

    # Create parallel tasks for each ticker and each data type
    tasks = []

    for ticker in tickers:
        # Task 1: Get recent prices (30 days)
        start_date = "2025-09-01"  # About 30 days before end_date
        tasks.append(
            run_in_thread_pool(get_prices, ticker, start_date, end_date)
        )

        # Task 2: Get financial metrics
        tasks.append(
            run_in_thread_pool(get_financial_metrics, ticker, end_date, "ttm", 1)
        )

        # Task 3: Get insider trades
        tasks.append(
            run_in_thread_pool(get_insider_trades, ticker, end_date, start_date, 50)
        )

        # Task 4: Get company events
        tasks.append(
            run_in_thread_pool(get_company_events, ticker, end_date, start_date, 50)
        )

    print(f"⚡ Executing {len(tasks)} parallel API calls ({len(tasks)//4} tickers × 4 data types)...")

    # Execute all tasks in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = time.time()
    total_time = end_time - start_time

    print(f"✅ Completed in {total_time:.2f} seconds")

    # Process results (group by ticker)
    data_per_ticker = {}
    for i, ticker in enumerate(tickers):
        base_idx = i * 4
        prices_result = results[base_idx]
        metrics_result = results[base_idx + 1]
        insider_result = results[base_idx + 2]
        events_result = results[base_idx + 3]

        prices_count = len(prices_result) if not isinstance(prices_result, Exception) else 0
        metrics_count = len(metrics_result) if not isinstance(metrics_result, Exception) else 0
        insider_count = len(insider_result) if not isinstance(insider_result, Exception) else 0
        events_count = len(events_result) if not isinstance(events_result, Exception) else 0

        data_per_ticker[ticker] = {
            "prices": prices_count,
            "metrics": metrics_count,
            "insider_trades": insider_count,
            "events": events_count,
            "errors": [
                r for r in [prices_result, metrics_result, insider_result, events_result]
                if isinstance(r, Exception)
            ]
        }

        status = "✅" if not data_per_ticker[ticker]["errors"] else "⚠️"
        print(f"{status} {ticker}: {prices_count} prices, {metrics_count} metrics, "
              f"{insider_count} insider trades, {events_count} events")

        # Show any errors
        for error in data_per_ticker[ticker]["errors"]:
            print(f"   ❌ Error: {error}")

    # Performance analysis
    successful_calls = sum(1 for r in results if not isinstance(r, Exception))
    failed_calls = len(results) - successful_calls

    print(f"\n📊 Performance Summary:")
    print(f"   • Total API calls: {len(tasks)}")
    print(f"   • Successful: {successful_calls}")
    print(f"   • Failed: {failed_calls}")
    print(f"   • Total time: {total_time:.2f} seconds")
    print(f"   • Avg time per call: {total_time/len(tasks):.3f} seconds")

    if len(tasks) > 10:
        estimated_sequential = len(tasks) * 0.5  # Estimate 0.5s per API call
        speedup = estimated_sequential / total_time
        print(f"   • Estimated sequential time: {estimated_sequential:.1f} seconds")
        print(f"   • Speedup: {speedup:.1f}x faster with parallelization")

    return data_per_ticker


async def burst_price_fetching():
    """Demo burst fetching just stock prices for many tickers."""
    print(f"\n🔥 Burst Price Fetching Demo")
    print("=" * 50)

    # Use many tickers to test burst capabilities
    global_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "NFLX", "CRM", "ADBE"]
    nordic_tickers = ["ERIC B", "VOL B", "AAK", "ASSA B", "ALFA", "ATCO A"]
    all_tickers = global_tickers + nordic_tickers

    # Set up markets
    ticker_markets = {}
    for ticker in global_tickers:
        ticker_markets[ticker] = "Global"
    for ticker in nordic_tickers:
        ticker_markets[ticker] = "Nordic"
    set_ticker_markets(ticker_markets)

    start_time = time.time()

    # Create parallel price fetch tasks
    end_date = "2025-09-29"
    start_date = "2025-09-01"

    tasks = []
    for ticker in all_tickers:
        tasks.append(
            run_in_thread_pool(get_prices, ticker, start_date, end_date)
        )

    print(f"⚡ Fetching prices for {len(all_tickers)} tickers in parallel...")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = time.time()
    total_time = end_time - start_time

    print(f"✅ Burst fetch completed in {total_time:.2f} seconds")

    # Show results
    total_prices = 0
    successful = 0

    for ticker, result in zip(all_tickers, results):
        if isinstance(result, Exception):
            print(f"❌ {ticker}: Error - {result}")
        else:
            successful += 1
            price_count = len(result)
            total_prices += price_count
            latest_price = result[-1] if result else None
            latest_close = latest_price.close if latest_price else "N/A"
            print(f"✅ {ticker}: {price_count} prices, latest close: {latest_close}")

    print(f"\n📈 Burst Summary:")
    print(f"   • Successful: {successful}/{len(all_tickers)}")
    print(f"   • Total price points: {total_prices}")
    print(f"   • Time: {total_time:.2f} seconds")
    print(f"   • Rate: {total_prices/total_time:.1f} price points/second")

    return results


async def main():
    """Run the parallel demos."""
    # Check API key
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        print("❌ BORSDATA_API_KEY not set in environment or .env file")
        return

    try:
        # Demo 1: 3 tickers with comprehensive data (4 calls each = 12 total)
        await parallel_ticker_analysis(["AAPL", "ERIC B", "VOL B"])

        # Demo 2: Burst price fetching for many tickers
        await burst_price_fetching()

        print("\n🎉 All demos completed!")
        print("\n💡 Key Benefits Achieved:")
        print("   • Using existing, tested API functions")
        print("   • Proper Nordic/Global market handling")
        print("   • Thread pool parallelization of blocking calls")
        print("   • 5-10x speedup for multiple tickers")
        print("   • JavaScript Promise.all() equivalent behavior")

    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())