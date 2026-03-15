"""Analyst performance attribution scorecard.

Evaluates each analyst's historical predictions against actual price outcomes,
producing accuracy metrics and a credibility score.
"""

from __future__ import annotations

import bisect
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Literal, Optional

from src.data.analysis_cache import CachedAnalystSignal

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "prefetch_cache.db"
RegimeLabel = Literal["trend_up", "trend_down", "high_vol", "low_vol"]


@dataclass
class SignalOutcome:
    ticker: str
    analyst_name: str
    analysis_date: str
    signal_numeric: float
    confidence: float
    forward_return: float
    direction_correct: bool


@dataclass
class AnalystScore:
    analyst_name: str
    display_name: str
    total_signals: int
    evaluated: int
    neutral_skipped: int
    hit_rate: float
    credibility: float
    avg_alpha: float
    conviction_rate: float


@dataclass
class ScorecardResult:
    analyst_scores: list[AnalystScore]
    date_range: str
    evaluable_dates: int
    horizon: int
    total_outcomes: int


@dataclass
class RegimeScorecardResult:
    analyst_scores: list[AnalystScore]
    regime_scores: dict[RegimeLabel, list[AnalystScore]]
    benchmark_ticker: str
    regime_by_date: dict[str, RegimeLabel]
    date_range: str
    evaluable_dates: int
    horizon: int
    total_outcomes: int


def load_all_signals(db_path: Path = _DEFAULT_DB_PATH) -> list[CachedAnalystSignal]:
    """Load all cached analyst signals from the analysis_cache table."""
    signals: list[CachedAnalystSignal] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, analyst_name, analysis_date, model_name, model_provider, payload FROM analysis_cache"
        ).fetchall()

    for row in rows:
        payload = json.loads(row["payload"])
        signals.append(
            CachedAnalystSignal(
                ticker=row["ticker"],
                analyst_name=row["analyst_name"],
                analysis_date=row["analysis_date"],
                model_name=row["model_name"],
                model_provider=row["model_provider"],
                signal=payload.get("signal", "neutral"),
                signal_numeric=float(payload.get("signal_numeric", 0.0)),
                confidence=float(payload.get("confidence", 0.0)),
                reasoning=payload.get("reasoning", ""),
            )
        )
    return signals


def build_price_index(
    tickers: list[str], start: str, end: str
) -> dict[str, list[tuple[str, float]]]:
    """Build {ticker: [(date_str, close), ...]} sorted by date.

    Uses get_prices from the API layer (with Borsdata caching).
    """
    from src.data.borsdata_ticker_mapping import get_ticker_market
    from src.tools.api import get_prices, set_ticker_markets

    markets: dict[str, str] = {}
    for t in tickers:
        market = get_ticker_market(t)
        markets[t] = (market or "global").lower()
    set_ticker_markets(markets)

    index: dict[str, list[tuple[str, float]]] = {}
    for ticker in tickers:
        try:
            prices = get_prices(ticker, start, end)
        except Exception as exc:
            logger.warning("Price fetch failed for %s: %s", ticker, exc)
            continue
        if not prices:
            continue
        entries: list[tuple[str, float]] = []
        for p in prices:
            date_str = p.time.split("T")[0] if "T" in p.time else p.time
            entries.append((date_str, p.close))
        entries.sort(key=lambda x: x[0])
        index[ticker] = entries
    return index


def forward_return(
    price_index: dict[str, list[tuple[str, float]]],
    ticker: str,
    signal_date: str,
    horizon: int,
) -> Optional[float]:
    """Compute the forward return for a ticker from signal_date over horizon trading days.

    Returns (exit_close - entry_close) / entry_close, or None if insufficient data.
    """
    entries = price_index.get(ticker)
    if not entries:
        return None

    dates = [e[0] for e in entries]
    entry_idx = bisect.bisect_left(dates, signal_date)
    if entry_idx >= len(entries):
        return None

    exit_idx = entry_idx + horizon
    if exit_idx >= len(entries):
        return None

    entry_close = entries[entry_idx][1]
    exit_close = entries[exit_idx][1]

    if entry_close == 0:
        return None

    return (exit_close - entry_close) / entry_close


