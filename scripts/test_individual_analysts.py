#!/usr/bin/env python3
"""
Test individual analysts to identify which ones are failing and why.
This script tests each analyst separately with the same 4 tickers from the test output.
"""

import os
import sys
import json
import traceback
import time
from datetime import datetime
from typing import Dict, Any

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
from src.graph.state import AgentState
from src.utils.analysts import ANALYST_CONFIG
from src.utils.api_key import get_api_key_from_state
from src.tools.api import set_ticker_markets
from src.utils.progress import progress

# Load environment variables
load_dotenv()

# Enhanced logging for data fetching
def log_data_fetch(operation: str, ticker: str = "", details: str = ""):
    """Log data fetching operations with details."""
    if ticker:
        print(f"     🔍 {ticker}: {operation} - {details}")
    else:
        print(f"     🔍 {operation} - {details}")

def log_cache_status():
    """Log current cache status."""
    from src.data.cache import get_cache
    cache = get_cache()

    metrics_count = len(cache._financial_metrics_cache)
    line_items_count = len(cache._line_items_cache)
    prices_count = len(cache._prices_cache)

    print(f"     💾 Cache status: {metrics_count} metrics, {line_items_count} line items, {prices_count} prices cached")

# Monkey patch to add logging to key functions
original_get_financial_metrics = None
original_search_line_items = None
original_get_market_cap = None

def patch_api_logging():
    """Add logging to API functions."""
    global original_get_financial_metrics, original_search_line_items, original_get_market_cap

    from src.tools import api

    # Store original functions
    original_get_financial_metrics = api.get_financial_metrics
    original_search_line_items = api.search_line_items
    original_get_market_cap = api.get_market_cap

    def logged_get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=None):
        log_data_fetch("Financial Metrics", ticker, f"period={period}, limit={limit}")
        result = original_get_financial_metrics(ticker, end_date, period, limit, api_key)
        if result:
            metrics_count = len(result)
            # Use proper Pydantic V2 approach to get model fields from class
            try:
                # Access model fields from the class, not the instance
                model_class = type(result[0])
                if hasattr(model_class, 'model_fields'):
                    # Get non-null fields from the first result
                    sample_metrics = []
                    for field_name in list(model_class.model_fields.keys())[:10]:  # First 10 fields
                        if hasattr(result[0], field_name) and getattr(result[0], field_name) is not None:
                            sample_metrics.append(field_name)
                    sample_metrics = sample_metrics[:5]  # Show first 5 non-null
                else:
                    sample_metrics = ["unknown_model_type"]
            except Exception:
                # Fallback if model introspection fails
                sample_metrics = ["model_introspection_failed"]
            log_data_fetch("Metrics Retrieved", ticker, f"{metrics_count} periods, sample: {sample_metrics}")
        return result

    def logged_search_line_items(ticker, line_items, end_date, period="annual", limit=5, api_key=None):
        log_data_fetch("Line Items", ticker, f"{len(line_items)} items: {line_items}")
        result = original_search_line_items(ticker, line_items, end_date, period, limit, api_key)
        if result:
            available_items = []
            for item in result:
                for field in line_items:
                    if hasattr(item, field) and getattr(item, field) is not None:
                        available_items.append(field)
            log_data_fetch("Line Items Found", ticker, f"{len(set(available_items))} available: {list(set(available_items))[:5]}")
        return result

    def logged_get_market_cap(ticker, end_date, api_key=None):
        log_data_fetch("Market Cap", ticker, "")
        result = original_get_market_cap(ticker, end_date, api_key)
        if result:
            log_data_fetch("Market Cap Retrieved", ticker, f"${result:,.0f}")
        return result

    # Replace with logged versions
    api.get_financial_metrics = logged_get_financial_metrics
    api.search_line_items = logged_search_line_items
    api.get_market_cap = logged_get_market_cap

def restore_api_logging():
    """Restore original API functions."""
    if original_get_financial_metrics:
        from src.tools import api
        api.get_financial_metrics = original_get_financial_metrics
        api.search_line_items = original_search_line_items
        api.get_market_cap = original_get_market_cap

# Test configuration matching the failed test
TEST_TICKERS = ["INVE B", "8TRA", "MAU", "VOW"]
END_DATE = "2025-09-15"
MODEL = "gpt-5-mini"

