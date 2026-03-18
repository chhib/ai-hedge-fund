#!/usr/bin/env python3
"""Generate an IBKR universe file from a Borsdata universe file."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List

from src.integrations.ticker_mapper import map_borsdata_to_ibkr


def _parse_universe_lines(lines: Iterable[str]) -> List[str]:
    tickers: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("--"):
            continue
        # Remove inline comments
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        # Support comma-separated entries on a line
        if "," in line:
            parts = [part.strip().strip('"').strip("'") for part in line.split(",")]
            tickers.extend([part for part in parts if part])
        else:
            tickers.append(line.strip().strip('"').strip("'"))

    # De-duplicate while preserving order
    seen = set()
    ordered: List[str] = []
    for ticker in tickers:
        if ticker and ticker not in seen:
            seen.add(ticker)
            ordered.append(ticker)
    return ordered


def build_ibkr_universe(input_path: Path, output_path: Path) -> None:
    tickers = _parse_universe_lines(input_path.read_text().splitlines())
    mapped = [map_borsdata_to_ibkr(ticker) for ticker in tickers]

    lines = [
        "# IBKR universe (generated)",
        f"# Source: {input_path.name}",
        "# Format: IBKR_TICKER  # from Borsdata ticker",
        "",
    ]

    for original, ibkr in zip(tickers, mapped):
        if ibkr:
            lines.append(f"{ibkr:<12} # {original}")

    output_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate IBKR universe file from Borsdata universe.")
    parser.add_argument(
        "--input",
        default="portfolios/borsdata_universe.txt",
        help="Path to the Borsdata universe file",
    )
    parser.add_argument(
        "--output",
        default="portfolios/ibkr_universe.txt",
        help="Path to write the IBKR universe file",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise SystemExit(f"Input universe not found: {input_path}")

    build_ibkr_universe(input_path, output_path)
    print(f"Generated IBKR universe: {output_path}")


if __name__ == "__main__":
    main()
