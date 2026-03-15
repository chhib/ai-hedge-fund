"""Tests for the analyst scorecard scoring engine."""

from src.analytics.scorecard import (
    SignalOutcome,
    forward_return,
    evaluate_signals,
    score_analysts,
)
from src.data.analysis_cache import CachedAnalystSignal


def _make_signal(
    ticker="AAPL",
    analyst="technical_analyst",
    date="2025-10-02",
    signal_numeric=0.5,
    confidence=0.8,
):
    return CachedAnalystSignal(
        ticker=ticker,
        analyst_name=analyst,
        analysis_date=date,
        model_name="test",
        model_provider="test",
        signal="bullish" if signal_numeric > 0 else ("bearish" if signal_numeric < 0 else "neutral"),
        signal_numeric=signal_numeric,
        confidence=confidence,
        reasoning="",
    )


def _make_outcome(
    analyst="technical_analyst",
    signal_numeric=0.5,
    forward_ret=0.05,
    direction_correct=True,
):
    return SignalOutcome(
        ticker="AAPL",
        analyst_name=analyst,
        analysis_date="2025-10-02",
        signal_numeric=signal_numeric,
        confidence=0.8,
        forward_return=forward_ret,
        direction_correct=direction_correct,
    )


# --- forward_return tests ---

def test_forward_return_basic():
    """Known prices produce correct return."""
    index = {"AAPL": [("2025-10-01", 100.0), ("2025-10-02", 102.0), ("2025-10-03", 105.0)]}
    result = forward_return(index, "AAPL", "2025-10-01", 2)
    assert result == (105.0 - 100.0) / 100.0  # 0.05


def test_forward_return_weekend_alignment():
    """Signal on a non-trading day finds the next available trading day."""
    index = {"AAPL": [("2025-10-06", 100.0), ("2025-10-07", 103.0), ("2025-10-08", 106.0)]}
    # Signal on Saturday 2025-10-04 -- should snap to 2025-10-06
    result = forward_return(index, "AAPL", "2025-10-04", 1)
    assert result == (103.0 - 100.0) / 100.0  # 0.03


def test_forward_return_insufficient_data():
    """Returns None when not enough trading days after entry."""
    index = {"AAPL": [("2025-10-01", 100.0), ("2025-10-02", 102.0)]}
    result = forward_return(index, "AAPL", "2025-10-01", 5)
    assert result is None


def test_forward_return_missing_ticker():
    """Returns None for a ticker not in the index."""
    result = forward_return({}, "AAPL", "2025-10-01", 1)
    assert result is None


# --- direction correctness tests ---

def test_direction_correct_bullish_up():
    """Bullish signal + positive return = correct."""
    signals = [_make_signal(signal_numeric=0.5, date="2025-10-02")]
    signals.append(_make_signal(date="2025-10-03"))  # need 2nd date so latest is excluded

    index = {"AAPL": [("2025-10-02", 100.0), ("2025-10-03", 100.0), ("2025-10-04", 100.0),
                       ("2025-10-05", 100.0), ("2025-10-06", 100.0), ("2025-10-07", 100.0),
                       ("2025-10-08", 100.0), ("2025-10-09", 110.0)]}
    outcomes = evaluate_signals(signals, index, 7)
    assert len(outcomes) == 1
    assert outcomes[0].direction_correct is True


def test_direction_correct_bearish_down():
    """Bearish signal + negative return = correct."""
    signals = [_make_signal(signal_numeric=-0.5, date="2025-10-02")]
    signals.append(_make_signal(date="2025-10-03"))

    index = {"AAPL": [("2025-10-02", 100.0), ("2025-10-03", 100.0), ("2025-10-04", 100.0),
                       ("2025-10-05", 100.0), ("2025-10-06", 100.0), ("2025-10-07", 100.0),
                       ("2025-10-08", 100.0), ("2025-10-09", 90.0)]}
    outcomes = evaluate_signals(signals, index, 7)
    assert len(outcomes) == 1
    assert outcomes[0].direction_correct is True


def test_direction_correct_wrong():
    """Bullish signal + negative return = incorrect."""
    signals = [_make_signal(signal_numeric=0.8, date="2025-10-02")]
    signals.append(_make_signal(date="2025-10-03"))

    index = {"AAPL": [("2025-10-02", 100.0), ("2025-10-03", 100.0), ("2025-10-04", 100.0),
                       ("2025-10-05", 100.0), ("2025-10-06", 100.0), ("2025-10-07", 100.0),
                       ("2025-10-08", 100.0), ("2025-10-09", 90.0)]}
    outcomes = evaluate_signals(signals, index, 7)
    assert len(outcomes) == 1
    assert outcomes[0].direction_correct is False


# --- neutral handling ---

