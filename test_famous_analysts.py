#!/usr/bin/env python3
"""
Test script for running famous investor personality analysts on AAPL
"""

import os
import sys
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, 'src')

from agents.warren_buffett import WarrenBuffettAgent
from agents.stanley_druckenmiller import StanleyDruckenMillerAgent  
from agents.charlie_munger import CharlieMungerAgent
from agents.fundamentals import FundamentalsAnalyst
from data.borsdata_client import BorsdataClient
from data.borsdata_kpis import FinancialMetricsAssembler

def test_famous_analysts():
    """Test AAPL with famous investor personalities"""
    
    # Setup
    api_key = os.getenv('BORSDATA_API_KEY')
    ticker = 'AAPL'
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    print(f"Testing {ticker} with famous investor personalities")
    print(f"Period: {start_date} to {end_date}")
    print("=" * 60)
    
    # Get financial data
    client = BorsdataClient()
    assembler = FinancialMetricsAssembler(client)
    
    try:
        # Get financial metrics using enhanced KPI system
        metrics = assembler.assemble(
            ticker,
            end_date=None,
            period='ttm',
            limit=1,
            api_key=api_key,
            use_global=True
        )
        
        if not metrics:
            print(f"No financial metrics found for {ticker}")
            return
            
        financial_data = metrics[0]
        print(f"✓ Retrieved financial data: {sum(1 for k, v in financial_data.model_dump().items() if v is not None)} metrics")
        
        # Get price data
        instrument = client.get_instrument(ticker, api_key=api_key, use_global=True)
        instrument_id = int(instrument['insId'])
        prices = client.get_stock_prices(instrument_id, original_currency=True, api_key=api_key)
        
        if not prices:
            print(f"No price data found for {ticker}")
            return
            
        print(f"✓ Retrieved price data: {len(prices)} data points")
        print()
        
        # Test with famous analysts
        analysts = [
            ("Warren Buffett", WarrenBuffettAgent()),
            ("Stanley Druckenmiller", StanleyDruckenMillerAgent()),
            ("Charlie Munger", CharlieMungerAgent()),
            ("Fundamentals Analyst", FundamentalsAnalyst())
        ]
        
        results = []
        
        for name, agent in analysts:
            try:
                print(f"🧠 Analyzing with {name}...")
                
                # Create context for the agent
                context = {
                    'ticker': ticker,
                    'financial_data': financial_data,
                    'price_data': prices,
                    'start_date': start_date,
                    'end_date': end_date
                }
                
                # Run analysis
                signal = agent.analyze(context)
                
                action = signal.signal or "NEUTRAL"
                confidence = signal.confidence or 0.0
                reasoning = signal.reasoning if isinstance(signal.reasoning, str) else str(signal.reasoning)[:100] + "..."
                
                results.append((name, action, confidence, reasoning))
                print(f"   Signal: {action} ({confidence:.1f}% confidence)")
                
            except Exception as e:
                print(f"   Error: {e}")
                results.append((name, "ERROR", 0.0, str(e)))
        
        print()
        print("=" * 60)
        print("ANALYST SUMMARY")
        print("=" * 60)
        
        for name, action, confidence, reasoning in results:
            print(f"{name:20} | {action:8} | {confidence:6.1f}% | {reasoning[:50]}...")
            
        # Show key financial metrics used
        print()
        print("KEY FINANCIAL METRICS:")
        key_metrics = ['market_cap', 'price_to_earnings_ratio', 'return_on_equity', 
                      'debt_to_equity', 'dividend_yield', 'revenue_growth', 'earnings_growth']
        for metric in key_metrics:
            value = getattr(financial_data, metric, None)
            if value is not None:
                print(f"  {metric}: {value:.2f}")
        
    except Exception as e:
        print(f"Error in analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_famous_analysts()