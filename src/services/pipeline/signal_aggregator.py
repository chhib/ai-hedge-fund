"""Signal aggregation: merge per-analyst signals into per-ticker consensus scores."""

from typing import Dict, List, Optional

from src.agents.enhanced_portfolio_manager import AnalystSignal


def aggregate_signals(
    signals: List[AnalystSignal],
    analyst_weights: Optional[Dict[str, float]] = None,
    universe: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Weighted average of analyst signals per ticker.

    Merges at the ticker level (not dict.update) to avoid the Session 34
    parallel merge bug.

    Returns dict mapping ticker -> aggregated score in [-1, 1].
    """
    ticker_signals: Dict[str, List[AnalystSignal]] = {}

    for signal in signals:
        if signal.ticker not in ticker_signals:
            ticker_signals[signal.ticker] = []
        ticker_signals[signal.ticker].append(signal)

    aggregated: Dict[str, float] = {}
    for ticker, ticker_sigs in ticker_signals.items():
        total_weight = sum(
            s.confidence * (analyst_weights.get(s.analyst, 1.0) if analyst_weights else 1.0)
            for s in ticker_sigs
        )
        if total_weight > 0:
            weighted_sum = sum(
                s.signal * s.confidence * (analyst_weights.get(s.analyst, 1.0) if analyst_weights else 1.0)
                for s in ticker_sigs
            )
            aggregated[ticker] = weighted_sum / total_weight
        else:
            aggregated[ticker] = 0

    if not aggregated and universe:
        for ticker in universe:
            aggregated[ticker] = 0.5

    return aggregated


def apply_long_only_constraint(scores: Dict[str, float]) -> Dict[str, float]:
    """Convert [-1, 1] signals to [0, 1] long-only scores.

    -1 (strong sell) -> 0, 0 (neutral) -> 0.5, 1 (strong buy) -> 1.
    """
    return {ticker: (score + 1) / 2 for ticker, score in scores.items()}


def apply_ticker_penalties(
    scores: Dict[str, float],
    ticker_penalties: Dict[str, float],
) -> Dict[str, float]:
    """Apply governor ticker penalties to scores."""
    return {ticker: score * ticker_penalties.get(ticker, 1.0) for ticker, score in scores.items()}