def test_neutral_excluded():
    """Neutral signals (signal_numeric=0) are excluded from hit_rate."""
    outcomes = [
        _make_outcome(signal_numeric=0.0, forward_ret=0.05, direction_correct=False),
        _make_outcome(signal_numeric=0.5, forward_ret=0.05, direction_correct=True),
        _make_outcome(signal_numeric=-0.3, forward_ret=-0.02, direction_correct=True),
    ]
    scores = score_analysts(outcomes)
    assert len(scores) == 1
    s = scores[0]
    assert s.neutral_skipped == 1
    assert s.evaluated == 2
    assert s.hit_rate == 1.0  # 2/2 correct


# --- credibility tests ---

def test_credibility_no_data():
    """Zero non-neutral observations -> credibility 1.0 (neutral)."""
    outcomes = [_make_outcome(signal_numeric=0.0, forward_ret=0.01, direction_correct=False)]
    scores = score_analysts(outcomes)
    assert scores[0].credibility == 1.0


def test_credibility_perfect_accuracy():
    """All correct with large N -> credibility approaches 2.0."""
    outcomes = [_make_outcome(signal_numeric=0.5, forward_ret=0.05, direction_correct=True) for _ in range(200)]
    scores = score_analysts(outcomes)
    # shrunk = (200+10)/(200+20) = 210/220 ≈ 0.9545, cred = 0.9545/0.5 ≈ 1.91
    assert scores[0].credibility > 1.9


def test_credibility_zero_accuracy():
    """All wrong with large N -> credibility approaches 0.2 (floor)."""
    outcomes = [_make_outcome(signal_numeric=0.5, forward_ret=-0.05, direction_correct=False) for _ in range(200)]
    scores = score_analysts(outcomes)
    assert scores[0].credibility == 0.2


def test_credibility_bayesian_shrinkage():
    """Small N pulls credibility toward 1.0 even with perfect accuracy."""
    # 3 correct out of 3 -- without shrinkage would be 2.0
    outcomes = [_make_outcome(signal_numeric=0.5, forward_ret=0.05, direction_correct=True) for _ in range(3)]
    scores = score_analysts(outcomes)
    s = scores[0]
    # shrunk = (3 + 10) / (3 + 20) = 13/23 ≈ 0.565
    # credibility = 0.565 / 0.5 = 1.13
    assert 1.1 < s.credibility < 1.2


# --- alpha and conviction ---

def test_avg_alpha_calculation():
    """Known signals + returns -> expected alpha."""
    outcomes = [
        _make_outcome(signal_numeric=0.5, forward_ret=0.10, direction_correct=True),
        _make_outcome(signal_numeric=-0.3, forward_ret=-0.05, direction_correct=True),
    ]
    scores = score_analysts(outcomes)
    # alpha_1 = 0.5 * 0.10 = 0.05
    # alpha_2 = -0.3 * -0.05 = 0.015
    # avg = (0.05 + 0.015) / 2 = 0.0325
    assert abs(scores[0].avg_alpha - 0.0325) < 1e-6


def test_conviction_rate():
    """Mix of neutral and non-neutral -> correct conviction rate."""
    outcomes = [
        _make_outcome(signal_numeric=0.5, forward_ret=0.05, direction_correct=True),
        _make_outcome(signal_numeric=0.0, forward_ret=0.01, direction_correct=False),
        _make_outcome(signal_numeric=-0.3, forward_ret=-0.02, direction_correct=True),
        _make_outcome(signal_numeric=0.0, forward_ret=0.03, direction_correct=False),
    ]
    scores = score_analysts(outcomes)
    assert scores[0].conviction_rate == 0.5  # 2 non-neutral / 4 total


# --- multi-analyst ---

def test_multiple_analysts():
    """Separate scoring per analyst from shared outcomes."""
    outcomes = [
        _make_outcome(analyst="technical_analyst", signal_numeric=0.5, forward_ret=0.05, direction_correct=True),
        _make_outcome(analyst="technical_analyst", signal_numeric=0.5, forward_ret=-0.02, direction_correct=False),
        _make_outcome(analyst="fundamentals_analyst", signal_numeric=-0.3, forward_ret=-0.05, direction_correct=True),
    ]
    scores = score_analysts(outcomes)
    by_name = {s.analyst_name: s for s in scores}

    assert len(by_name) == 2
    assert by_name["technical_analyst"].evaluated == 2
    assert by_name["technical_analyst"].hit_rate == 0.5
    assert by_name["fundamentals_analyst"].evaluated == 1
    assert by_name["fundamentals_analyst"].hit_rate == 1.0


# --- latest date exclusion ---

def test_latest_date_excluded():
    """Most recent analysis date is skipped (no forward data available yet)."""
    signals = [
        _make_signal(date="2025-10-02"),
        _make_signal(date="2025-10-09"),
        _make_signal(date="2025-10-16"),  # latest -- should be excluded
    ]
    index = {"AAPL": [(f"2025-10-{d:02d}", 100.0 + d) for d in range(1, 25)]}
    outcomes = evaluate_signals(signals, index, 1)

    dates_in_outcomes = {o.analysis_date for o in outcomes}
    assert "2025-10-16" not in dates_in_outcomes
    assert "2025-10-02" in dates_in_outcomes
    assert "2025-10-09" in dates_in_outcomes
