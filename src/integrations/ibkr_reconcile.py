"""Portfolio reconciliation: compare live IBKR positions against a target CSV."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.utils.portfolio_loader import Portfolio


@dataclass
class PositionDrift:
    ticker: str
    status: str  # "match", "drift", "missing_live", "extra_live"
    live_shares: float
    target_shares: float
    shares_delta: float  # live - target
    live_weight: float  # % of total portfolio value
    target_weight: float
    weight_delta: float  # live_weight - target_weight
    currency: str


@dataclass
class ReconciliationResult:
    live_count: int
    target_count: int
    drifts: List[PositionDrift]
    drift_score: float  # RMS of weight deltas
    target_csv_path: str
    target_csv_date: str  # from filename
    account_id: Optional[str]


_CSV_DATE_PATTERN = re.compile(r"portfolio_(\d{8})")


def find_latest_target_csv(search_dir: Path) -> Optional[Path]:
    """Find the most recent portfolio_YYYYMMDD.csv, excluding *_actual* files."""
    candidates = [
        p
        for p in search_dir.glob("portfolio_????????.csv")
        if "_actual" not in p.stem
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stem, reverse=True)
    return candidates[0]


def reconcile(live: Portfolio, target: Portfolio, tolerance: int = 1) -> List[PositionDrift]:
    """Compare live vs target portfolios and return per-ticker drift info."""
    live_map = {p.ticker: p for p in live.positions}
    target_map = {p.ticker: p for p in target.positions}

    live_total = sum(p.shares * p.cost_basis for p in live.positions)
    target_total = sum(p.shares * p.cost_basis for p in target.positions)

    all_tickers = sorted(set(live_map) | set(target_map))
    drifts: List[PositionDrift] = []

    for ticker in all_tickers:
        live_pos = live_map.get(ticker)
        target_pos = target_map.get(ticker)

        live_shares = live_pos.shares if live_pos else 0.0
        target_shares = target_pos.shares if target_pos else 0.0
        shares_delta = live_shares - target_shares

        live_value = (live_pos.shares * live_pos.cost_basis) if live_pos else 0.0
        target_value = (target_pos.shares * target_pos.cost_basis) if target_pos else 0.0

        live_weight = (live_value / live_total * 100) if live_total else 0.0
        target_weight = (target_value / target_total * 100) if target_total else 0.0
        weight_delta = live_weight - target_weight

        currency = (live_pos or target_pos).currency

        if target_pos and not live_pos:
            status = "missing_live"
        elif live_pos and not target_pos:
            status = "extra_live"
        elif abs(shares_delta) <= tolerance:
            status = "match"
        else:
            status = "drift"

        drifts.append(
            PositionDrift(
                ticker=ticker,
                status=status,
                live_shares=live_shares,
                target_shares=target_shares,
                shares_delta=shares_delta,
                live_weight=live_weight,
                target_weight=target_weight,
                weight_delta=weight_delta,
                currency=currency,
            )
        )

    return drifts


def compute_drift_score(drifts: List[PositionDrift]) -> float:
    """RMS of weight_delta across all positions (as percentage points)."""
    if not drifts:
        return 0.0
    sum_sq = sum(d.weight_delta ** 2 for d in drifts)
    return math.sqrt(sum_sq / len(drifts))


def _extract_date_from_csv(csv_path: Path) -> str:
    """Extract YYYYMMDD date string from a portfolio CSV filename."""
    m = _CSV_DATE_PATTERN.search(csv_path.stem)
    if m:
        raw = m.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return "unknown"


def build_result(
    live: Portfolio,
    target: Portfolio,
    csv_path: Path,
    account_id: Optional[str],
    tolerance: int = 1,
) -> ReconciliationResult:
    """Orchestrate reconciliation and return a full result."""
    drifts = reconcile(live, target, tolerance=tolerance)
    return ReconciliationResult(
        live_count=len(live.positions),
        target_count=len(target.positions),
        drifts=drifts,
        drift_score=compute_drift_score(drifts),
        target_csv_path=str(csv_path),
        target_csv_date=_extract_date_from_csv(csv_path),
        account_id=account_id,
    )
