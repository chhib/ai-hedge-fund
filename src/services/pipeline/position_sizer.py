"""Position sizing: select top positions and calculate target weights."""

from typing import Dict, List


def select_top_positions(
    scores: Dict[str, float],
    max_holdings: int,
    min_score_threshold: float = 0.5,
) -> List[str]:
    """Select top N tickers by score, filtering below threshold.

    Path-independent: selects best positions regardless of current holdings.
    """
    qualified = {t: s for t, s in scores.items() if s >= min_score_threshold}
    sorted_tickers = sorted(qualified.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_tickers[:max_holdings]]


def calculate_target_positions(
    selected_tickers: List[str],
    scores: Dict[str, float],
    max_position: float,
    min_position: float,
) -> Dict[str, float]:
    """Calculate target portfolio weights for selected tickers.

    Score-proportional allocation with min/max constraints and residual
    capacity distribution.
    """
    if not selected_tickers:
        return {}

    selected_scores = {t: scores[t] for t in selected_tickers}
    total_score = sum(selected_scores.values())
    if total_score == 0:
        return {}

    count = len(selected_tickers)
    effective_max = max(max_position, 1.0 / count)
    effective_max = min(effective_max, 1.0)

    target_weights: Dict[str, float] = {}
    for ticker in selected_tickers:
        base_weight = selected_scores[ticker] / total_score
        if base_weight > effective_max:
            weight = effective_max
        elif base_weight < min_position:
            weight = min_position
        else:
            weight = base_weight
        target_weights[ticker] = weight

    total_weight = sum(target_weights.values())

    # Scale down if overweight
    if total_weight > 1.0:
        for ticker in target_weights:
            target_weights[ticker] /= total_weight
        total_weight = sum(target_weights.values())

    # Distribute residual capacity
    if total_weight < 1.0:
        residual = 1.0 - total_weight
        capacities = {t: max(0.0, effective_max - w) for t, w in target_weights.items()}
        capacity_total = sum(capacities.values())

        if capacity_total > 0 and residual > 0:
            for ticker, capacity in capacities.items():
                if capacity <= 0:
                    continue
                addition = residual * (capacity / capacity_total)
                addition = min(addition, capacity)
                target_weights[ticker] += addition

    return target_weights
