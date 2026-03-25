"""Price-drift validation for Phase 2 daemon execution.

Compares current market prices against Phase 1 proposal prices.
Trades exceeding the drift threshold are skipped with a reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DRIFT_THRESHOLD = 0.05  # 5% absolute price change


@dataclass(slots=True)
class DriftResult:
    ticker: str
    proposal_price: float
    current_price: float
    drift_pct: float
    exceeds_threshold: bool
    skip_reason: Optional[str] = None


def validate_price_drift(
    proposals: List[Dict[str, Any]],
    current_prices: Dict[str, float],
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> List[DriftResult]:
    """Check each proposal ticker for price drift since Phase 1.

    Returns a DriftResult per proposal ticker:
      - exceeds_threshold=False -> trade can proceed
      - exceeds_threshold=True -> trade should be skipped

    Tickers with missing current prices are always marked as exceeding threshold.
    """
    results = []
    for proposal in proposals:
        ticker = proposal.get("ticker", "")
        proposal_price = proposal.get("target_weight", 0.0)  # weight, not price
        # Use limit_price or latest_close from the proposal as the reference price
        ref_price = proposal.get("limit_price") or proposal.get("latest_close") or proposal.get("signal_score")

        current = current_prices.get(ticker)

        if current is None or ref_price is None:
            results.append(DriftResult(
                ticker=ticker,
                proposal_price=ref_price or 0.0,
                current_price=0.0,
                drift_pct=0.0,
                exceeds_threshold=True,
                skip_reason=f"Missing current price for {ticker}",
            ))
            continue

        if ref_price == 0:
            results.append(DriftResult(
                ticker=ticker,
                proposal_price=0.0,
                current_price=current,
                drift_pct=0.0,
                exceeds_threshold=True,
                skip_reason=f"Zero reference price for {ticker}",
            ))
            continue

        drift = abs(current - ref_price) / ref_price
        exceeds = drift > threshold

        results.append(DriftResult(
            ticker=ticker,
            proposal_price=ref_price,
            current_price=current,
            drift_pct=drift,
            exceeds_threshold=exceeds,
            skip_reason=f"Price drift {drift:.1%} exceeds {threshold:.1%} threshold" if exceeds else None,
        ))

    return results


def filter_proposals_by_drift(
    proposals: List[Dict[str, Any]],
    current_prices: Dict[str, float],
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> tuple[List[Dict[str, Any]], List[DriftResult]]:
    """Split proposals into valid (within drift) and skipped (exceeds drift).

    Returns (valid_proposals, all_drift_results).
    """
    drift_results = validate_price_drift(proposals, current_prices, threshold)
    skip_tickers = {r.ticker for r in drift_results if r.exceeds_threshold}

    valid = [p for p in proposals if p.get("ticker", "") not in skip_tickers]
    return valid, drift_results
