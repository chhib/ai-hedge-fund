#!/usr/bin/env python3
"""Refresh the Borsdata ticker-to-market mapping.

This script fetches all tickers from both Borsdata Nordic and Global markets,
creates a mapping table, and caches it locally for use by the CLI.

Usage:
    poetry run python scripts/refresh_borsdata_mapping.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.data.borsdata_ticker_mapping import refresh_ticker_mapping, get_ticker_mapping


def main():
    """Main execution function."""
    # Load environment variables
    load_dotenv()

    api_key = os.getenv("BORSDATA_API_KEY")
    if not api_key:
        print("❌ Error: BORSDATA_API_KEY not found in .env file")
        sys.exit(1)

    print("🔄 Refreshing Borsdata ticker mapping...")
    print()

    try:
        nordic_count, global_count = refresh_ticker_mapping(api_key=api_key)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    total_count = nordic_count + global_count

    print("✅ Ticker mapping refreshed successfully!")
    print()
    print("📊 Statistics:")
    print(f"   Nordic tickers: {nordic_count:,}")
    print(f"   Global tickers: {global_count:,}")
    print(f"   Total tickers:  {total_count:,}")
    print()

    # Show some sample tickers
    mapping = get_ticker_mapping()
    all_tickers = {ticker: market for ticker, market in mapping._mapping.items()}

    # Get samples
    nordic_samples = [t for t, m in all_tickers.items() if m == "Nordic"][:5]
    global_samples = [t for t, m in all_tickers.items() if m == "global"][:5]

    if nordic_samples:
        print("📋 Sample Nordic tickers:")
        for ticker in nordic_samples:
            print(f"   • {ticker}")
        print()

    if global_samples:
        print("📋 Sample Global tickers:")
        for ticker in global_samples:
            print(f"   • {ticker}")
        print()

    print("💡 You can now use just --tickers for any ticker without specifying the market!")
    print()
    print("Examples:")
    print("   poetry run python src/main.py --tickers AAPL,MSFT,TELIA,VOLV-B")
    print("   poetry run backtester --tickers AAPL,TELIA --start-date 2025-01-01 --end-date 2025-09-30")
    print()


if __name__ == "__main__":
    main()
