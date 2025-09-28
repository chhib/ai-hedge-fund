#!/usr/bin/env python3
"""
Direct FD vs BD Comparison Script

Simple comparison between FinancialDatasets and Börsdata for key metrics.
This script can run both implementations to compare data directly.

Usage:
    poetry run python scripts/fd_bd_direct_comparison.py AAPL
    poetry run python scripts/fd_bd_direct_comparison.py MSFT --verbose
"""

import argparse
import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime


def run_original_analysis(ticker: str, test_date: str = "2025-09-15") -> dict:
    """Run analysis using original FinancialDatasets implementation."""
    print(f"🔍 Running FinancialDatasets analysis for {ticker}...")

    original_dir = Path(__file__).parent.parent.parent / "ai-hedge-fund-virattt"

    # Create a simple test script in the original directory
    test_script = f"""
import sys
import os
sys.path.insert(0, '/Users/ksu541/Code/ai-hedge-fund-virattt/src')

from tools.api import get_financial_metrics, get_market_cap
import json

def main():
    api_key = os.getenv('FINANCIAL_DATASETS_API_KEY')
    if not api_key:
        print({{"error": "No FINANCIAL_DATASETS_API_KEY found"}})
        return

    try:
        # Get financial metrics
        metrics = get_financial_metrics('{ticker}', '{test_date}', period='ttm', limit=1, api_key=api_key)

        if metrics:
            m = metrics[0]
            result = {{
                "ticker": "{ticker}",
                "source": "FinancialDatasets",
                "test_date": "{test_date}",
                "market_cap": getattr(m, 'market_cap', None),
                "enterprise_value": getattr(m, 'enterprise_value', None),
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
                "available_metrics": len([attr for attr in dir(m) if not attr.startswith('_') and getattr(m, attr) is not None])
            }}
            print(json.dumps(result, indent=2))
        else:
            print({{"error": "No metrics found"}})
    except Exception as e:
        print({{"error": str(e)}})

if __name__ == "__main__":
    main()
"""

    # Write and execute the test script
    script_path = original_dir / "temp_fd_test.py"
    with open(script_path, "w") as f:
        f.write(test_script)

    try:
        # Run the script in the original directory
        result = subprocess.run(
            ["python", "temp_fd_test.py"],
            cwd=original_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"error": f"Invalid JSON: {result.stdout}"}
        else:
            return {"error": f"Script failed: {result.stderr}"}

    except subprocess.TimeoutExpired:
        return {"error": "FinancialDatasets request timed out"}
    except Exception as e:
        return {"error": f"Execution error: {e}"}
    finally:
        # Clean up
        if script_path.exists():
            script_path.unlink()


def run_borsdata_analysis(ticker: str, test_date: str = "2025-09-15") -> dict:
    """Run analysis using current Börsdata implementation."""
    print(f"🔍 Running Börsdata analysis for {ticker}...")

    try:
        # Import Börsdata modules
        from src.data.borsdata_client import BorsdataClient
        from src.data.borsdata_kpis import FinancialMetricsAssembler

        api_key = os.getenv('BORSDATA_API_KEY')
        if not api_key:
            return {"error": "No BORSDATA_API_KEY found"}

        # Create client and assembler
        client = BorsdataClient(api_key=api_key)
        assembler = FinancialMetricsAssembler(client)

        # Get financial metrics - try global first for US tickers
        use_global = ticker in ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META"]
        metrics = assembler.assemble(
            ticker=ticker,
            end_date=test_date,
            period="ttm",
            limit=1,
            api_key=api_key,
            use_global=use_global
        )

        if metrics:
            m = metrics[0]
            result = {
                "ticker": ticker,
                "source": "Börsdata",
                "test_date": test_date,
                "currency": getattr(m, 'currency', None),
                "market_cap": getattr(m, 'market_cap', None),
                "enterprise_value": getattr(m, 'enterprise_value', None),
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
                "available_metrics": len([attr for attr in dir(m) if not attr.startswith('_') and getattr(m, attr) is not None])
            }
            return result
        else:
            return {"error": "No metrics found"}

    except Exception as e:
        return {"error": f"Börsdata error: {e}"}


