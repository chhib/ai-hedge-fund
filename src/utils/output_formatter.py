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

    # Recommendations table organized by action type
    recs = results.get("recommendations", [])
    if recs:
        print("\n" + "-" * 40)
        print("RECOMMENDATIONS")
        print("-" * 40)

        def _format_shares(value: float) -> str:
            try:
                if value is None:
                    return "0"
                return f"{int(value)}"
            except (ValueError, TypeError):
                return f"{value:.0f}"

        # Group recommendations by action
        by_action = {
            "SELL": [],
            "DECREASE": [],
            "HOLD": [],
            "INCREASE": [],
            "ADD": []
        }

        for rec in recs:
            action = rec["action"]
            if action in by_action:
                current_shares = _format_shares(rec["current_shares"])
                target_shares = _format_shares(rec.get("target_shares", 0.0))
                change_value = rec.get("value_delta", 0.0)
                currency = rec.get("currency") or ""
                change_formatted = f"{change_value:+,.0f} {currency}".strip()

                by_action[action].append({
                    "ticker": rec["ticker"],
                    "current": current_shares,
                    "target": target_shares,
                    "change": change_formatted,
                    "reasoning": rec.get("reasoning", "") if verbose else ""
                })

        # Calculate max rows needed
        max_rows = max(len(items) for items in by_action.values()) if any(by_action.values()) else 0

        if max_rows > 0:
            # Print table header
            col_width = 20
            header = "| " + " | ".join([f"{action:^{col_width}}" for action in by_action.keys()]) + " |"
            separator = "+-" + "-+-".join(["-" * col_width for _ in by_action.keys()]) + "-+"

            print("\n" + separator)
            print(header)
            print(separator)

            # Print table rows - each ticker gets 3 lines
            for row_idx in range(max_rows):
                # Line 1: Ticker name
                line1_parts = []
                for action, items in by_action.items():
                    if row_idx < len(items):
                        ticker = f"{items[row_idx]['ticker']}"
                        line1_parts.append(f" {ticker:<{col_width}} ")
                    else:
                        line1_parts.append(f" {'':<{col_width}} ")
                print("|" + "|".join(line1_parts) + "|")

                # Line 2: Share change
                line2_parts = []
                for action, items in by_action.items():
                    if row_idx < len(items):
                        item = items[row_idx]
                        shares_change = f"{item['current']} → {item['target']} shs"
                        line2_parts.append(f" {shares_change:<{col_width}} ")
                    else:
                        line2_parts.append(f" {'':<{col_width}} ")
                print("|" + "|".join(line2_parts) + "|")

                # Line 3: Value change
                line3_parts = []
                for action, items in by_action.items():
                    if row_idx < len(items):
                        change = items[row_idx]['change']
                        # Truncate if too long
                        if len(change) > col_width:
                            change = change[:col_width-3] + "..."
                        line3_parts.append(f" {change:<{col_width}} ")
                    else:
                        line3_parts.append(f" {'':<{col_width}} ")
                print("|" + "|".join(line3_parts) + "|")

                # Add separator between items (not after last item)
                if row_idx < max_rows - 1:
                    print(separator)

            print(separator)

        # Print summary
        counts = {action: len(items) for action, items in by_action.items() if items}
        print("\n**Summary:**")
        for action, count in counts.items():
            emoji = {"ADD": "🟢", "INCREASE": "⬆️", "HOLD": "⏸️", "DECREASE": "⬇️", "SELL": "🔴"}.get(action, "")
            print(f"  {emoji} {count} position(s) to {action.lower()}")

        # Show detailed list if verbose
        if verbose:
            print("\n" + "-" * 40)
            print("DETAILED RECOMMENDATIONS")
            print("-" * 40)
            for action in by_action.keys():
                if by_action[action]:
                    print(f"\n{action}:")
                    for item in by_action[action]:
                        print(f"  • {item['ticker']}: {item['current']} → {item['target']} shares ({item['change']})")
                        if item['reasoning']:
                            print(f"    Reasoning: {item['reasoning']}")

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
