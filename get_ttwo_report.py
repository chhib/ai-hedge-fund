import os
import sys
from datetime import datetime, timedelta

api_key = "b059f5e0450d4e5db9f9b65410b8de46"
os.environ["BORSDATA_API_KEY"] = api_key

sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.tools.api import set_ticker_markets, get_prices
from src.data.borsdata_reports import LineItemAssembler
from src.data.borsdata_client import BorsdataClient

if __name__ == "__main__":
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    set_ticker_markets({"TTWO": "Global"})

    print("Fetching report data for TTWO...")
    client = BorsdataClient()
    line_item_assembler = LineItemAssembler(client)
    
    report_data = line_item_assembler.assemble("TTWO", ["operating_income", "net_debt", "revenue", "outstanding_shares"], end_date=end_date, period="ttm", limit=1, api_key=api_key, use_global=True)
    print(report_data)

    print("\nFetching prices for TTWO...")
    prices = get_prices("TTWO", start_date=start_date, end_date=end_date, api_key=api_key)
    print(prices)