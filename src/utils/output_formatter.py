from datetime import datetime
from typing import Dict

import pandas as pd


def format_as_portfolio_csv(results: Dict) -> pd.DataFrame:
    """
    Convert recommendations to portfolio CSV format
    Maintains the same format as input for next iteration
    """

    portfolio_data = []

    # Process updated positions from recommendations
    for rec in results.get("updated_portfolio", {}).get("positions", []):
        if rec["shares"] > 0:  # Only include non-zero positions
            portfolio_data.append({"ticker": rec["ticker"], "shares": int(rec["shares"]), "cost_basis": round(rec["cost_basis"], 2), "currency": rec["currency"], "date_acquired": rec["date_acquired"]})

    # Add cash positions
    for currency, amount in results.get("updated_portfolio", {}).get("cash", {}).items():
        if amount > 0:
            portfolio_data.append({"ticker": "CASH", "shares": round(amount, 2), "cost_basis": "", "currency": currency, "date_acquired": ""})

    # Create DataFrame and sort
    df = pd.DataFrame(portfolio_data)
    if not df.empty:
        # Sort by currency then ticker
        df = df.sort_values(["currency", "ticker"])

    return df


def display_results(results: Dict, verbose: bool):
    """Display rebalancing recommendations in table format"""

    print("\n" + "=" * 80)
    print("PORTFOLIO REBALANCING ANALYSIS")
    print("=" * 80)
    print(f"Date: {results.get('analysis_date', datetime.now())}")

    # Current portfolio summary
    current = results.get("current_portfolio", {})
    home_currency = current.get("home_currency", "USD")
    total_value = current.get("total_value", 0)

    print(f"\nCurrent Portfolio Value: {total_value:,.2f} {home_currency}")
    print(f"Number of Positions: {current.get('num_positions', 0)}")

    # Show exchange rates if available
    exchange_rates = current.get("exchange_rates", {})
    if exchange_rates and len(exchange_rates) > 1:
        print(f"\nExchange Rates (to {home_currency}):")
        for currency, rate in sorted(exchange_rates.items()):
            if currency != home_currency:
                print(f"   1 {currency} = {rate:.4f} {home_currency}")

    # Recommendations table
    recs = results.get("recommendations", [])
    if recs:
        print("\n" + "-" * 40)
        print("RECOMMENDATIONS")
        print("-" * 40)

        for rec in recs:
            action = rec["action"]
            emoji = {"ADD": "🟢", "INCREASE": "⬆️", "HOLD": "⏸️", "DECREASE": "⬇️", "SELL": "🔴"}.get(action, "")

            def _format_shares(value: float) -> str:
                try:
                    if value is None:
                        return "0"
                    return f"{int(value)}"
                except (ValueError, TypeError):
                    return f"{value:.0f}"

            current_shares_display = _format_shares(rec["current_shares"])
            target_shares_display = _format_shares(rec.get("target_shares", 0.0))

            change_value = rec.get("value_delta", 0.0)
            currency = rec.get("currency") or ""
            change_formatted = f"{change_value:+,.0f}"
            if currency:
                change_formatted = f"{change_formatted} {currency}"

            print(f"\n{emoji} {rec['ticker']}: {action}")
            print(f"   Current: {current_shares_display} shares ({rec['current_weight']:.1%})")
            print(f"   Target:  {target_shares_display} shares ({rec['target_weight']:.1%})")
            print(f"   Change:  {change_formatted}")
            print(f"   Confidence: {rec['confidence']:.1%}")

            if verbose:
                print(f"   Reasoning: {rec['reasoning']}")

    # Show detailed analyst opinions if verbose
    if verbose and "analyst_signals" in results and results["analyst_signals"]:
        print("\n" + "-" * 40)
        print("ANALYST OPINIONS")
        print("-" * 40)

        by_ticker = {}
        for signal in results["analyst_signals"]:
            if signal.ticker not in by_ticker:
                by_ticker[signal.ticker] = []
            by_ticker[signal.ticker].append(signal)

        for ticker, signals in by_ticker.items():
            print(f"\n{ticker}:")
            for sig in signals:
                sentiment = "Bullish" if sig.signal > 0 else "Bearish" if sig.signal < 0 else "Neutral"
                print(f"  {sig.analyst}: {sentiment} ({sig.signal:+.2f})")