# Ticker market classification (Global tickers need use_global=True)
TICKER_MARKETS = {
    "INVE B": "Nordic",
    "8TRA": "Nordic",
    "MAU": "Global",
    "VOW": "Global"
}

# Progress tracking
data_fetch_log = []

def progress_handler(agent_name: str, ticker: str = None, status: str = "", analysis: str = None, timestamp: str = None):
    """Custom progress handler to capture data fetching details."""
    if ticker and status:
        # Log data fetching activities
        if "Fetching" in status or "Getting" in status or "Gathering" in status:
            log_entry = f"   📡 {ticker}: {status}"
            print(log_entry)
            data_fetch_log.append(log_entry)
        elif "Error" in status:
            error_entry = f"   ⚠️  {ticker}: {status}"
            print(error_entry)
            data_fetch_log.append(error_entry)
        elif "Done" in status:
            done_entry = f"   ✅ {ticker}: {status}"
            print(done_entry)
            data_fetch_log.append(done_entry)

def create_test_state(tickers: list[str]) -> AgentState:
    """Create a test state for analyst testing."""
    return {
        "messages": [],
        "data": {
            "tickers": tickers,
            "start_date": "2025-09-01",
            "end_date": END_DATE,
            "current_prices": {},
            "portfolio": {},
            "analyst_signals": {}
        },
        "metadata": {
            "model": MODEL,
            "model_name": MODEL,
            "model_provider": "OpenAI",
            "show_reasoning": False
        },
        "api_keys": {
            "BORSDATA_API_KEY": os.environ.get("BORSDATA_API_KEY"),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY")
        }
    }

def test_single_analyst(analyst_key: str, analyst_config: Dict[str, Any], tickers: list[str], current: int, total: int) -> Dict[str, Any]:
    """Test a single analyst with the given tickers."""
    print(f"\n{'='*60}")
    print(f"Testing [{current}/{total}]: {analyst_config['display_name']} ({analyst_key})")
    print(f"{'='*60}")

    # Estimate remaining time
    if current > 1:
        avg_time_per_analyst = 45  # seconds estimate
        remaining_analysts = total - current
        estimated_minutes = (remaining_analysts * avg_time_per_analyst) / 60
        print(f"   📊 Progress: {current-1} completed, {remaining_analysts} remaining (~{estimated_minutes:.1f} min left)")

    result = {
        "analyst": analyst_key,
        "display_name": analyst_config["display_name"],
        "success": False,
        "error": None,
        "output": None,
        "tickers_processed": 0
    }

    try:
        # Create test state
        state = create_test_state(tickers)

        # Get the agent function
        agent_func = analyst_config["agent_func"]
        agent_id = f"{analyst_key}_agent"

        print(f"Running {agent_func.__name__} with tickers: {tickers}")

        # Add progress indicators
        print(f"   🔄 Initializing agent...")

        # Register progress handler to capture data fetching
        progress.register_handler(progress_handler)

        # Enable detailed API logging
        patch_api_logging()

        # Clear previous data fetch log
        global data_fetch_log
        data_fetch_log = []

        # Call the agent with progress tracking
        try:
            print(f"   🔄 Starting analysis (this may take 30-60 seconds)...")
            print(f"   📊 Data fetching details:")

            # Show cache status before
            log_cache_status()

            start_time = time.time()
            output = agent_func(state, agent_id)
            elapsed_time = time.time() - start_time
            print(f"   ⏱️  Analysis completed in {elapsed_time:.1f} seconds!")

            # Show cache status after
            log_cache_status()

            # Show data fetch summary
            if data_fetch_log:
                unique_activities = set([entry.split(": ")[1] if ": " in entry else entry for entry in data_fetch_log])
                print(f"   📈 Data activities: {len(unique_activities)} unique operations")

        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"   ❌ Analysis failed after {elapsed_time:.1f} seconds: {str(e)[:100]}...")
            raise
        finally:
            # Cleanup
            progress.unregister_handler(progress_handler)
            restore_api_logging()

        if output:
            result["success"] = True
            result["output"] = output
            result["tickers_processed"] = len(tickers)
            print(f"✅ SUCCESS: {analyst_config['display_name']}")

            # Show sample output
            if isinstance(output, dict):
                for ticker, analysis in list(output.items())[:2]:  # Show first 2 tickers
                    if isinstance(analysis, dict):
                        signal = analysis.get("signal", "unknown")
                        confidence = analysis.get("confidence", 0)
                        print(f"   {ticker}: {signal} ({confidence}% confidence)")
                    else:
                        print(f"   {ticker}: {type(analysis).__name__} (unexpected format)")
            elif isinstance(output, list):
                print(f"   Output: list with {len(output)} items")
                if output and isinstance(output[0], dict):
                    first_item = output[0]
                    print(f"   First item keys: {list(first_item.keys())}")
            else:
                print(f"   Output type: {type(output).__name__}")
        else:
            result["error"] = "Agent returned None/empty output"
            print(f"❌ FAILED: {analyst_config['display_name']} - No output")

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        result["success"] = False
        print(f"❌ ERROR: {analyst_config['display_name']}")
        print(f"   Error: {str(e)}")

        # Print first few lines of traceback for debugging
        tb_lines = traceback.format_exc().split('\n')
        print("   Traceback (last 3 lines):")
        for line in tb_lines[-4:-1]:  # Skip empty last line
            if line.strip():
                print(f"     {line}")

    return result

