import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class Position:
    ticker: str
    shares: float
    cost_basis: float
    currency: str = "USD"
    date_acquired: Optional[datetime] = None


@dataclass
class Portfolio:
    positions: List[Position]
    cash_holdings: Dict[str, float]  # {'USD': 10000, 'SEK': 75000}
    last_updated: datetime


def load_portfolio(portfolio_file: str) -> Portfolio:
    """Load portfolio from CSV file"""

    positions = []
    cash_holdings = {}

    df = pd.read_csv(portfolio_file)
    required_cols = ["ticker", "shares"]

    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"CSV must contain columns: {required_cols}")

    for _, row in df.iterrows():
        ticker = row["ticker"].strip()

        # Handle cash entries
        if ticker.upper() == "CASH":
            currency = row["currency"] if "currency" in row and pd.notna(row["currency"]) else "USD"
            cash_holdings[currency] = float(row["shares"])
            continue

        # Regular position
        positions.append(
            Position(
                ticker=ticker,
                shares=float(row["shares"]),
                cost_basis=float(row["cost_basis"]) if "cost_basis" in row and pd.notna(row["cost_basis"]) else 0,
                currency=row["currency"] if "currency" in row and pd.notna(row["currency"]) else "USD",
                date_acquired=pd.to_datetime(row["date_acquired"]) if "date_acquired" in row and pd.notna(row["date_acquired"]) else None,
            )
        )

    return Portfolio(positions=positions, cash_holdings=cash_holdings, last_updated=datetime.now())


def load_universe(universe_file: Optional[str] = None, tickers_str: Optional[str] = None, nordics_str: Optional[str] = None, global_str: Optional[str] = None) -> List[str]:
    """
    Load investment universe from various sources
    Supports both comma-separated and line-separated formats
    """

    universe = set()

    if universe_file:
        with open(universe_file, "r") as f:
            content = f.read().strip()

            # Detect and parse format
            if "," in content:
                # CSV format - handles quoted tickers like "ERIC B"
                csv_reader = csv.reader(StringIO(content))
                for row in csv_reader:
                    for ticker in row:
                        ticker = ticker.strip().strip('"').strip("'")
                        if ticker and not ticker.startswith("#"):
                            universe.add(ticker)
            else:
                # Line-separated format
                for line in content.split("\n"):
                    ticker = line.strip().strip('"').strip("'")
                    if ticker and not ticker.startswith("#"):
                        universe.add(ticker)

    # Add inline tickers
    for ticker_str in [tickers_str, nordics_str, global_str]:
        if ticker_str:
            csv_reader = csv.reader(StringIO(ticker_str))
            for row in csv_reader:
                for ticker in row:
                    ticker = ticker.strip().strip('"').strip("'")
                    if ticker:
                        universe.add(ticker)

    return list(universe)