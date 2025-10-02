"""Tests for analyst signal caching."""

import tempfile
from pathlib import Path

import pytest

from src.data.analysis_cache import AnalysisCache


@pytest.fixture()
def temp_analysis_cache():
    """Provide an isolated analysis cache backed by a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    cache = AnalysisCache(db_path=db_path)
    try:
        yield cache
    finally:
        db_path.unlink(missing_ok=True)


def test_cache_miss(temp_analysis_cache):
    """Missing entries should return None."""
    result = temp_analysis_cache.get_cached_analysis(
        ticker="AAPL",
        analyst_name="fundamentals_analyst",
        analysis_date="2025-10-02",
        model_name="gpt-5-nano",
        model_provider="openai",
    )
    assert result is None


def test_store_and_retrieve(temp_analysis_cache):
    """Stored analyses should be retrievable with identical keys."""
    temp_analysis_cache.store_analysis(
        ticker="AAPL",
        analyst_name="fundamentals_analyst",
        analysis_date="2025-10-02",
        model_name="gpt-5-nano",
        model_provider="openai",
        signal="bullish",
        signal_numeric=1.0,
        confidence=0.85,
        reasoning="Robust earnings momentum",
    )

    cached = temp_analysis_cache.get_cached_analysis(
        ticker="AAPL",
        analyst_name="fundamentals_analyst",
        analysis_date="2025-10-02",
        model_name="gpt-5-nano",
        model_provider="openai",
    )

    assert cached is not None
    assert cached.signal == "bullish"
    assert cached.signal_numeric == pytest.approx(1.0)
    assert cached.confidence == pytest.approx(0.85)
    assert cached.reasoning == "Robust earnings momentum"


def test_overwrites_existing_entry(temp_analysis_cache):
    """Storing with the same key replaces the previous payload."""
    key_kwargs = {
        "ticker": "MSFT",
        "analyst_name": "technical_analyst",
        "analysis_date": "2025-10-02",
        "model_name": "gpt-4o",
        "model_provider": "openai",
    }
    temp_analysis_cache.store_analysis(
        **key_kwargs,
        signal="neutral",
        signal_numeric=0.0,
        confidence=0.4,
        reasoning="Initial read",
    )
    temp_analysis_cache.store_analysis(
        **key_kwargs,
        signal="bearish",
        signal_numeric=-0.5,
        confidence=0.6,
        reasoning="Updated after new data",
    )

    cached = temp_analysis_cache.get_cached_analysis(**key_kwargs)
    assert cached is not None
    assert cached.signal == "bearish"
    assert cached.signal_numeric == pytest.approx(-0.5)
    assert cached.confidence == pytest.approx(0.6)
    assert cached.reasoning == "Updated after new data"


def test_model_specific_keys(temp_analysis_cache):
    """Different model names should create isolated cache entries."""
    base_kwargs = {
        "ticker": "GOOG",
        "analyst_name": "valuation_analyst",
        "analysis_date": "2025-10-02",
    }
    temp_analysis_cache.store_analysis(
        **base_kwargs,
        model_name="gpt-4o",
        model_provider="openai",
        signal="bullish",
        signal_numeric=0.9,
        confidence=0.7,
        reasoning="DCF upside",
    )
    temp_analysis_cache.store_analysis(
        **base_kwargs,
        model_name="claude-3",
        model_provider="anthropic",
        signal="bearish",
        signal_numeric=-0.2,
        confidence=0.55,
        reasoning="Valuation stretched",
    )

    cached_openai = temp_analysis_cache.get_cached_analysis(
        **base_kwargs,
        model_name="gpt-4o",
        model_provider="openai",
    )
    cached_anthropic = temp_analysis_cache.get_cached_analysis(
        **base_kwargs,
        model_name="claude-3",
        model_provider="anthropic",
    )

    assert cached_openai is not None
    assert cached_openai.signal == "bullish"
    assert cached_anthropic is not None
    assert cached_anthropic.signal == "bearish"


def test_ticker_normalisation(temp_analysis_cache):
    """Ticker lookups should be case-insensitive."""
    temp_analysis_cache.store_analysis(
        ticker="abbv",
        analyst_name="sentiment_analyst",
        analysis_date="2025-10-02",
        model_name="deterministic",
        model_provider="deterministic",
        signal="neutral",
        signal_numeric=0.0,
        confidence=0.5,
        reasoning="Stable sentiment",
    )

    cached = temp_analysis_cache.get_cached_analysis(
        ticker="ABBV",
        analyst_name="sentiment_analyst",
        analysis_date="2025-10-02",
        model_name="deterministic",
        model_provider="deterministic",
    )

    assert cached is not None
    assert cached.signal == "neutral"
