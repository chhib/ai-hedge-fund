import os
import sys
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from tools.api import get_financial_metrics, set_ticker_markets

if __name__ == "__main__":
    api_key = "b059f5e0450d4e5db9f9b65410b8de46"
    end_date = datetime.now().strftime("%Y-%m-%d")

    # Set the market for the tickers
    set_ticker_markets({"LUG": "Nordic", "TTWO": "Global"})

    print("Fetching metrics for LUG...")
    lug_metrics = get_financial_metrics("LUG", end_date=end_date, api_key=api_key)
    print(lug_metrics)

    print("\nFetching metrics for TTWO...")
    ttwo_metrics = get_financial_metrics("TTWO", end_date=end_date, api_key=api_key)
    print(ttwo_metrics)
