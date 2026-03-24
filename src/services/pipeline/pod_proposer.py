"""Pod proposer: synthesize per-ticker analyst signals into a ranked portfolio proposal."""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.agents.enhanced_portfolio_manager import AnalystSignal
from src.config.pod_config import Pod


@dataclass(slots=True)
class PodPick:
    rank: int
    ticker: str
    target_weight: float
    signal_score: float


@dataclass(slots=True)
class PodProposal:
    pod_id: str
    run_id: str
    picks: List[PodPick]
    reasoning: Optional[str] = None


class PortfolioProposalOutput(BaseModel):
    """Structured output for LLM portfolio proposal."""
    picks: List[Dict[str, Any]] = Field(description="Ranked list of picks with ticker, weight (0-1), and brief rationale")
    reasoning: str = Field(description="Overall portfolio thesis explaining the selection")


def propose_portfolio(
    pod: Pod,
    signals: List[AnalystSignal],
    run_id: str,
    model_config: Dict[str, Any],
) -> PodProposal:
    """Route to LLM or deterministic proposer based on analyst type."""
    from src.utils.analysts import ANALYST_CONFIG

    analyst_config = ANALYST_CONFIG.get(pod.analyst, {})
    uses_llm = analyst_config.get("uses_llm", True)

    if uses_llm:
        try:
            return _propose_portfolio_llm(pod, signals, run_id, model_config, analyst_config)
        except Exception as e:
            print(f"  Warning: LLM proposal failed for pod {pod.name}: {e}")
            print(f"  Falling back to deterministic proposal")
            return _propose_portfolio_deterministic(pod, signals, run_id)
    else:
        return _propose_portfolio_deterministic(pod, signals, run_id)


def _propose_portfolio_llm(
    pod: Pod,
    signals: List[AnalystSignal],
    run_id: str,
    model_config: Dict[str, Any],
    analyst_config: Dict[str, Any],
) -> PodProposal:
    """Second LLM call: synthesize per-ticker signals into a ranked portfolio."""
    from src.utils.llm import call_llm

    display_name = analyst_config.get("display_name", pod.analyst)
    description = analyst_config.get("description", "")
    style = analyst_config.get("investing_style", "")

    signal_summary = []
    for sig in sorted(signals, key=lambda s: abs(s.signal) * s.confidence, reverse=True):
        direction = "BULLISH" if sig.signal > 0 else ("BEARISH" if sig.signal < 0 else "NEUTRAL")
        signal_summary.append(
            f"- {sig.ticker}: {direction} (signal={sig.signal:.2f}, confidence={sig.confidence:.2f})"
            f"\n  Reasoning: {sig.reasoning[:200]}..."
            if len(sig.reasoning) > 200 else
            f"- {sig.ticker}: {direction} (signal={sig.signal:.2f}, confidence={sig.confidence:.2f})"
            f"\n  Reasoning: {sig.reasoning}"
        )

    prompt = f"""You are {display_name}, a portfolio manager.

{description}
{f"Investment style: {style}" if style else ""}

You have analyzed the following tickers and produced these signals:

{chr(10).join(signal_summary)}

Based on your analysis, propose your TOP {pod.max_picks} portfolio picks.
Rules:
- Long-only (no short positions)
- Weights must sum to approximately 1.0
- Only include tickers from the analysis above
- Rank by conviction (rank 1 = highest conviction)
- Provide a brief portfolio thesis explaining your selection

Return your picks as a JSON list with fields: ticker, weight (0.0 to 1.0), rank (1-based).
"""

    # Build a minimal state for call_llm model config extraction
    state = {
        "messages": [],
        "data": {"model_config": model_config},
        "metadata": {},
    }

    result = call_llm(
        prompt=prompt,
        pydantic_model=PortfolioProposalOutput,
        agent_name=f"{pod.analyst}_agent",
        state=state,
    )

    # Validate and build picks
    ticker_signal_map = {s.ticker: s for s in signals}
    picks = []
    total_weight = 0.0

    for i, pick_data in enumerate(result.picks[:pod.max_picks]):
        ticker = pick_data.get("ticker", "")
        weight = float(pick_data.get("weight", 0.0))
        rank = int(pick_data.get("rank", i + 1))

        if ticker not in ticker_signal_map:
            continue

        total_weight += weight
        sig = ticker_signal_map[ticker]
        picks.append(PodPick(
            rank=rank,
            ticker=ticker,
            target_weight=weight,
            signal_score=sig.signal,
        ))

    # Normalize weights if they don't sum to ~1.0
    if picks and abs(total_weight - 1.0) > 0.05:
        for pick in picks:
            pick.target_weight /= total_weight

    # Sort by rank
    picks.sort(key=lambda p: p.rank)

    return PodProposal(
        pod_id=pod.name,
        run_id=run_id,
        picks=picks,
        reasoning=result.reasoning,
    )


def _propose_portfolio_deterministic(
    pod: Pod,
    signals: List[AnalystSignal],
    run_id: str,
) -> PodProposal:
    """Rank tickers by score, take top N, assign proportional weights."""
    # Sort by |signal| * confidence descending
    ranked = sorted(signals, key=lambda s: abs(s.signal) * s.confidence, reverse=True)
    top = ranked[:pod.max_picks]

    if not top:
        return PodProposal(pod_id=pod.name, run_id=run_id, picks=[])

    # Proportional weights from scores
    scores = [abs(s.signal) * s.confidence for s in top]
    total = sum(scores)
    if total == 0:
        weights = [1.0 / len(top)] * len(top)
    else:
        weights = [s / total for s in scores]

    picks = [
        PodPick(
            rank=i + 1,
            ticker=sig.ticker,
            target_weight=w,
            signal_score=sig.signal,
        )
        for i, (sig, w) in enumerate(zip(top, weights))
    ]

    return PodProposal(pod_id=pod.name, run_id=run_id, picks=picks)
