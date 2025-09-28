#!/usr/bin/env python3
"""
Cross-Validation Framework for FinancialDatasets (FD) vs Börsdata (BD) Comparison

This script provides comprehensive comparison between the original FinancialDatasets
implementation and the current Börsdata fork to validate migration integrity and
identify areas for harmonization.

Usage:
    poetry run python scripts/cross_validation_framework.py --ticker AAPL --test-date 2025-09-15
    poetry run python scripts/cross_validation_framework.py --ticker MSFT --compare-agents warren_buffett,fundamentals
    poetry run python scripts/cross_validation_framework.py --batch-test AAPL,MSFT,NVDA
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

# Add both codebases to Python path
current_dir = Path(__file__).parent.parent
original_dir = current_dir.parent / "ai-hedge-fund-virattt"

sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(original_dir))

# Import from original codebase (FinancialDatasets)
try:
    from src.tools.api import get_financial_metrics as fd_get_financial_metrics
    from src.tools.api import get_prices as fd_get_prices
    from src.tools.api import get_insider_trades as fd_get_insider_trades
    from src.agents.warren_buffett import warren_buffett_agent as fd_warren_buffett
    from src.agents.fundamentals import fundamentals_agent as fd_fundamentals
    print("✓ Successfully imported FinancialDatasets modules")
except ImportError as e:
    print(f"❌ Failed to import FinancialDatasets modules: {e}")
    sys.exit(1)

# Clear path and import from Börsdata fork
sys.path = [p for p in sys.path if "ai-hedge-fund-virattt" not in p]

# Import from Börsdata fork
try:
    from src.data.borsdata_client import BorsdataClient
    from src.data.borsdata_kpis import FinancialMetricsAssembler
    from src.agents.warren_buffett import warren_buffett_agent as bd_warren_buffett
    from src.agents.fundamentals import fundamentals_agent as bd_fundamentals
    from src.data.models import FinancialMetrics as BDFinancialMetrics
    print("✓ Successfully imported Börsdata modules")
except ImportError as e:
    print(f"❌ Failed to import Börsdata modules: {e}")
    sys.exit(1)


class CrossValidationFramework:
    """Framework for comparing FinancialDatasets vs Börsdata implementations."""

    def __init__(self, fd_api_key: str, bd_api_key: str):
        self.fd_api_key = fd_api_key
        self.bd_api_key = bd_api_key
        self.borsdata_client = BorsdataClient(bd_api_key)
        self.results = {}

    def compare_financial_metrics(self, ticker: str, test_date: str) -> Dict[str, Any]:
        """Compare financial metrics between FD and BD sources."""
        print(f"\n🔍 Comparing financial metrics for {ticker} on {test_date}")

        # Get FinancialDatasets metrics
        try:
            fd_metrics = fd_get_financial_metrics(
                ticker=ticker,
                as_of_date=test_date,
                period="ttm",
                limit=1,
                api_key=self.fd_api_key
            )
            fd_data = fd_metrics[0] if fd_metrics else None
            print(f"  ✓ FinancialDatasets: {len(fd_metrics) if fd_metrics else 0} records")
        except Exception as e:
            print(f"  ❌ FinancialDatasets error: {e}")
            fd_data = None

        # Get Börsdata metrics
        try:
            assembler = FinancialMetricsAssembler(self.borsdata_client)
            bd_metrics = assembler.assemble_financial_metrics(
                ticker=ticker,
                as_of_date=test_date,
                period="ttm"
            )
            bd_data = bd_metrics[0] if bd_metrics else None
            print(f"  ✓ Börsdata: {len(bd_metrics) if bd_metrics else 0} records")
        except Exception as e:
            print(f"  ❌ Börsdata error: {e}")
            bd_data = None

        # Compare key metrics
        comparison = {
            "ticker": ticker,
            "test_date": test_date,
            "fd_available": fd_data is not None,
            "bd_available": bd_data is not None,
            "metric_comparison": {},
            "missing_metrics": {"fd_only": [], "bd_only": [], "both_missing": []},
            "value_differences": {}
        }

        if fd_data and bd_data:
            # Core metrics to compare
            key_metrics = [
                "market_cap", "enterprise_value", "price_to_earnings_ratio",
                "price_to_book_ratio", "price_to_sales_ratio", "enterprise_value_to_ebitda_ratio",
                "return_on_equity", "return_on_assets", "gross_margin", "operating_margin",
                "net_margin", "debt_to_equity", "current_ratio", "revenue_growth",
                "earnings_growth", "free_cash_flow_growth"
            ]

            for metric in key_metrics:
                fd_value = getattr(fd_data, metric, None)
                bd_value = getattr(bd_data, metric, None)

                if fd_value is not None and bd_value is not None:
                    # Calculate percentage difference
                    if fd_value != 0:
                        pct_diff = ((bd_value - fd_value) / fd_value) * 100
                    else:
                        pct_diff = None if bd_value == 0 else float('inf')

                    comparison["metric_comparison"][metric] = {
                        "fd_value": fd_value,
                        "bd_value": bd_value,
                        "percent_diff": pct_diff,
                        "significant_diff": abs(pct_diff) > 10 if pct_diff is not None else False
                    }
                elif fd_value is not None:
                    comparison["missing_metrics"]["bd_only"].append(metric)
                elif bd_value is not None:
                    comparison["missing_metrics"]["fd_only"].append(metric)
                else:
                    comparison["missing_metrics"]["both_missing"].append(metric)

        return comparison

    def compare_agent_signals(self, ticker: str, test_date: str, agents: List[str] = None) -> Dict[str, Any]:
        """Compare agent trading signals between FD and BD implementations."""
        if agents is None:
            agents = ["warren_buffett", "fundamentals"]

        print(f"\n🤖 Comparing agent signals for {ticker} on {test_date}")

        agent_comparison = {
            "ticker": ticker,
            "test_date": test_date,
            "agents": {}
        }

        for agent_name in agents:
            print(f"  Analyzing {agent_name} agent...")

            try:
                # This would require setting up full agent state - simplified for framework
                # In practice, would need to run full backtest comparison
                agent_comparison["agents"][agent_name] = {
                    "status": "framework_ready",
                    "note": "Full agent comparison requires backtest execution"
                }
            except Exception as e:
                print(f"    ❌ Error comparing {agent_name}: {e}")
                agent_comparison["agents"][agent_name] = {
                    "status": "error",
                    "error": str(e)
                }

        return agent_comparison

    def run_parallel_backtest_comparison(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Run parallel backtests using both FD and BD implementations."""
        print(f"\n🔄 Running parallel backtest comparison for {ticker}")

        results = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "fd_results": None,
            "bd_results": None,
            "comparison": {}
        }

        # This would require:
        # 1. Running original ai-hedge-fund with FD API key
        # 2. Running current fork with BD API key
        # 3. Comparing portfolio performance, signals, etc.

        results["status"] = "framework_ready"
        results["note"] = "Requires full CLI integration for parallel execution"

        return results

    def generate_harmonization_report(self, comparisons: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate comprehensive harmonization recommendations."""
        print(f"\n📊 Generating harmonization report from {len(comparisons)} comparisons")

        report = {
            "summary": {
                "total_comparisons": len(comparisons),
                "successful_comparisons": 0,
                "failed_comparisons": 0,
                "average_metric_coverage": 0
            },
            "metric_analysis": {},
            "recommendations": [],
            "priority_fixes": []
        }

        successful_comparisons = 0
        total_coverage = 0
        metric_stats = {}

        for comp in comparisons:
            if comp.get("fd_available") and comp.get("bd_available"):
                successful_comparisons += 1

                # Analyze metric coverage
                metrics = comp.get("metric_comparison", {})
                total_coverage += len(metrics)

                # Track individual metric statistics
                for metric, data in metrics.items():
                    if metric not in metric_stats:
                        metric_stats[metric] = {
                            "comparisons": 0,
                            "significant_diffs": 0,
                            "avg_percent_diff": 0,
                            "percent_diffs": []
                        }

                    stats = metric_stats[metric]
                    stats["comparisons"] += 1

                    if data.get("significant_diff"):
                        stats["significant_diffs"] += 1

                    pct_diff = data.get("percent_diff")
                    if pct_diff is not None and abs(pct_diff) < 1000:  # Filter outliers
                        stats["percent_diffs"].append(pct_diff)

        # Calculate summary statistics
        report["summary"]["successful_comparisons"] = successful_comparisons
        report["summary"]["failed_comparisons"] = len(comparisons) - successful_comparisons
        if successful_comparisons > 0:
            report["summary"]["average_metric_coverage"] = total_coverage / successful_comparisons

        # Generate metric analysis
        for metric, stats in metric_stats.items():
            if stats["percent_diffs"]:
                avg_diff = sum(stats["percent_diffs"]) / len(stats["percent_diffs"])
                stats["avg_percent_diff"] = avg_diff

                report["metric_analysis"][metric] = {
                    "coverage": f"{stats['comparisons']}/{len(comparisons)}",
                    "significant_differences": stats["significant_diffs"],
                    "avg_percent_difference": round(avg_diff, 2),
                    "needs_attention": abs(avg_diff) > 10 or stats["significant_diffs"] > stats["comparisons"] * 0.5
                }

        # Generate recommendations
        high_variance_metrics = [
            metric for metric, analysis in report["metric_analysis"].items()
            if analysis.get("needs_attention", False)
        ]

        if high_variance_metrics:
            report["recommendations"].append({
                "category": "Data Harmonization",
                "priority": "High",
                "description": f"Address high variance in metrics: {', '.join(high_variance_metrics[:5])}",
                "metrics_affected": high_variance_metrics
            })

        report["recommendations"].append({
            "category": "Coverage Expansion",
            "priority": "Medium",
            "description": "Expand Börsdata KPI mapping to achieve 100% FinancialDatasets parity",
            "action": "Map remaining FD metrics to BD KPI equivalents"
        })

        report["recommendations"].append({
            "category": "Validation Framework",
            "priority": "High",
            "description": "Implement continuous cross-validation testing",
            "action": "Add automated FD/BD comparison to CI/CD pipeline"
        })

        return report


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="FD/BD Cross-Validation Framework")
    parser.add_argument("--ticker", type=str, help="Single ticker to analyze")
    parser.add_argument("--test-date", type=str, default="2025-09-15", help="Test date (YYYY-MM-DD)")
    parser.add_argument("--batch-test", type=str, help="Comma-separated list of tickers")
    parser.add_argument("--compare-agents", type=str, help="Comma-separated list of agents")
    parser.add_argument("--output", type=str, default="cross_validation_results.json", help="Output file")

    args = parser.parse_args()

    # Get API keys
    fd_api_key = os.getenv("FINANCIAL_DATASETS_API_KEY")
    bd_api_key = os.getenv("BORSDATA_API_KEY")

    if not fd_api_key:
        print("❌ FINANCIAL_DATASETS_API_KEY not found in environment")
        sys.exit(1)
    if not bd_api_key:
        print("❌ BORSDATA_API_KEY not found in environment")
        sys.exit(1)

    print("🚀 Starting FD/BD Cross-Validation Framework")
    print(f"   FinancialDatasets API: {'✓' if fd_api_key else '❌'}")
    print(f"   Börsdata API: {'✓' if bd_api_key else '❌'}")

    framework = CrossValidationFramework(fd_api_key, bd_api_key)

    # Determine tickers to test
    if args.batch_test:
        tickers = [t.strip() for t in args.batch_test.split(",")]
    elif args.ticker:
        tickers = [args.ticker]
    else:
        tickers = ["AAPL"]  # Default

    agents = None
    if args.compare_agents:
        agents = [a.strip() for a in args.compare_agents.split(",")]

    all_results = []

    # Run comparisons
    for ticker in tickers:
        print(f"\n{'='*60}")
        print(f"Processing {ticker}")
        print(f"{'='*60}")

        # Financial metrics comparison
        metrics_comp = framework.compare_financial_metrics(ticker, args.test_date)
        all_results.append(metrics_comp)

        # Agent signals comparison (framework setup)
        if agents:
            agent_comp = framework.compare_agent_signals(ticker, args.test_date, agents)
            all_results.append(agent_comp)

    # Generate harmonization report
    report = framework.generate_harmonization_report(all_results)

    # Save results
    output_data = {
        "framework_version": "1.0",
        "execution_time": datetime.now().isoformat(),
        "comparisons": all_results,
        "harmonization_report": report
    }

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2, default=str)

    print(f"\n✅ Cross-validation complete! Results saved to {args.output}")
    print(f"📊 Summary: {report['summary']['successful_comparisons']}/{len(all_results)} successful comparisons")

    # Print key findings
    if report.get("recommendations"):
        print(f"\n🎯 Key Recommendations:")
        for rec in report["recommendations"][:3]:
            print(f"   • {rec['category']}: {rec['description']}")


if __name__ == "__main__":
    main()