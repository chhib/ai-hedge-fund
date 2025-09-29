#!/usr/bin/env python3
"""
Quick test of parallel Börsdata fetching.
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

from data.parallel_borsdata_client import run_parallel_fetch


def main():
    """Quick test with 2 tickers and all data types."""
    print("🚀 Quick parallel fetch test...")

    # Check API key
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        print("❌ BORSDATA_API_KEY not set")
        return

    start_time = time.time()

    # Test with 2 tickers - this will make about 6 API calls total
    # (2 prices + 2 metrics + 1 insider batch + 1 events batch)
    try:
        data = run_parallel_fetch(
            ["AAPL", "MSFT"],
            use_global=True,
            price_params={"max_count": 5}
        )

        end_time = time.time()
        print(f"✅ Completed in {end_time - start_time:.2f} seconds")

        # Show results
        for ticker, ticker_data in data.items():
            prices = len(ticker_data.get("prices", []))
            metrics = len(ticker_data.get("metrics", {}).get("values", []))
            insider = len(ticker_data.get("insider_trades", []))
            events = len(ticker_data.get("events", []))

            print(f"{ticker}: {prices} prices, {metrics} metrics, {insider} insider, {events} events")

        print("🎉 Parallel fetching working!")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()