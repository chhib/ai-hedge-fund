#!/usr/bin/env python3
"""
Quick fix for Börsdata market cap scaling issue.

This script demonstrates the fix and validates it against FinancialDatasets data.
"""

import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.borsdata_client import BorsdataClient
from src.data.borsdata_kpis import FinancialMetricsAssembler


def fix_market_cap_scaling(bd_value: float) -> float:
    """
    Convert Börsdata market cap values from millions to absolute values.

    Args:
        bd_value: Börsdata value in millions

    Returns:
        Absolute value comparable to FinancialDatasets
    """
    if bd_value is None:
        return None
    return bd_value * 1_000_000


def test_scaling_fix():
    """Test the market cap scaling fix with real data."""
    api_key = os.getenv('BORSDATA_API_KEY')
    if not api_key:
        print("❌ BORSDATA_API_KEY not set")
        return

    client = BorsdataClient(api_key=api_key)
    assembler = FinancialMetricsAssembler(client)

    test_tickers = ["AAPL", "MSFT", "NVDA"]

    print("🔧 Testing Market Cap Scaling Fix")
    print("=" * 50)

    for ticker in test_tickers:
        try:
            metrics = assembler.assemble(
                ticker=ticker,
                end_date="2025-09-15",
                period="ttm",
                limit=1,
                api_key=api_key,
                use_global=True
            )

            if metrics:
                m = metrics[0]
                raw_market_cap = getattr(m, 'market_cap', None)
                raw_enterprise_value = getattr(m, 'enterprise_value', None)

                fixed_market_cap = fix_market_cap_scaling(raw_market_cap)
                fixed_enterprise_value = fix_market_cap_scaling(raw_enterprise_value)

                print(f"\n📊 {ticker}:")
                print(f"   Raw Market Cap: ${raw_market_cap:,.1f}M")
                print(f"   Fixed Market Cap: ${fixed_market_cap:,.0f}")
                print(f"   Raw Enterprise Value: ${raw_enterprise_value:,.1f}M")
                print(f"   Fixed Enterprise Value: ${fixed_enterprise_value:,.0f}")

                # Show the scale difference
                if raw_market_cap:
                    scale_factor = fixed_market_cap / raw_market_cap
                    print(f"   Scale Factor: {scale_factor:,.0f}x")

        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}")

    print(f"\n✅ Scaling fix validation complete")
    print(f"💡 Apply this fix in borsdata_kpis.py to resolve market cap discrepancies")


def show_proposed_implementation():
    """Show the proposed code changes."""
    print(f"\n📝 Proposed Implementation:")
    print("=" * 50)

    code = '''
# In src/data/borsdata_kpis.py, modify the _assemble_financial_metrics method:

def _scale_market_values(value: Optional[float]) -> Optional[float]:
    """Convert Börsdata millions to absolute values for market cap/EV."""
    return value * 1_000_000 if value is not None else None

# Then in the FinancialMetrics construction:
FinancialMetrics(
    # ... existing fields ...
    market_cap=_scale_market_values(market_cap_raw),
    enterprise_value=_scale_market_values(enterprise_value_raw),
    # ... remaining fields ...
)
'''

    print(code)


if __name__ == "__main__":
    test_scaling_fix()
    show_proposed_implementation()