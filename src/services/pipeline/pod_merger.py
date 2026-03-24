"""Pod merger: combine N pod proposals into one merged portfolio."""

from typing import Dict, List

from src.services.pipeline.pod_proposer import PodProposal


def merge_proposals(
    proposals: List[PodProposal],
    max_holdings: int = 8,
) -> Dict[str, float]:
    """Equal-weight merge of pod proposals into a single portfolio.

    Each pod gets 1/N of total weight. Overlapping tickers are summed
    (consensus picks get amplified). If unique tickers > max_holdings,
    the lowest-weight tickers are dropped and weights re-normalized.

    Returns dict mapping ticker -> target weight (sums to ~1.0).
    """
    if not proposals:
        return {}

    active = [p for p in proposals if p.picks]
    if not active:
        return {}

    pod_weight = 1.0 / len(active)

    # Accumulate per-ticker weights across all pods
    merged: Dict[str, float] = {}
    for proposal in active:
        for pick in proposal.picks:
            ticker = pick.ticker
            scaled_weight = pick.target_weight * pod_weight
            merged[ticker] = merged.get(ticker, 0.0) + scaled_weight

    # Apply max_holdings constraint
    if len(merged) > max_holdings:
        sorted_tickers = sorted(merged.items(), key=lambda x: x[1], reverse=True)
        merged = dict(sorted_tickers[:max_holdings])

    # Re-normalize to sum to 1.0
    total = sum(merged.values())
    if total > 0 and abs(total - 1.0) > 0.001:
        merged = {t: w / total for t, w in merged.items()}

    return merged
