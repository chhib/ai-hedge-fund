#!/usr/bin/env python3
"""Debug script to extract ALL available KPIs from both Nordic and Global tickers."""

import sys
from dotenv import load_dotenv
from src.tools.api import get_financial_metrics
from src.data.borsdata_metrics_mapping import FINANCIAL_METRICS_MAPPING
import json

# Load environment variables
load_dotenv()

def extract_all_kpis(ticker, use_global=False):
    """Extract all available financial metrics for a ticker."""
    print(f"\n{'='*60}")
    print(f"EXTRACTING ALL KPIs for {ticker} ({'Global' if use_global else 'Nordic'})")
    print(f"{'='*60}")
    
    try:
        # Import the set_ticker_markets function
        from src.tools.api import set_ticker_markets
        
        # Set the ticker market type for API calls  
        if use_global:
            ticker_markets = {ticker: "Global"}
        else:
            ticker_markets = {ticker: "Nordic"}
        
        set_ticker_markets(ticker_markets)
            
        # Get financial metrics with correct API signature
        metrics_list = get_financial_metrics(
            ticker,
            end_date="2024-12-31",
            period="ttm",
            limit=5
        )
        
        if not metrics_list:
            print(f"❌ No financial metrics found for {ticker}")
            return {}
            
        # Get the most recent metrics
        latest_metrics = metrics_list[0]
        
        print(f"\n📊 Found {len(metrics_list)} financial periods")
        print(f"📅 Latest period: {latest_metrics.report_period}")
        print(f"💱 Currency: {latest_metrics.currency}")
        
        # Extract all non-None metrics
        all_kpis = {}
        print(f"\n🔍 AVAILABLE KPIs:")
        print(f"{'KPI Name':<35} {'Value':<20} {'Mapped?':<8} {'Percentage?':<12}")
        print("-" * 80)
        
        # Get all attributes from the FinancialMetrics object
        for attr_name in dir(latest_metrics):
            if not attr_name.startswith('_') and not callable(getattr(latest_metrics, attr_name)):
                value = getattr(latest_metrics, attr_name)
                if value is not None and attr_name not in ['ticker', 'report_period', 'period', 'currency']:
                    # Check if this metric is in our mapping
                    is_mapped = attr_name in FINANCIAL_METRICS_MAPPING
                    is_percentage = FINANCIAL_METRICS_MAPPING.get(attr_name, {}).get('is_percentage', False)
                    
                    # Format value for display
                    if isinstance(value, float):
                        if abs(value) > 1000:
                            value_str = f"{value:,.2f}"
                        elif abs(value) > 1:
                            value_str = f"{value:.2f}"
                        else:
                            value_str = f"{value:.4f}"
                    else:
                        value_str = str(value)
                    
                    mapped_str = "✅" if is_mapped else "❌"
                    percentage_str = "📊" if is_percentage else ""
                    
                    print(f"{attr_name:<35} {value_str:<20} {mapped_str:<8} {percentage_str:<12}")
                    all_kpis[attr_name] = value
        
        print(f"\n📈 Total KPIs extracted: {len(all_kpis)}")
        
        # Check for suspicious percentage values (>1000% might indicate inflation)
        suspicious_metrics = []
        for name, value in all_kpis.items():
            if isinstance(value, (int, float)) and abs(value) > 10.0:  # >1000%
                # Check if this looks like a percentage metric
                if any(keyword in name.lower() for keyword in ['margin', 'growth', 'return', 'ratio', 'yield']):
                    if name not in FINANCIAL_METRICS_MAPPING or not FINANCIAL_METRICS_MAPPING.get(name, {}).get('is_percentage', False):
                        suspicious_metrics.append((name, value))
        
        if suspicious_metrics:
            print(f"\n⚠️  SUSPICIOUS VALUES (might need percentage conversion):")
            for name, value in suspicious_metrics:
                print(f"   {name}: {value}")
        
        return all_kpis
        
    except Exception as e:
        print(f"❌ Error extracting KPIs for {ticker}: {e}")
        return {}

def main():
    print("🔍 COMPREHENSIVE KPI EXTRACTION AND VALIDATION")
    print("=" * 60)
    
    # Extract Nordic KPIs (ATCO B)
    nordic_kpis = extract_all_kpis("ATCO B", use_global=False)
    
    # Extract Global KPIs (AAPL)  
    global_kpis = extract_all_kpis("AAPL", use_global=True)
    
    # Create summary comparison
    print(f"\n{'='*60}")
    print("SUMMARY COMPARISON")
    print(f"{'='*60}")
    
    print(f"Nordic KPIs (ATCO B): {len(nordic_kpis)} metrics")
    print(f"Global KPIs (AAPL): {len(global_kpis)} metrics")
    
    # Find common and unique metrics
    nordic_set = set(nordic_kpis.keys())
    global_set = set(global_kpis.keys())
    
    common_metrics = nordic_set & global_set
    nordic_only = nordic_set - global_set
    global_only = global_set - nordic_set
    
    print(f"\nCommon metrics: {len(common_metrics)}")
    print(f"Nordic-only metrics: {len(nordic_only)}")
    print(f"Global-only metrics: {len(global_only)}")
    
    if nordic_only:
        print(f"\n📍 Nordic-only metrics:")
        for metric in sorted(nordic_only):
            print(f"   {metric}: {nordic_kpis[metric]}")
    
    if global_only:
        print(f"\n🌍 Global-only metrics:")
        for metric in sorted(global_only):
            print(f"   {metric}: {global_kpis[metric]}")
    
    # Save detailed results to JSON for further analysis
    results = {
        "nordic_kpis": nordic_kpis,
        "global_kpis": global_kpis,
        "summary": {
            "nordic_count": len(nordic_kpis),
            "global_count": len(global_kpis),
            "common_count": len(common_metrics),
            "nordic_only_count": len(nordic_only),
            "global_only_count": len(global_only)
        }
    }
    
    with open("/Users/ksu541/Code/ai-hedge-fund/kpi_extraction_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n💾 Detailed results saved to: kpi_extraction_results.json")

if __name__ == "__main__":
    main()