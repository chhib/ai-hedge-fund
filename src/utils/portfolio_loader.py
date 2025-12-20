import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional
import warnings

import pandas as pd


# Common ISO 4217 currency codes used in markets supported by Börsdata
VALID_CURRENCIES = {
    "USD", "EUR", "GBP", "SEK", "DKK", "NOK", "CHF", "CAD", "AUD", "JPY",
    "HKD", "SGD", "CNY", "PLN", "CZK", "HUF", "ISK", "TRY", "RUB", "INR",
    "BRL", "MXN", "ZAR", "NZD", "KRW", "TWD", "THB", "IDR", "MYR", "PHP",
}


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


def validate_portfolio_data(
    ticker: str,
    shares: float,
    cost_basis: float,
    currency: str,
    row_num: int
) -> List[str]:
    """Validate portfolio position data and return list of warnings."""
    warnings_list = []

    if shares < 0:
        warnings_list.append(f"Row {row_num}: Negative shares ({shares}) for {ticker} - is this intentional (short position)?")

    if cost_basis < 0:
        warnings_list.append(f"Row {row_num}: Negative cost_basis ({cost_basis}) for {ticker}")

    if currency.upper() not in VALID_CURRENCIES:
        warnings_list.append(f"Row {row_num}: Unknown currency '{currency}' for {ticker} - not in ISO 4217 list")

    return warnings_list


def load_portfolio(portfolio_file: str, validate: bool = True) -> Portfolio:
    """Load portfolio from CSV file.

    Args:
        portfolio_file: Path to CSV file with columns: ticker, shares, [cost_basis, currency, date_acquired]
        validate: If True, emit warnings for suspicious data (negative shares, invalid currencies)

    Returns:
        Portfolio object with positions and cash holdings
    """

    positions = []
    cash_holdings = {}
    validation_warnings = []

    df = pd.read_csv(portfolio_file)
    required_cols = ["ticker", "shares"]

    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"CSV must contain columns: {required_cols}")

    for row_num, (_, row) in enumerate(df.iterrows(), start=2):  # Start at 2 for header row
        ticker = row["ticker"].strip()
        shares = float(row["shares"])
        cost_basis = float(row["cost_basis"]) if "cost_basis" in row and pd.notna(row["cost_basis"]) else 0
        currency = row["currency"] if "currency" in row and pd.notna(row["currency"]) else "USD"

        # Handle cash entries
        if ticker.upper() == "CASH":
            cash_holdings[currency] = shares
            continue

        # Validate position data
        if validate:
            validation_warnings.extend(
                validate_portfolio_data(ticker, shares, cost_basis, currency, row_num)
            )

        # Regular position
        positions.append(
            Position(
                ticker=ticker,
                shares=shares,
                cost_basis=cost_basis,
                currency=currency,
                date_acquired=pd.to_datetime(row["date_acquired"]) if "date_acquired" in row and pd.notna(row["date_acquired"]) else None,
            )
        )

    # Emit validation warnings
    if validation_warnings:
        for warning in validation_warnings:
            warnings.warn(warning, UserWarning)

    return Portfolio(positions=positions, cash_holdings=cash_holdings, last_updated=datetime.now())


def load_universe(universe_file: Optional[str] = None, tickers_str: Optional[str] = None, verbose: bool = False) -> List[str]:
    """
    Load investment universe from various sources.

    Supports both comma-separated and line-separated formats.
    Supports comments: lines starting with # or --, and inline comments after #.
    Supports delisted markers: # DELISTED: TICKER - Reason (these are tracked and skipped).
    Market detection (Nordic vs Global) is handled automatically via borsdata_ticker_mapping.

    Args:
        universe_file: Path to a file containing tickers (line-separated or CSV)
        tickers_str: Comma-separated string of tickers
        verbose: If True, print info about skipped delisted tickers

    Returns:
        List of ticker symbols
    """
    delisted_tickers: List[str] = []

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

    def extract_delisted(line: str) -> Optional[str]:
        """Extract ticker from DELISTED comment line, returns ticker if found"""
        stripped = line.strip().upper()
        if stripped.startswith("# DELISTED:"):
            # Format: # DELISTED: TICKER - Reason
            rest = line.strip()[11:].strip()  # After "# DELISTED:"
            if " - " in rest:
                ticker = rest.split(" - ")[0].strip()
            else:
                ticker = rest.split()[0].strip() if rest.split() else None
            return ticker
        return None

    universe = set()

    if universe_file:
        with open(universe_file, "r") as f:
            content = f.read().strip()

            # First pass: extract delisted tickers from DELISTED comments
            for line in content.split("\n"):
                delisted = extract_delisted(line)
                if delisted:
                    delisted_tickers.append(delisted)

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

    # Report delisted tickers if any were found
    if delisted_tickers and verbose:
        print(f"ℹ️  Skipping {len(delisted_tickers)} delisted ticker(s): {', '.join(delisted_tickers)}")

    return list(universe)