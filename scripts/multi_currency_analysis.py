#!/usr/bin/env python3
"""
Multi-Currency Analysis Script

This script analyzes how different currencies are handled across the system
and ensures proper normalization for cross-currency comparisons.

Usage:
    poetry run python scripts/multi_currency_analysis.py
    poetry run python scripts/multi_currency_analysis.py --normalize-to USD
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.borsdata_client import BorsdataClient
from src.data.borsdata_kpis import FinancialMetricsAssembler


# Sample tickers by currency for testing
CURRENCY_TICKERS = {
    "USD": ["AAPL", "MSFT", "NVDA"],  # US Global
    "SEK": ["AAK", "ASSA B", "ALFA"],  # Swedish
    "DKK": ["DSV", "NOVO B", "ORSTED"],  # Danish (if available)
    "NOK": ["EQNR", "DNB", "TEL"],  # Norwegian (if available)
    "EUR": ["ASML", "SAP", "ADYEN"]   # European (if available)
}

# Approximate exchange rates (for demonstration - in practice use real-time rates)
EXCHANGE_RATES_TO_USD = {
    "USD": 1.0,
    "SEK": 0.091,  # 1 SEK = ~0.091 USD
    "DKK": 0.145,  # 1 DKK = ~0.145 USD
    "NOK": 0.094,  # 1 NOK = ~0.094 USD
    "EUR": 1.06    # 1 EUR = ~1.06 USD
}


class MultiCurrencyAnalyzer:
    """Analyzes multi-currency financial data handling."""

    def __init__(self, api_key: str):
        self.client = BorsdataClient(api_key=api_key)
        self.assembler = FinancialMetricsAssembler(self.client)
        self.api_key = api_key

    def get_ticker_currency_info(self, ticker: str, use_global: bool = False) -> Optional[Dict]:
        """Get currency information for a ticker."""
        try:
            instrument = self.client.get_instrument(ticker, api_key=self.api_key, use_global=use_global)
            return {
                "ticker": ticker,
                "name": instrument.get("name", ""),
                "reportCurrency": instrument.get("reportCurrency", ""),
                "stockPriceCurrency": instrument.get("stockPriceCurrency", ""),
                "market": "Global" if use_global else "Nordic",
                "country": instrument.get("countryId", ""),
                "exchange": instrument.get("exchangeId", "")
            }
        except Exception as e:
            return {"ticker": ticker, "error": str(e)}

    def get_financial_metrics_with_currency(self, ticker: str, test_date: str = "2025-09-15") -> Optional[Dict]:
        """Get financial metrics and currency information."""
        try:
            # Try global first for known US tickers
            use_global = ticker in CURRENCY_TICKERS.get("USD", [])

            metrics = self.assembler.assemble(
                ticker=ticker,
                end_date=test_date,
                period="ttm",
                limit=1,
                api_key=self.api_key,
                use_global=use_global
            )

            if not metrics:
                # Try opposite market if not found
                use_global = not use_global
                metrics = self.assembler.assemble(
                    ticker=ticker,
                    end_date=test_date,
                    period="ttm",
                    limit=1,
                    api_key=self.api_key,
                    use_global=use_global
                )

            if metrics:
                m = metrics[0]
                return {
                    "ticker": ticker,
                    "currency": getattr(m, 'currency', None),
                    "market_used": "Global" if use_global else "Nordic",
                    "market_cap": getattr(m, 'market_cap', None),
                    "enterprise_value": getattr(m, 'enterprise_value', None),
                    "price_to_earnings_ratio": getattr(m, 'price_to_earnings_ratio', None),
                    "revenue": getattr(m, 'revenue', None),
                    "net_income": getattr(m, 'net_income', None)
                }
            else:
                return {"ticker": ticker, "error": "No metrics found"}

        except Exception as e:
            return {"ticker": ticker, "error": str(e)}

    def normalize_to_currency(self, value: Optional[float], from_currency: str, to_currency: str) -> Optional[float]:
        """Convert value from one currency to another."""
        if value is None or from_currency == to_currency:
            return value

        if from_currency not in EXCHANGE_RATES_TO_USD or to_currency not in EXCHANGE_RATES_TO_USD:
            print(f"⚠️  Warning: Exchange rate not available for {from_currency} -> {to_currency}")
            return value

        # Convert to USD first, then to target currency
        usd_value = value * EXCHANGE_RATES_TO_USD[from_currency]
        target_value = usd_value / EXCHANGE_RATES_TO_USD[to_currency]
        return target_value

    def analyze_currency_coverage(self) -> Dict:
        """Analyze what currencies are available in the system."""
        print("🌍 Analyzing Currency Coverage")
        print("=" * 50)

        results = {
            "timestamp": datetime.now().isoformat(),
            "currencies_found": {},
            "currency_analysis": {},
            "normalization_examples": {}
        }

        all_tickers = []
        for currency, tickers in CURRENCY_TICKERS.items():
            all_tickers.extend(tickers)

        for ticker in all_tickers:
            print(f"📊 Analyzing {ticker}...")

            # Get currency info
            currency_info = self.get_ticker_currency_info(ticker, use_global=ticker in CURRENCY_TICKERS.get("USD", []))
            if "error" not in currency_info:
                currency = currency_info.get("reportCurrency", "Unknown")
                if currency not in results["currencies_found"]:
                    results["currencies_found"][currency] = []
                results["currencies_found"][currency].append(ticker)

            # Get financial metrics
            metrics = self.get_financial_metrics_with_currency(ticker)
            if "error" not in metrics:
                currency = metrics.get("currency", "Unknown")
                market_cap = metrics.get("market_cap")

                if currency not in results["currency_analysis"]:
                    results["currency_analysis"][currency] = {
                        "tickers": [],
                        "market_caps": [],
                        "sample_data": {}
                    }

                results["currency_analysis"][currency]["tickers"].append(ticker)
                if market_cap:
                    results["currency_analysis"][currency]["market_caps"].append(market_cap)

                # Store sample data for first ticker in each currency
                if not results["currency_analysis"][currency]["sample_data"]:
                    results["currency_analysis"][currency]["sample_data"] = metrics

                print(f"   ✓ {ticker}: {currency}, Market Cap: {market_cap:,.1f}M {currency}")
            else:
                print(f"   ❌ {ticker}: {metrics.get('error')}")

        return results

    def demonstrate_currency_normalization(self, target_currency: str = "USD") -> Dict:
        """Demonstrate currency normalization across different markets."""
        print(f"\n💱 Currency Normalization to {target_currency}")
        print("=" * 50)

        normalization_results = {
            "target_currency": target_currency,
            "examples": []
        }

        # Test one ticker from each available currency
        test_tickers = {
            "USD": "AAPL",
            "SEK": "AAK"
        }

        for currency, ticker in test_tickers.items():
            metrics = self.get_financial_metrics_with_currency(ticker)
            if "error" not in metrics:
                original_market_cap = metrics.get("market_cap")
                source_currency = metrics.get("currency")

                if original_market_cap and source_currency:
                    # Apply our market cap scaling fix first (millions to absolute)
                    scaled_market_cap = original_market_cap * 1_000_000

                    # Then normalize currency
                    normalized_market_cap = self.normalize_to_currency(
                        scaled_market_cap, source_currency, target_currency
                    )

                    example = {
                        "ticker": ticker,
                        "source_currency": source_currency,
                        "original_value_millions": original_market_cap,
                        "scaled_absolute": scaled_market_cap,
                        "normalized_to_target": normalized_market_cap,
                        "exchange_rate_used": EXCHANGE_RATES_TO_USD.get(source_currency, "N/A")
                    }

                    normalization_results["examples"].append(example)

                    print(f"📈 {ticker} ({source_currency}):")
                    print(f"   Original: {original_market_cap:,.1f}M {source_currency}")
                    print(f"   Scaled: {scaled_market_cap:,.0f} {source_currency}")
                    print(f"   Normalized: {normalized_market_cap:,.0f} {target_currency}")

        return normalization_results


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Multi-Currency Analysis")
    parser.add_argument("--normalize-to", default="USD", help="Target currency for normalization")
    parser.add_argument("--output", default="multi_currency_analysis.json", help="Output file")

    args = parser.parse_args()

    # Get API key
    api_key = os.getenv("BORSDATA_API_KEY")
    if not api_key:
        print("❌ BORSDATA_API_KEY not found in environment")
        sys.exit(1)

    print("🚀 Multi-Currency Analysis")
    print(f"🎯 Target Currency: {args.normalize_to}")

    analyzer = MultiCurrencyAnalyzer(api_key)

    # Analyze currency coverage
    coverage_results = analyzer.analyze_currency_coverage()

    # Demonstrate normalization
    normalization_results = analyzer.demonstrate_currency_normalization(args.normalize_to)

    # Combine results
    final_results = {
        "analysis_timestamp": datetime.now().isoformat(),
        "target_normalization_currency": args.normalize_to,
        "currency_coverage": coverage_results,
        "normalization_demonstration": normalization_results,
        "recommendations": {
            "scaling_fix_needed": "Market cap values need 1M scaling factor from Börsdata millions",
            "currency_normalization": f"Implement real-time exchange rates for {args.normalize_to} normalization",
            "multi_currency_support": "System properly handles SEK, USD currencies; expand for DKK, NOK, EUR",
            "comparison_framework": "FD/BD comparisons should normalize to common currency before ratio calculations"
        }
    }

    # Save results
    with open(args.output, "w") as f:
        json.dump(final_results, f, indent=2)

    print(f"\n✅ Multi-currency analysis complete!")
    print(f"💾 Results saved to {args.output}")

    # Print summary
    currencies_found = coverage_results.get("currencies_found", {})
    print(f"\n📋 Summary:")
    print(f"   Currencies supported: {', '.join(currencies_found.keys())}")
    print(f"   Total tickers analyzed: {sum(len(tickers) for tickers in currencies_found.values())}")
    print(f"   Normalization target: {args.normalize_to}")


if __name__ == "__main__":
    main()