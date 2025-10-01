#!/usr/bin/env python3
"""Search for specific tickers in Börsdata."""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.data.borsdata_client import BorsdataClient


def search_instruments(client, search_term):
    """Search for instruments matching the term."""
    print(f"\n🔍 Searching for: '{search_term}'")
    print("=" * 80)

    all_instruments = client.get_all_instruments()
    matches = []

    search_upper = search_term.upper()

    for inst in all_instruments:
        ticker = inst.get("ticker", "").upper()
        name = inst.get("name", "").upper()
        ins_id = inst.get("insId", 0)

        # Check if search term matches ticker or name
        if search_upper in ticker or search_upper in name:
            market = "Global" if ins_id > 1000000 else "Nordic"
            matches.append({
                "ticker": inst.get("ticker", ""),
                "name": inst.get("name", ""),
                "insId": ins_id,
                "market": market,
                "isin": inst.get("isin", ""),
                "listId": inst.get("listId", "")
            })

    if matches:
        print(f"✓ Found {len(matches)} matches:\n")
        for match in sorted(matches, key=lambda x: (x["market"], x["ticker"])):
            print(f"  [{match['market']:<7}] {match['ticker']:<15} {match['name']}")
            print(f"              insId: {match['insId']}, ISIN: {match['isin']}")
            print()
    else:
        print("✗ No matches found\n")

    return matches


def main():
    """Main execution function."""
    load_dotenv()

    api_key = os.getenv("BORSDATA_API_KEY")
    if not api_key:
        print("❌ Error: BORSDATA_API_KEY not found in .env file")
        sys.exit(1)

    client = BorsdataClient(api_key=api_key)

    print("📥 Fetching all instruments...")
    all_instruments = client.get_all_instruments()
    print(f"✅ Loaded {len(all_instruments)} instruments\n")

    # Search for H&M variations
    search_terms = [
        "HM B",
        "H&M",
        "H & M",
        "HENNES",
        "HENNES & MAURITZ",
        "AKELIUS",
    ]

    all_results = {}
    for term in search_terms:
        results = search_instruments(client, term)
        if results:
            all_results[term] = results

    # Summary
    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)

    if all_results:
        print("\nFound tickers:")
        unique_tickers = set()
        for term, matches in all_results.items():
            for match in matches:
                ticker_key = (match["ticker"], match["market"])
                if ticker_key not in unique_tickers:
                    unique_tickers.add(ticker_key)
                    print(f"  • {match['ticker']:<15} [{match['market']:<7}] {match['name']}")
    else:
        print("\n❌ No matches found for any search terms")


if __name__ == "__main__":
    main()
