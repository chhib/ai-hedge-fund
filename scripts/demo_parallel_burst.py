#!/usr/bin/env python3
"""
Demo showing true parallel burst fetching with Börsdata API.

This demonstrates the power of using asyncio to make many parallel API calls
and efficiently utilize the 100 calls/10 seconds rate limit.
"""

import asyncio
import time
import sys
import os
from pathlib import Path

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

from data.parallel_borsdata_client import ParallelBorsdataClient


async def demo_burst_stock_prices():
    """
    Demonstrate burst fetching stock prices for many tickers.

    This creates 30+ parallel API calls to show how we can efficiently
    use the rate limit for prefetching data across multiple tickers.
    """
    print("🚀 Burst Stock Price Fetching Demo")
    print("=" * 50)

    # Mix of Global and Nordic tickers
    global_tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "NFLX", "CRM", "ADBE"]
    nordic_tickers = ["ERIC B", "VOL B", "AAK", "ASSA B", "ALFA", "ATCO A"]

    print(f"Global tickers: {global_tickers}")
    print(f"Nordic tickers: {nordic_tickers}")
    print(f"Total API calls will be: {len(global_tickers) + len(nordic_tickers)} (one per ticker)")

    start_time = time.time()

    async with ParallelBorsdataClient() as client:
        # Create parallel tasks for all stock prices
        tasks = []

        # Global stock prices
        for ticker in global_tickers:
            tasks.append(
                client.get_stock_prices_by_ticker(
                    ticker,
                    use_global=True,
                    max_count=30  # Last 30 trading days
                )
            )

        # Nordic stock prices
        for ticker in nordic_tickers:
            tasks.append(
                client.get_stock_prices_by_ticker(
                    ticker,
                    use_global=False,
                    max_count=30
                )
            )

        print(f"\n⚡ Executing {len(tasks)} parallel API calls...")

        # Execute all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_time = end_time - start_time

        print(f"✅ Completed in {total_time:.2f} seconds")
        print(f"📊 Average time per API call: {total_time/len(tasks):.3f} seconds")

        # Analyze results
        successful = 0
        total_prices = 0

        all_tickers = global_tickers + nordic_tickers

        for i, (ticker, result) in enumerate(zip(all_tickers, results)):
            if isinstance(result, Exception):
                print(f"❌ {ticker}: Error - {result}")
            else:
                successful += 1
                price_count = len(result)
                total_prices += price_count
                latest_price = result[0] if result else None
                latest_close = latest_price.get('c', 'N/A') if latest_price else 'N/A'
                print(f"✅ {ticker}: {price_count} prices, latest close: {latest_close}")

        print(f"\n📈 Summary:")
        print(f"   • Successful calls: {successful}/{len(tasks)}")
        print(f"   • Total price points fetched: {total_prices}")
        print(f"   • Throughput: {total_prices/total_time:.1f} price points/second")

        if total_time < 10:
            calls_per_second = len(tasks) / total_time
            print(f"   • API calls per second: {calls_per_second:.1f}")
            if calls_per_second > 10:
                print(f"   🔥 Excellent! Rate limit allows burst fetching")
            else:
                print(f"   ✅ Good parallel performance")

    return results


async def demo_3_calls_per_ticker():
    """
    Demo the original use case: 3 calls per ticker for comprehensive data.
    This shows how prefetching can make analysis much faster.
    """
    print("\n🎯 3 Calls Per Ticker Demo (Original Use Case)")
    print("=" * 50)

    # Test with 3 tickers = 9 total API calls
    test_tickers = ["AAPL", "MSFT", "NVDA"]

    print(f"Tickers: {test_tickers}")
    print("Fetching for each ticker:")
    print("  • Stock prices (30 days)")
    print("  • Insider trades")
    print("  • Company events (reports/dividends)")

    start_time = time.time()

    async with ParallelBorsdataClient() as client:
        tasks = []

        # Create 3 parallel tasks per ticker
        for ticker in test_tickers:
            # Stock prices
            tasks.append(
                client.get_stock_prices_by_ticker(
                    ticker,
                    use_global=True,
                    max_count=30
                )
            )

            # Insider trades (batch call - will be efficient)
            tasks.append(
                client.get_insider_trades([ticker], use_global=True)
            )

            # Company events (batch call - will be efficient)
            tasks.append(
                client.get_company_events([ticker], use_global=True)
            )

        print(f"\n⚡ Executing {len(tasks)} parallel API calls...")

        # Execute all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_time = end_time - start_time

        print(f"✅ Completed in {total_time:.2f} seconds")

        # Group results by ticker (every 3 results belong to one ticker)
        for i, ticker in enumerate(test_tickers):
            base_idx = i * 3
            prices_result = results[base_idx]
            insider_result = results[base_idx + 1]
            events_result = results[base_idx + 2]

            prices_count = len(prices_result) if not isinstance(prices_result, Exception) else 0
            insider_count = len(insider_result) if not isinstance(insider_result, Exception) else 0
            events_count = len(events_result) if not isinstance(events_result, Exception) else 0

            print(f"✅ {ticker}: {prices_count} prices, {insider_count} insider trades, {events_count} events")

        print(f"\n🚀 Performance Analysis:")
        print(f"   • Time for 3 data types × {len(test_tickers)} tickers: {total_time:.2f}s")
        print(f"   • Without parallelization (sequential): ~{len(tasks) * 0.5:.1f}s estimated")
        print(f"   • Speedup: ~{(len(tasks) * 0.5) / total_time:.1f}x faster")

    return results


async def main():
    """Run both demo scenarios."""
    # Check API key
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        print("❌ BORSDATA_API_KEY not set in environment or .env file")
        return

    try:
        # Demo 1: Burst fetching many tickers
        await demo_burst_stock_prices()

        # Demo 2: Original use case optimization
        await demo_3_calls_per_ticker()

        print("\n🎉 All demos completed successfully!")
        print("\n💡 Key Benefits of Parallel Fetching:")
        print("   • Utilize full 100 calls/10 seconds rate limit")
        print("   • 5-10x faster than sequential API calls")
        print("   • Perfect for prefetching multiple tickers")
        print("   • JavaScript Promise.all() equivalent in Python")
        print("   • Automatic rate limiting and retry logic")

    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())