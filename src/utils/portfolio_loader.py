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


def load_universe(universe_file: Optional[str] = None, tickers_str: Optional[str] = None) -> List[str]:
    """
    Load investment universe from various sources.

    Supports both comma-separated and line-separated formats.
    Supports comments: lines starting with # or --, and inline comments after #.
    Market detection (Nordic vs Global) is handled automatically via borsdata_ticker_mapping.

    Args:
        universe_file: Path to a file containing tickers (line-separated or CSV)
        tickers_str: Comma-separated string of tickers

    Returns:
        List of ticker symbols
    """

    def clean_ticker(ticker: str) -> Optional[str]:
        """Extract ticker from string, removing inline comments and whitespace"""
        # Remove inline comments (everything after #)
        if "#" in ticker:
            ticker = ticker.split("#")[0]
        # Strip whitespace and quotes
        ticker = ticker.strip().strip('"').strip("'")
        return ticker if ticker else None

    def is_comment_line(line: str) -> bool:
        """Check if line is a comment (starts with # or --)"""
        stripped = line.strip()
        return stripped.startswith("#") or stripped.startswith("--")

    universe = set()

    if universe_file:
        with open(universe_file, "r") as f:
            content = f.read().strip()

            # Detect and parse format
            if "," in content:
                # CSV format - handles quoted tickers like "ERIC B"
                # Filter out comment lines before CSV parsing
                non_comment_lines = [line for line in content.split("\n") if not is_comment_line(line)]
                csv_content = "\n".join(non_comment_lines)
                csv_reader = csv.reader(StringIO(csv_content))
                for row in csv_reader:
                    for ticker in row:
                        cleaned = clean_ticker(ticker)
                        if cleaned:
                            universe.add(cleaned)
            else:
                # Line-separated format
                for line in content.split("\n"):
                    if is_comment_line(line):
                        continue
                    cleaned = clean_ticker(line)
                    if cleaned:
                        universe.add(cleaned)

    # Add inline tickers
    if tickers_str:
        csv_reader = csv.reader(StringIO(tickers_str))
        for row in csv_reader:
            for ticker in row:
                cleaned = clean_ticker(ticker)
                if cleaned:
                    universe.add(cleaned)

    return list(universe)