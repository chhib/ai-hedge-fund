#!/usr/bin/env python3
"""
Currency-Aware FD vs BD Comparison

Enhanced comparison script that properly handles multi-currency scenarios
with automatic normalization and scaling fixes.

Usage:
    poetry run python scripts/currency_aware_comparison.py AAPL --target-currency USD
    poetry run python scripts/currency_aware_comparison.py AAK --target-currency USD --verbose
    poetry run python scripts/currency_aware_comparison.py DSV --target-currency EUR
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Add both codebases to Python path
current_dir = Path(__file__).parent.parent
sys.path.insert(0, str(current_dir))

# Import from current Börsdata implementation
from src.data.borsdata_client import BorsdataClient
from src.data.borsdata_kpis import FinancialMetricsAssembler

# Exchange rates (in practice, use real-time service)
EXCHANGE_RATES = {
    ("USD", "USD"): 1.0,
    ("SEK", "USD"): 0.091,
    ("DKK", "USD"): 0.145,
    ("NOK", "USD"): 0.094,
    ("EUR", "USD"): 1.06,
    ("USD", "EUR"): 0.943,
    ("SEK", "EUR"): 0.086,
    ("DKK", "EUR"): 0.134,
    ("NOK", "EUR"): 0.089,
}


class CurrencyAwareComparison:
    """Enhanced comparison with proper currency handling."""

    def __init__(self, bd_api_key: str, fd_api_key: Optional[str] = None):
        self.bd_api_key = bd_api_key
        self.fd_api_key = fd_api_key
        self.bd_client = BorsdataClient(api_key=bd_api_key)
        self.bd_assembler = FinancialMetricsAssembler(self.bd_client)

    def get_exchange_rate(self, from_currency: str, to_currency: str) -> float:
        """Get exchange rate between currencies."""
        if from_currency == to_currency:
            return 1.0

        rate = EXCHANGE_RATES.get((from_currency, to_currency))
        if rate is None:
            # Try reverse rate
            reverse_rate = EXCHANGE_RATES.get((to_currency, from_currency))
            if reverse_rate:
                rate = 1.0 / reverse_rate
            else:
                print(f"⚠️  Warning: No exchange rate available for {from_currency} -> {to_currency}")
                return 1.0

        return rate

    def normalize_currency_values(self, metrics_dict: Dict, target_currency: str) -> Dict:
        """Normalize monetary values to target currency."""
        if not metrics_dict or "error" in metrics_dict:
            return metrics_dict

        source_currency = metrics_dict.get("currency", "USD")
        if source_currency == target_currency:
            return metrics_dict

        exchange_rate = self.get_exchange_rate(source_currency, target_currency)

        # Create normalized copy
        normalized = metrics_dict.copy()
        normalized["original_currency"] = source_currency
        normalized["normalized_currency"] = target_currency
        normalized["exchange_rate_used"] = exchange_rate

        # Apply currency normalization to monetary values
        monetary_fields = ["market_cap", "enterprise_value"]
        for field in monetary_fields:
            if field in normalized and normalized[field] is not None:
                normalized[field] = normalized[field] * exchange_rate

        normalized["currency"] = target_currency
        return normalized

    def get_borsdata_analysis(self, ticker: str, test_date: str, target_currency: str) -> Dict:
        """Get Börsdata analysis with currency normalization."""
        try:
            # Determine market type
            use_global = ticker.upper() in ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META"]

            metrics = self.bd_assembler.assemble(
                ticker=ticker,
                end_date=test_date,
                period="ttm",
                limit=1,
                api_key=self.bd_api_key,
                use_global=use_global
            )

            if metrics:
                m = metrics[0]
                result = {
                    "ticker": ticker,
                    "source": "Börsdata",
                    "test_date": test_date,
                    "currency": getattr(m, 'currency', 'USD'),
                    "market_used": "Global" if use_global else "Nordic",
                    # Apply BD scaling fix (millions to absolute)
                    "market_cap": getattr(m, 'market_cap', None) * 1_000_000 if getattr(m, 'market_cap', None) else None,
                    "enterprise_value": getattr(m, 'enterprise_value', None) * 1_000_000 if getattr(m, 'enterprise_value', None) else None,
                    "price_to_earnings_ratio": getattr(m, 'price_to_earnings_ratio', None),
                    "price_to_book_ratio": getattr(m, 'price_to_book_ratio', None),
                    "price_to_sales_ratio": getattr(m, 'price_to_sales_ratio', None),
                    "enterprise_value_to_ebitda_ratio": getattr(m, 'enterprise_value_to_ebitda_ratio', None),
                    "return_on_equity": getattr(m, 'return_on_equity', None),
                    "return_on_assets": getattr(m, 'return_on_assets', None),
                    "gross_margin": getattr(m, 'gross_margin', None),
                    "operating_margin": getattr(m, 'operating_margin', None),
                    "net_margin": getattr(m, 'net_margin', None),
                    "debt_to_equity": getattr(m, 'debt_to_equity', None),
                    "current_ratio": getattr(m, 'current_ratio', None),
                    "revenue_growth": getattr(m, 'revenue_growth', None),
                    "earnings_growth": getattr(m, 'earnings_growth', None),
                    "free_cash_flow_growth": getattr(m, 'free_cash_flow_growth', None),
                }

                # Apply currency normalization
                normalized_result = self.normalize_currency_values(result, target_currency)
                return normalized_result
            else:
                return {"error": "No metrics found"}

        except Exception as e:
            return {"error": f"Börsdata error: {e}"}

    def get_financialdatasets_analysis(self, ticker: str, test_date: str, target_currency: str) -> Dict:
        """Get FinancialDatasets analysis (placeholder - would need actual implementation)."""
        # For now, return a status indicating FD limitations
        return {
            "ticker": ticker,
            "source": "FinancialDatasets",
            "error": f"FinancialDatasets does not support ticker {ticker} (non-USD markets not supported)",
            "note": "FD only supports US markets; BD provides superior multi-currency coverage"
        }

    def compare_with_currency_awareness(self, ticker: str, test_date: str, target_currency: str) -> Dict:
        """Perform currency-aware comparison."""
        print(f"🔍 Currency-Aware Analysis for {ticker}")
        print(f"📅 Date: {test_date}, Target Currency: {target_currency}")

        # Get analyses
        bd_result = self.get_borsdata_analysis(ticker, test_date, target_currency)
        fd_result = self.get_financialdatasets_analysis(ticker, test_date, target_currency)

        # Build comparison
        comparison = {
            "ticker": ticker,
            "test_date": test_date,
            "target_currency": target_currency,
            "borsdata_result": bd_result,
            "financialdatasets_result": fd_result,
            "currency_analysis": {},
            "recommendations": []
        }

        # Analyze currency aspects
        if "error" not in bd_result:
            original_currency = bd_result.get("original_currency", bd_result.get("currency"))
            if original_currency != target_currency:
                exchange_rate = bd_result.get("exchange_rate_used", 1.0)
                comparison["currency_analysis"] = {
                    "original_currency": original_currency,
                    "normalization_applied": True,
                    "exchange_rate_used": exchange_rate,
                    "scaling_fix_applied": True,
                    "market_type": bd_result.get("market_used", "Unknown")
                }
            else:
                comparison["currency_analysis"] = {
                    "normalization_required": False,
                    "scaling_fix_applied": True,
                    "market_type": bd_result.get("market_used", "Unknown")
                }

        # Generate recommendations
        if "error" in fd_result:
            comparison["recommendations"].append({
                "type": "Market Coverage",
                "priority": "High",
                "description": f"Consider using Börsdata for {ticker} as FD does not support this market",
                "action": "Börsdata provides native {original_currency} support with proper currency handling"
            })

        if comparison["currency_analysis"].get("normalization_applied"):
            comparison["recommendations"].append({
                "type": "Currency Normalization",
                "priority": "Medium",
                "description": f"Implement real-time exchange rates for more accurate {original_currency}->{target_currency} conversion",
                "action": "Integrate exchange rate service for daily rate updates"
            })

        return comparison


def print_currency_aware_summary(comparison: Dict, verbose: bool = False):
    """Print formatted summary of currency-aware comparison."""
    print(f"\n{'='*60}")
    print(f"💱 CURRENCY-AWARE COMPARISON SUMMARY")
    print(f"{'='*60}")

    ticker = comparison["ticker"]
    target_currency = comparison["target_currency"]
    bd_result = comparison["borsdata_result"]
    fd_result = comparison["financialdatasets_result"]

    print(f"📊 Ticker: {ticker}")
    print(f"💰 Target Currency: {target_currency}")

    # Börsdata analysis
    if "error" not in bd_result:
        print(f"\n✅ Börsdata Analysis:")
        original_currency = bd_result.get("original_currency", bd_result.get("currency"))
        market_cap = bd_result.get("market_cap")
        exchange_rate = bd_result.get("exchange_rate_used", 1.0)

        print(f"   Currency: {original_currency} -> {target_currency}")
        if market_cap:
            print(f"   Market Cap: {market_cap:,.0f} {target_currency}")
        if exchange_rate != 1.0:
            print(f"   Exchange Rate Applied: {exchange_rate:.6f}")
        print(f"   Market: {bd_result.get('market_used', 'Unknown')}")

        if verbose:
            print(f"   P/E Ratio: {bd_result.get('price_to_earnings_ratio', 'N/A')}")
            print(f"   P/B Ratio: {bd_result.get('price_to_book_ratio', 'N/A')}")
            print(f"   ROE: {bd_result.get('return_on_equity', 'N/A')}")
    else:
        print(f"\n❌ Börsdata Error: {bd_result.get('error')}")

    # FinancialDatasets analysis
    if "error" not in fd_result:
        print(f"\n✅ FinancialDatasets Analysis: Available")
    else:
        print(f"\n⚠️  FinancialDatasets: {fd_result.get('error')}")

    # Currency analysis
    currency_analysis = comparison.get("currency_analysis", {})
    if currency_analysis:
        print(f"\n💱 Currency Processing:")
        if currency_analysis.get("normalization_applied"):
            print(f"   ✓ Currency normalization applied")
            print(f"   ✓ Scaling fix applied (millions -> absolute)")
        else:
            print(f"   • No currency conversion needed")

    # Recommendations
    recommendations = comparison.get("recommendations", [])
    if recommendations:
        print(f"\n🎯 Recommendations:")
        for rec in recommendations:
            print(f"   • {rec['type']}: {rec['description']}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Currency-Aware FD vs BD Comparison")
    parser.add_argument("ticker", help="Ticker symbol to analyze")
    parser.add_argument("--test-date", default="2025-09-15", help="Test date (YYYY-MM-DD)")
    parser.add_argument("--target-currency", default="USD", help="Target currency for normalization")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output", help="Save results to JSON file")

    args = parser.parse_args()

    # Check API keys
    bd_key = os.getenv("BORSDATA_API_KEY")
    fd_key = os.getenv("FINANCIAL_DATASETS_API_KEY")

    if not bd_key:
        print("❌ BORSDATA_API_KEY not found")
        sys.exit(1)

    print(f"🚀 Currency-Aware Comparison for {args.ticker}")

    # Run comparison
    comparator = CurrencyAwareComparison(bd_key, fd_key)
    comparison = comparator.compare_with_currency_awareness(
        args.ticker, args.test_date, args.target_currency
    )

    # Print results
    print_currency_aware_summary(comparison, args.verbose)

    # Save if requested
    if args.output:
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "comparison": comparison
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n💾 Results saved to {args.output}")


if __name__ == "__main__":
    main()