"""Tests for price-drift validation (Phase 2 daemon execution)."""

import pytest

from src.services.price_validator import (
    DEFAULT_DRIFT_THRESHOLD,
    DriftResult,
    filter_proposals_by_drift,
    validate_price_drift,
)


def _proposal(ticker: str, signal_score: float = 100.0) -> dict:
    return {"ticker": ticker, "signal_score": signal_score}


class TestValidatePriceDrift:
    def test_no_drift(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 100.0}
        results = validate_price_drift(proposals, prices)
        assert len(results) == 1
        assert results[0].exceeds_threshold is False
        assert results[0].drift_pct == 0.0

    def test_small_drift_within_threshold(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 103.0}  # 3% drift
        results = validate_price_drift(proposals, prices)
        assert results[0].exceeds_threshold is False
        assert abs(results[0].drift_pct - 0.03) < 0.001

    def test_large_drift_exceeds_threshold(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 110.0}  # 10% drift
        results = validate_price_drift(proposals, prices)
        assert results[0].exceeds_threshold is True
        assert "exceeds" in results[0].skip_reason

    def test_drift_exactly_at_threshold_passes(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 105.0}  # Exactly 5%
        results = validate_price_drift(proposals, prices, threshold=0.05)
        assert results[0].exceeds_threshold is False  # threshold is exclusive

    def test_missing_current_price_exceeds(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {}  # No current price
        results = validate_price_drift(proposals, prices)
        assert results[0].exceeds_threshold is True
        assert "Missing" in results[0].skip_reason

    def test_zero_reference_price_exceeds(self):
        proposals = [{"ticker": "AAPL", "signal_score": 0.0}]
        prices = {"AAPL": 100.0}
        results = validate_price_drift(proposals, prices)
        assert results[0].exceeds_threshold is True
        assert "Zero" in results[0].skip_reason

    def test_custom_threshold(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 102.0}  # 2% drift
        # With 1% threshold, this exceeds
        results = validate_price_drift(proposals, prices, threshold=0.01)
        assert results[0].exceeds_threshold is True

    def test_multiple_tickers(self):
        proposals = [_proposal("AAPL", 100.0), _proposal("TSLA", 200.0)]
        prices = {"AAPL": 100.0, "TSLA": 230.0}  # TSLA 15% drift
        results = validate_price_drift(proposals, prices)
        aapl = next(r for r in results if r.ticker == "AAPL")
        tsla = next(r for r in results if r.ticker == "TSLA")
        assert aapl.exceeds_threshold is False
        assert tsla.exceeds_threshold is True


class TestFilterProposalsByDrift:
    def test_filter_keeps_valid(self):
        proposals = [_proposal("AAPL", 100.0), _proposal("TSLA", 200.0)]
        prices = {"AAPL": 100.0, "TSLA": 230.0}  # TSLA 15% drift
        valid, results = filter_proposals_by_drift(proposals, prices)
        assert len(valid) == 1
        assert valid[0]["ticker"] == "AAPL"

    def test_filter_all_valid(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 101.0}
        valid, results = filter_proposals_by_drift(proposals, prices)
        assert len(valid) == 1

    def test_filter_all_exceeded(self):
        proposals = [_proposal("AAPL", 100.0)]
        prices = {"AAPL": 120.0}  # 20% drift
        valid, results = filter_proposals_by_drift(proposals, prices)
        assert len(valid) == 0
