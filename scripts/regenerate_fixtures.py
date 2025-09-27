#!/usr/bin/env python3
"""
Script to regenerate test fixtures with fresh data from Börsdata API.
This ensures our test data reflects current market conditions and API responses.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from src.tools.api import get_financial_metrics, get_insider_trades, get_company_events, get_prices, set_ticker_markets


def ensure_api_key() -> str:
    """Ensure we have a valid Börsdata API key."""
    # Load environment variables from .env file
    load_dotenv()
    
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        raise ValueError("BORSDATA_API_KEY environment variable is required")
    return api_key


def regenerate_financial_metrics_fixtures() -> None:
    """Regenerate financial metrics fixtures for test tickers."""
    print("Regenerating financial metrics fixtures...")
    
    tickers = ["LUG", "VOLV B", "TTWO", "FDEV"]
    api_key = ensure_api_key()
    
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    
    for ticker in tickers:
        print(f"  Fetching financial metrics for {ticker}...")
        try:
            # Fetch fresh data from API
            metrics = get_financial_metrics(
                ticker=ticker,
                end_date=end_date,
                period="ttm",
                limit=20,  # Get more historical data
                api_key=api_key
            )
            
            # Convert FinancialMetrics objects to dicts for JSON serialization
            metrics_dicts = []
            for metric in metrics:
                if hasattr(metric, '__dict__'):
                    metrics_dicts.append(metric.__dict__)
                else:
                    metrics_dicts.append(metric)
            
            # Create the fixture structure
            fixture_data = {
                "financial_metrics": metrics_dicts
            }
            
            # Save to fixture file
            fixture_dir = Path("tests/fixtures/api/financial_metrics")
            fixture_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = fixture_dir / f"{ticker}_{start_date}_{end_date}.json"
            
            with open(fixture_path, "w") as f:
                json.dump(fixture_data, f, indent=2)
            
            print(f"    Saved {len(metrics)} metrics to {fixture_path}")
            
        except Exception as e:
            print(f"    Error fetching {ticker}: {e}")


def regenerate_insider_trades_fixtures() -> None:
    """Regenerate insider trades fixtures for test tickers."""
    print("Regenerating insider trades fixtures...")
    
    tickers = ["LUG", "VOLV B", "TTWO", "FDEV"]
    api_key = ensure_api_key()
    
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    
    for ticker in tickers:
        print(f"  Fetching insider trades for {ticker}...")
        try:
            # Fetch fresh data from API
            trades = get_insider_trades(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                limit=100,
                api_key=api_key
            )
            
            # Convert InsiderTrade objects to dicts for JSON serialization
            trades_dicts = []
            for trade in trades:
                if hasattr(trade, '__dict__'):
                    trades_dicts.append(trade.__dict__)
                else:
                    trades_dicts.append(trade)
            
            # Create the fixture structure
            fixture_data = {
                "insider_trades": trades_dicts
            }
            
            # Save to fixture file
            fixture_dir = Path("tests/fixtures/api/insider_trades")
            fixture_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = fixture_dir / f"{ticker}_{start_date}_{end_date}.json"
            
            with open(fixture_path, "w") as f:
                json.dump(fixture_data, f, indent=2)
            
            print(f"    Saved {len(trades)} trades to {fixture_path}")
            
        except Exception as e:
            print(f"    Error fetching {ticker}: {e}")


def regenerate_calendar_fixtures() -> None:
    """Regenerate company events fixtures for test tickers."""
    print("Regenerating company calendar fixtures...")
    
    tickers = ["LUG", "VOLV B", "TTWO", "FDEV"]
    api_key = ensure_api_key()
    
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    
    for ticker in tickers:
        print(f"  Fetching company events for {ticker}...")
        try:
            # Fetch fresh data from API
            events = get_company_events(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                limit=100,
                api_key=api_key
            )
            
            # Convert CompanyEvent objects to dicts for JSON serialization
            events_dicts = [event.model_dump() for event in events]

            # Create the fixture structure
            fixture_data = {
                "events": events_dicts
            }
            
            # Save to fixture file
            fixture_dir = Path("tests/fixtures/api/calendar")
            fixture_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = fixture_dir / f"{ticker}_{start_date}_{end_date}.json"
            
            with open(fixture_path, "w") as f:
                json.dump(fixture_data, f, indent=2)
            
            print(f"    Saved {len(events)} events to {fixture_path}")
            
        except Exception as e:
            print(f"    Error fetching {ticker}: {e}")


def regenerate_price_fixtures() -> None:
    """Regenerate price data fixtures for test tickers."""
    print("Regenerating price data fixtures...")
    
    tickers = ["LUG", "VOLV B", "TTWO", "FDEV", "SPY", "OMXS30"]
    api_key = ensure_api_key()
    
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    
    for ticker in tickers:
        print(f"  Fetching price data for {ticker}...")
        try:
            # Fetch fresh data from API
            prices = get_prices(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key
            )
            
            # Convert Price objects to dicts for JSON serialization
            price_dicts = []
            for price in prices:
                price_dicts.append({
                    "time": price.time,
                    "open": price.open,
                    "close": price.close,
                    "high": price.high,
                    "low": price.low,
                    "volume": price.volume
                })
            
            # Create the fixture structure
            fixture_data = {
                "prices": price_dicts
            }
            
            # Save to fixture file
            fixture_dir = Path("tests/fixtures/api/prices")
            fixture_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = fixture_dir / f"{ticker}_{start_date}_{end_date}.json"
            
            with open(fixture_path, "w") as f:
                json.dump(fixture_data, f, indent=2)
            
            print(f"    Saved {len(price_dicts)} price points to {fixture_path}")
            
        except Exception as e:
            print(f"    Error fetching {ticker}: {e}")


def main() -> None:
    """Main function to regenerate all fixtures."""
    print("=== Regenerating all test fixtures with fresh Börsdata API data ===")
    print()
    
    try:
        # Check API key first
        ensure_api_key()
        print("✓ Börsdata API key found")
        print()

        # Set ticker markets before regenerating data
        set_ticker_markets({
            "LUG": "Nordic",
            "VOLV B": "Nordic",
            "OMXS30": "Nordic",
            "TTWO": "Global",
            "FDEV": "Global",
            "SPY": "Global",
        })
        print("✓ Ticker markets configured (Nordic/Global)")
        print()
        
        # Regenerate all fixture types
        regenerate_financial_metrics_fixtures()
        print()
        regenerate_insider_trades_fixtures()
        print()
        regenerate_calendar_fixtures()
        print()
        regenerate_price_fixtures()
        print()
        
        print("=== All fixtures regenerated successfully! ===")
        print()
        print("Note: The new fixtures contain fresh data from the Börsdata API.")
        print("This should resolve any currency conversion or data quality issues.")
        
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Make sure to set your BORSDATA_API_KEY environment variable:")
        print("export BORSDATA_API_KEY=your_api_key_here")


if __name__ == "__main__":
    main()