def main():
    """Test all analysts individually."""
    print("🚀 Starting Individual Analyst Testing")
    print(f"Model: {MODEL}")
    print(f"Tickers: {TEST_TICKERS}")
    print(f"End Date: {END_DATE}")

    # Set up ticker markets for proper global/Nordic routing
    set_ticker_markets(TICKER_MARKETS)
    print(f"Ticker markets: {TICKER_MARKETS}")

    # Check API key
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        print("❌ ERROR: BORSDATA_API_KEY not found in environment")
        return

    # Pre-fetch common data to populate cache (optional optimization)
    print("\n🔄 Pre-fetching common data to cache...")
    try:
        from src.tools.api import get_financial_metrics, get_market_cap
        for ticker in TEST_TICKERS:
            try:
                print(f"   📡 Pre-caching {ticker}...")
                # Most common parameters used by agents
                get_financial_metrics(ticker, END_DATE, period="annual", limit=10, api_key=api_key)
                get_market_cap(ticker, END_DATE, api_key=api_key)
            except Exception as e:
                print(f"   ⚠️  {ticker}: {str(e)[:50]}...")

        log_cache_status()
        print("✅ Pre-caching completed")
    except Exception as e:
        print(f"⚠️  Pre-caching failed: {str(e)[:100]}... (continuing anyway)")

    results = []
    successful_count = 0
    failed_count = 0

    # Test each analyst
    total_analysts = len(ANALYST_CONFIG)
    for i, (analyst_key, analyst_config) in enumerate(ANALYST_CONFIG.items(), 1):
        result = test_single_analyst(analyst_key, analyst_config, TEST_TICKERS, i, total_analysts)
        results.append(result)

        if result["success"]:
            successful_count += 1
        else:
            failed_count += 1

        # Show running summary
        print(f"   📊 Running tally: {successful_count} ✅ | {failed_count} ❌ | {total_analysts - i} remaining")

    # Summary
    print(f"\n{'='*60}")
    print("📊 SUMMARY")
    print(f"{'='*60}")
    print(f"Total analysts tested: {len(results)}")
    print(f"✅ Successful: {successful_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"Success rate: {successful_count/len(results)*100:.1f}%")

    # Show failed analysts
    if failed_count > 0:
        print(f"\n❌ FAILED ANALYSTS ({failed_count}):")
        for result in results:
            if not result["success"]:
                print(f"   • {result['display_name']} ({result['analyst']})")
                if result["error"]:
                    print(f"     Error: {result['error']}")

    # Show successful analysts
    if successful_count > 0:
        print(f"\n✅ SUCCESSFUL ANALYSTS ({successful_count}):")
        for result in results:
            if result["success"]:
                print(f"   • {result['display_name']} ({result['analyst']})")

    # Save detailed results
    output_file = "individual_analyst_test_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n💾 Detailed results saved to: {output_file}")

if __name__ == "__main__":
    main()