def evaluate_signals(
    signals: list[CachedAnalystSignal],
    price_index: dict[str, list[tuple[str, float]]],
    horizon: int,
) -> list[SignalOutcome]:
    """Evaluate signals against actual price outcomes.

    Excludes the most recent analysis date (no forward data yet).
    """
    if not signals:
        return []

    analysis_dates = sorted(set(s.analysis_date for s in signals))
    if len(analysis_dates) < 2:
        return []

    latest_date = analysis_dates[-1]

    outcomes: list[SignalOutcome] = []
    for sig in signals:
        if sig.analysis_date == latest_date:
            continue

        fwd = forward_return(price_index, sig.ticker, sig.analysis_date, horizon)
        if fwd is None:
            continue

        direction_correct = (sig.signal_numeric > 0 and fwd > 0) or (
            sig.signal_numeric < 0 and fwd < 0
        )

        outcomes.append(
            SignalOutcome(
                ticker=sig.ticker,
                analyst_name=sig.analyst_name,
                analysis_date=sig.analysis_date,
                signal_numeric=sig.signal_numeric,
                confidence=sig.confidence,
                forward_return=fwd,
                direction_correct=direction_correct,
            )
        )
    return outcomes


def score_analysts(outcomes: list[SignalOutcome]) -> list[AnalystScore]:
    """Compute per-analyst accuracy, credibility, alpha, and conviction."""
    from src.utils.analysts import ANALYST_CONFIG

    grouped: dict[str, list[SignalOutcome]] = {}
    for o in outcomes:
        grouped.setdefault(o.analyst_name, []).append(o)

    scores: list[AnalystScore] = []
    for analyst_name, analyst_outcomes in grouped.items():
        total = len(analyst_outcomes)
        non_neutral = [o for o in analyst_outcomes if o.signal_numeric != 0]
        neutral_skipped = total - len(non_neutral)

        if non_neutral:
            hits = sum(1 for o in non_neutral if o.direction_correct)
            hit_rate = hits / len(non_neutral)
            shrunk = (hits + 10) / (len(non_neutral) + 20)
            credibility = max(0.2, min(2.0, shrunk / 0.5))
            avg_alpha = sum(o.signal_numeric * o.forward_return for o in non_neutral) / len(non_neutral)
        else:
            hit_rate = 0.0
            credibility = 1.0
            avg_alpha = 0.0

        conviction_rate = len(non_neutral) / total if total > 0 else 0.0

        config = ANALYST_CONFIG.get(analyst_name, {})
        display_name = config.get("display_name", analyst_name)

        scores.append(
            AnalystScore(
                analyst_name=analyst_name,
                display_name=display_name,
                total_signals=total,
                evaluated=len(non_neutral),
                neutral_skipped=neutral_skipped,
                hit_rate=hit_rate,
                credibility=credibility,
                avg_alpha=avg_alpha,
                conviction_rate=conviction_rate,
            )
        )

    scores.sort(key=lambda s: s.credibility, reverse=True)
    return scores


def resolve_benchmark_ticker(ticker_markets: Optional[dict[str, str]] = None) -> str:
    """Select a benchmark ticker aligned with the current universe mix."""
    if not ticker_markets:
        return "OMXS30"

    nordic_count = 0
    global_count = 0
    for market in ticker_markets.values():
        normalized = (market or "").lower()
        if normalized == "nordic":
            nordic_count += 1
        elif normalized == "global":
            global_count += 1

    return "OMXS30" if nordic_count >= global_count else "SPY"


def build_regime_map(
    *,
    benchmark_ticker: str,
    start: str,
    end: str,
) -> dict[str, RegimeLabel]:
    """Classify each benchmark trading day into a simple market regime."""
    price_index = build_price_index([benchmark_ticker], start, end)
    entries = price_index.get(benchmark_ticker, [])
    if len(entries) < 3:
        return {}

    dates = [date_str for date_str, _ in entries]
    closes = [close for _, close in entries]

    daily_returns: list[float] = [0.0]
    for idx in range(1, len(closes)):
        prev_close = closes[idx - 1]
        curr_close = closes[idx]
        if prev_close == 0:
            daily_returns.append(0.0)
        else:
            daily_returns.append((curr_close - prev_close) / prev_close)

    rolling_vols: list[float] = []
    for idx in range(len(closes)):
        window_returns = daily_returns[max(1, idx - 9): idx + 1]
        if len(window_returns) < 2:
            rolling_vols.append(0.0)
            continue
        mean_ret = sum(window_returns) / len(window_returns)
        variance = sum((ret - mean_ret) ** 2 for ret in window_returns) / len(window_returns)
        rolling_vols.append(variance ** 0.5)

    regime_by_date: dict[str, RegimeLabel] = {}
    for idx, date_str in enumerate(dates):
        start_idx = max(0, idx - 19)
        start_close = closes[start_idx]
        trailing_return = 0.0 if start_close == 0 else (closes[idx] - start_close) / start_close

        history_window = rolling_vols[max(0, idx - 59): idx + 1]
        baseline = median(history_window) if history_window else 0.0
        current_vol = rolling_vols[idx]
        vol_ratio = current_vol / baseline if baseline > 1e-9 else 1.0

        if vol_ratio >= 1.25:
            regime_by_date[date_str] = "high_vol"
        elif vol_ratio <= 0.75:
            regime_by_date[date_str] = "low_vol"
        elif trailing_return >= 0:
            regime_by_date[date_str] = "trend_up"
        else:
            regime_by_date[date_str] = "trend_down"

    return regime_by_date


