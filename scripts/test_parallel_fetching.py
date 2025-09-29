#!/usr/bin/env python3
"""
Test script demonstrating parallel Börsdata API fetching.

This script shows how to fetch data for multiple tickers in parallel,
utilizing the full 100 calls/10 seconds rate limit efficiently.
"""

import asyncio
import time
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data.parallel_borsdata_client import (
    ParallelBorsdataClient,
    parallel_fetch_multiple_tickers,
    run_parallel_fetch,
)


async def demo_basic_parallel_fetching():
    """Demonstrate basic parallel fetching for multiple tickers."""
    print("🚀 Testing basic parallel fetching...")

    # Test with a mix of Global and Nordic tickers
    global_tickers = ["AAPL", "MSFT", "NVDA"]
    nordic_tickers = ["ERIC B", "VOL B", "AAK"]

    start_time = time.time()

    # Fetch global tickers
    print(f"Fetching data for Global tickers: {global_tickers}")
    global_data = await parallel_fetch_multiple_tickers(
        global_tickers,
        use_global=True,
        price_params={"max_count": 30}  # Last 30 days of prices
    )

    # Fetch Nordic tickers
    print(f"Fetching data for Nordic tickers: {nordic_tickers}")
    nordic_data = await parallel_fetch_multiple_tickers(
        nordic_tickers,
        use_global=False,
        price_params={"max_count": 30}
    )

    end_time = time.time()
    total_time = end_time - start_time

    print(f"\n✅ Parallel fetch completed in {total_time:.2f} seconds")

    # Display results summary
    print("\n📊 Results Summary:")
    print("Global Tickers:")
    for ticker, data in global_data.items():
        prices_count = len(data.get("prices", []))
        metrics_count = len(data.get("metrics", {}).get("values", []))
        insider_count = len(data.get("insider_trades", []))
        events_count = len(data.get("events", []))

        print(f"  {ticker}: {prices_count} prices, {metrics_count} metrics, "
              f"{insider_count} insider trades, {events_count} events")

    print("\nNordic Tickers:")
    for ticker, data in nordic_data.items():
        prices_count = len(data.get("prices", []))
        metrics_count = len(data.get("metrics", {}).get("values", []))
        insider_count = len(data.get("insider_trades", []))
        events_count = len(data.get("events", []))

        print(f"  {ticker}: {prices_count} prices, {metrics_count} metrics, "
              f"{insider_count} insider trades, {events_count} events")

    return global_data, nordic_data


async def demo_burst_fetching():
    """Demonstrate burst fetching with many parallel calls."""
    print("\n🔥 Testing burst fetching (many parallel calls)...")

    # Use more tickers to test the rate limiting
    test_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "NFLX"]

    start_time = time.time()

    async with ParallelBorsdataClient() as client:
        # Create many individual tasks (this will create ~32 API calls)
        tasks = []

        for ticker in test_tickers:
            # 4 calls per ticker: prices, metrics, and 2 others
            tasks.extend([
                client.get_stock_prices_by_ticker(ticker, use_global=True, max_count=10),
                client.get_financial_metrics(ticker, use_global=True),
            ])

        # Add batch calls for insider trades and events
        tasks.extend([
            client.get_insider_trades(test_tickers, use_global=True),
            client.get_company_events(test_tickers, use_global=True),
        ])

        print(f"Executing {len(tasks)} parallel API calls...")

        # Execute all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_time = end_time - start_time

        print(f"✅ Burst fetch completed in {total_time:.2f} seconds")

        # Count successful vs failed requests
        successful = sum(1 for r in results if not isinstance(r, Exception))
        failed = sum(1 for r in results if isinstance(r, Exception))

        print(f"📈 Results: {successful} successful, {failed} failed API calls")

        if failed > 0:
            print("⚠️  Failed requests:")
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"  Task {i}: {result}")

    return results


def demo_synchronous_wrapper():
    """Demonstrate the synchronous wrapper for easy integration."""
    print("\n🔄 Testing synchronous wrapper...")

    start_time = time.time()

    # Use the synchronous wrapper
    data = run_parallel_fetch(
        ["AAPL", "MSFT"],
        use_global=True,
        include_insider_trades=False,  # Skip to reduce API calls
        include_events=False,
        price_params={"max_count": 5}
    )

    end_time = time.time()
    total_time = end_time - start_time

    print(f"✅ Sync fetch completed in {total_time:.2f} seconds")

    for ticker, ticker_data in data.items():
        print(f"  {ticker}: {len(ticker_data.get('prices', []))} prices, "
              f"{len(ticker_data.get('metrics', {}).get('values', []))} metrics")

    return data


async def main():
    """Run all demo functions."""
    print("🎯 Börsdata Parallel API Client Demo")
    print("=" * 50)

    try:
        # Test 1: Basic parallel fetching
        await demo_basic_parallel_fetching()

        # Test 2: Burst fetching with many calls
        await demo_burst_fetching()

        # Test 3: Synchronous wrapper
        demo_synchronous_wrapper()

        print("\n🎉 All tests completed successfully!")
        print("\n💡 Key Benefits:")
        print("   • Burst up to 95 API calls in parallel")
        print("   • Automatic rate limiting (100 calls/10 seconds)")
        print("   • JavaScript Promise-like async patterns")
        print("   • Efficient batch fetching for multiple tickers")
        print("   • Perfect for prefetching 3+ calls per ticker")

    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Check for API key
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        print("❌ Error: BORSDATA_API_KEY environment variable not set")
        print("   Set your API key with: export BORSDATA_API_KEY=your_key_here")
        sys.exit(1)

    # Run the demo
    asyncio.run(main())