def compare_results(fd_result: dict, bd_result: dict, verbose: bool = False) -> dict:
    """Compare results between FD and BD implementations."""

    if "error" in fd_result and "error" in bd_result:
        return {
            "status": "both_failed",
            "fd_error": fd_result["error"],
            "bd_error": bd_result["error"]
        }
    elif "error" in fd_result:
        return {
            "status": "fd_failed",
            "error": fd_result["error"],
            "bd_metrics": bd_result.get("available_metrics", 0)
        }
    elif "error" in bd_result:
        return {
            "status": "bd_failed",
            "error": bd_result["error"],
            "fd_metrics": fd_result.get("available_metrics", 0)
        }

    # Both succeeded - compare metrics
    comparison = {
        "status": "success",
        "ticker": fd_result.get("ticker"),
        "test_date": fd_result.get("test_date"),
        "coverage": {
            "fd_metrics": fd_result.get("available_metrics", 0),
            "bd_metrics": bd_result.get("available_metrics", 0)
        },
        "metric_comparison": {},
        "summary": {
            "total_compared": 0,
            "exact_matches": 0,
            "close_matches": 0,  # Within 5%
            "significant_differences": 0,  # >10% difference
            "missing_in_fd": 0,
            "missing_in_bd": 0
        }
    }

    # Key metrics to compare
    key_metrics = [
        "market_cap", "enterprise_value", "price_to_earnings_ratio",
        "price_to_book_ratio", "price_to_sales_ratio", "enterprise_value_to_ebitda_ratio",
        "return_on_equity", "return_on_assets", "gross_margin", "operating_margin",
        "net_margin", "debt_to_equity", "current_ratio", "revenue_growth",
        "earnings_growth", "free_cash_flow_growth"
    ]

    for metric in key_metrics:
        fd_val = fd_result.get(metric)
        bd_val = bd_result.get(metric)

        if fd_val is not None and bd_val is not None:
            comparison["summary"]["total_compared"] += 1

            # Calculate percentage difference
            if fd_val != 0:
                pct_diff = ((bd_val - fd_val) / fd_val) * 100
            else:
                pct_diff = 0 if bd_val == 0 else float('inf')

            # Categorize difference
            if abs(pct_diff) < 0.1:
                comparison["summary"]["exact_matches"] += 1
                match_type = "exact"
            elif abs(pct_diff) < 5:
                comparison["summary"]["close_matches"] += 1
                match_type = "close"
            elif abs(pct_diff) < 10:
                match_type = "moderate"
            else:
                comparison["summary"]["significant_differences"] += 1
                match_type = "significant"

            comparison["metric_comparison"][metric] = {
                "fd_value": fd_val,
                "bd_value": bd_val,
                "percent_diff": round(pct_diff, 2) if pct_diff != float('inf') else "inf",
                "match_type": match_type
            }

        elif fd_val is not None:
            comparison["summary"]["missing_in_bd"] += 1
            if verbose:
                comparison["metric_comparison"][metric] = {
                    "fd_value": fd_val,
                    "bd_value": None,
                    "status": "missing_in_bd"
                }
        elif bd_val is not None:
            comparison["summary"]["missing_in_fd"] += 1
            if verbose:
                comparison["metric_comparison"][metric] = {
                    "fd_value": None,
                    "bd_value": bd_val,
                    "status": "missing_in_fd"
                }

    return comparison


def print_comparison_summary(comparison: dict):
    """Print a formatted summary of the comparison."""
    print(f"\n{'='*60}")
    print(f"📊 COMPARISON SUMMARY")
    print(f"{'='*60}")

    if comparison["status"] != "success":
        print(f"❌ Status: {comparison['status']}")
        if "error" in comparison:
            print(f"   Error: {comparison['error']}")
        return

    print(f"✅ Ticker: {comparison['ticker']}")
    print(f"📅 Test Date: {comparison['test_date']}")

    coverage = comparison["coverage"]
    print(f"\n📈 Coverage:")
    print(f"   FinancialDatasets: {coverage['fd_metrics']} metrics")
    print(f"   Börsdata: {coverage['bd_metrics']} metrics")

    summary = comparison["summary"]
    total = summary["total_compared"]
    if total > 0:
        print(f"\n🎯 Metric Comparison ({total} compared):")
        print(f"   ✓ Exact matches: {summary['exact_matches']} ({summary['exact_matches']/total*100:.1f}%)")
        print(f"   ≈ Close matches: {summary['close_matches']} ({summary['close_matches']/total*100:.1f}%)")
        print(f"   ⚠️  Significant diffs: {summary['significant_differences']} ({summary['significant_differences']/total*100:.1f}%)")
        print(f"   📉 Missing in BD: {summary['missing_in_bd']}")
        print(f"   📈 Missing in FD: {summary['missing_in_fd']}")

        # Show significant differences
        significant_diffs = [
            (metric, data) for metric, data in comparison["metric_comparison"].items()
            if data.get("match_type") == "significant"
        ]

        if significant_diffs:
            print(f"\n⚠️  Significant Differences (>10%):")
            for metric, data in significant_diffs[:5]:  # Show top 5
                fd_val = data["fd_value"]
                bd_val = data["bd_value"]
                pct_diff = data["percent_diff"]
                print(f"   {metric}: FD={fd_val:.4f}, BD={bd_val:.4f} ({pct_diff:+.1f}%)")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Direct FD vs BD Comparison")
    parser.add_argument("ticker", help="Ticker symbol to analyze")
    parser.add_argument("--test-date", default="2025-09-15", help="Test date (YYYY-MM-DD)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output", help="Save results to JSON file")

    args = parser.parse_args()

    print(f"🚀 FD vs BD Direct Comparison for {args.ticker}")
    print(f"📅 Test Date: {args.test_date}")

    # Check API keys
    fd_key = os.getenv("FINANCIAL_DATASETS_API_KEY")
    bd_key = os.getenv("BORSDATA_API_KEY")

    print(f"\n🔑 API Keys:")
    print(f"   FinancialDatasets: {'✓' if fd_key else '❌'}")
    print(f"   Börsdata: {'✓' if bd_key else '❌'}")

    if not fd_key or not bd_key:
        print("❌ Missing required API keys")
        sys.exit(1)

    # Run both analyses
    fd_result = run_original_analysis(args.ticker, args.test_date)
    bd_result = run_borsdata_analysis(args.ticker, args.test_date)

    # Compare results
    comparison = compare_results(fd_result, bd_result, args.verbose)

    # Print summary
    print_comparison_summary(comparison)

    # Save detailed results if requested
    if args.output:
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "ticker": args.ticker,
            "test_date": args.test_date,
            "fd_result": fd_result,
            "bd_result": bd_result,
            "comparison": comparison
        }

        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n💾 Detailed results saved to {args.output}")


if __name__ == "__main__":
    main()