def score_analysts_by_regime(
    outcomes: list[SignalOutcome],
    regime_by_date: dict[str, RegimeLabel],
) -> dict[RegimeLabel, list[AnalystScore]]:
    """Compute separate analyst score tables for each market regime."""
    grouped: dict[RegimeLabel, list[SignalOutcome]] = {
        "trend_up": [],
        "trend_down": [],
        "high_vol": [],
        "low_vol": [],
    }

    for outcome in outcomes:
        regime = regime_by_date.get(outcome.analysis_date)
        if regime:
            grouped[regime].append(outcome)

    return {
        regime: score_analysts(regime_outcomes)
        for regime, regime_outcomes in grouped.items()
        if regime_outcomes
    }


def build_regime_scorecard(
    *,
    horizon: int = 7,
    analyst_names: Optional[list[str]] = None,
    benchmark_ticker: Optional[str] = None,
    ticker_markets: Optional[dict[str, str]] = None,
    db_path: Path = _DEFAULT_DB_PATH,
) -> RegimeScorecardResult:
    """Build overall and regime-specific analyst score lookups for the governor."""
    signals = load_all_signals(db_path)
    if analyst_names:
        selected = {name.lower() for name in analyst_names}
        signals = [signal for signal in signals if signal.analyst_name.lower() in selected]

    if not signals:
        resolved_benchmark = benchmark_ticker or resolve_benchmark_ticker(ticker_markets)
        return RegimeScorecardResult(
            analyst_scores=[],
            regime_scores={},
            benchmark_ticker=resolved_benchmark,
            regime_by_date={},
            date_range="n/a",
            evaluable_dates=0,
            horizon=horizon,
            total_outcomes=0,
        )

    analysis_dates = sorted(set(signal.analysis_date for signal in signals))
    date_range = f"{analysis_dates[0]} to {analysis_dates[-1]}"
    evaluable_dates = max(0, len(analysis_dates) - 1)

    tickers = sorted(set(signal.ticker for signal in signals))
    earliest = analysis_dates[0]
    latest_dt = datetime.strptime(analysis_dates[-1], "%Y-%m-%d")
    end_dt = latest_dt + timedelta(days=horizon * 2)
    end = end_dt.strftime("%Y-%m-%d")

    price_index = build_price_index(tickers, earliest, end)
    outcomes = evaluate_signals(signals, price_index, horizon)
    analyst_scores = score_analysts(outcomes)

    resolved_benchmark = benchmark_ticker or resolve_benchmark_ticker(ticker_markets)
    regime_by_date = build_regime_map(
        benchmark_ticker=resolved_benchmark,
        start=earliest,
        end=end,
    )
    if not regime_by_date and resolved_benchmark != "OMXS30":
        resolved_benchmark = "OMXS30"
        regime_by_date = build_regime_map(
            benchmark_ticker=resolved_benchmark,
            start=earliest,
            end=end,
        )
    regime_scores = score_analysts_by_regime(outcomes, regime_by_date)

    return RegimeScorecardResult(
        analyst_scores=analyst_scores,
        regime_scores=regime_scores,
        benchmark_ticker=resolved_benchmark,
        regime_by_date=regime_by_date,
        date_range=date_range,
        evaluable_dates=evaluable_dates,
        horizon=horizon,
        total_outcomes=len(outcomes),
    )


def run_scorecard(
    horizon: int = 7,
    analyst_filter: Optional[str] = None,
    db_path: Path = _DEFAULT_DB_PATH,
) -> ScorecardResult:
    """Run the full scorecard pipeline: load signals, fetch prices, evaluate, score."""
    analyst_names = [analyst_filter] if analyst_filter else None
    regime_result = build_regime_scorecard(
        horizon=horizon,
        analyst_names=analyst_names,
        db_path=db_path,
    )
    return ScorecardResult(
        analyst_scores=regime_result.analyst_scores,
        date_range=regime_result.date_range,
        evaluable_dates=regime_result.evaluable_dates,
        horizon=regime_result.horizon,
        total_outcomes=regime_result.total_outcomes,
    )
