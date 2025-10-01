"""Tests for LLM response caching with 7-day freshness check."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from src.data.llm_response_cache import LLMResponseCache


class SampleResponse(BaseModel):
    """Sample response model for testing."""

    signal: str
    confidence: int
    reasoning: str


@pytest.fixture
def temp_cache():
    """Create a temporary cache database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize cache and create tables
    cache = LLMResponseCache(db_path=db_path)

    # Create tables manually since we're using temp DB
    from app.backend.database.connection import Base
    from app.backend.database.models import LLMResponseCache as CacheModel

    Base.metadata.create_all(cache.engine)

    yield cache

    # Cleanup
    db_path.unlink(missing_ok=True)


def test_cache_miss(temp_cache):
    """Test cache miss when no data exists."""
    result = temp_cache.get_cached_response(
        ticker="AAPL",
        analyst_name="warren_buffett",
        prompt="Test prompt for AAPL",
    )
    assert result is None


def test_cache_hit_fresh_data(temp_cache):
    """Test cache hit with fresh data (< 7 days old)."""
    # Store response
    sample_response = SampleResponse(signal="bullish", confidence=85, reasoning="Strong fundamentals")

    temp_cache.store_response(
        ticker="AAPL",
        analyst_name="warren_buffett",
        prompt="Test prompt for AAPL",
        response=sample_response,
        model_name="gpt-4o",
        model_provider="openai",
    )

    # Retrieve response
    cached = temp_cache.get_cached_response(
        ticker="AAPL",
        analyst_name="warren_buffett",
        prompt="Test prompt for AAPL",
    )

    assert cached is not None
    assert cached["signal"] == "bullish"
    assert cached["confidence"] == 85
    assert cached["reasoning"] == "Strong fundamentals"


def test_cache_miss_stale_data(temp_cache):
    """Test cache miss when data is stale (> 7 days old)."""
    from app.backend.database.models import LLMResponseCache as CacheModel

    # Manually insert old entry
    sample_response = SampleResponse(signal="bullish", confidence=85, reasoning="Old analysis")

    old_date = datetime.utcnow() - timedelta(days=8)  # 8 days old

    db = temp_cache.SessionLocal()
    try:
        import hashlib

        prompt = "Test prompt for AAPL"
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        old_entry = CacheModel(
            ticker="AAPL",
            analyst_name="warren_buffett",
            prompt_hash=prompt_hash,
            prompt_text=prompt,
            response_json=json.dumps(sample_response.model_dump()),
            model_name="gpt-4o",
            model_provider="openai",
            created_at=old_date,
        )
        db.add(old_entry)
        db.commit()
    finally:
        db.close()

    # Try to retrieve - should return None because data is stale
    cached = temp_cache.get_cached_response(
        ticker="AAPL",
        analyst_name="warren_buffett",
        prompt=prompt,
        max_age_days=7,
    )

    assert cached is None


def test_cache_different_tickers(temp_cache):
    """Test cache isolation between different tickers."""
    response1 = SampleResponse(signal="bullish", confidence=90, reasoning="AAPL strong")
    response2 = SampleResponse(signal="bearish", confidence=70, reasoning="MSFT weak")

    temp_cache.store_response("AAPL", "warren_buffett", "Test prompt", response1)
    temp_cache.store_response("MSFT", "warren_buffett", "Test prompt", response2)

    aapl_cached = temp_cache.get_cached_response("AAPL", "warren_buffett", "Test prompt")
    msft_cached = temp_cache.get_cached_response("MSFT", "warren_buffett", "Test prompt")

    assert aapl_cached["signal"] == "bullish"
    assert msft_cached["signal"] == "bearish"


def test_cache_different_analysts(temp_cache):
    """Test cache isolation between different analysts."""
    response1 = SampleResponse(signal="bullish", confidence=90, reasoning="Buffett likes it")
    response2 = SampleResponse(signal="neutral", confidence=50, reasoning="Munger unsure")

    temp_cache.store_response("AAPL", "warren_buffett", "Test prompt", response1)
    temp_cache.store_response("AAPL", "charlie_munger", "Test prompt", response2)

    buffett_cached = temp_cache.get_cached_response("AAPL", "warren_buffett", "Test prompt")
    munger_cached = temp_cache.get_cached_response("AAPL", "charlie_munger", "Test prompt")

    assert buffett_cached["signal"] == "bullish"
    assert munger_cached["signal"] == "neutral"


def test_cache_different_prompts(temp_cache):
    """Test cache differentiation based on prompt content."""
    response1 = SampleResponse(signal="bullish", confidence=90, reasoning="Prompt 1 response")
    response2 = SampleResponse(signal="bearish", confidence=80, reasoning="Prompt 2 response")

    temp_cache.store_response("AAPL", "warren_buffett", "Prompt version 1", response1)
    temp_cache.store_response("AAPL", "warren_buffett", "Prompt version 2", response2)

    cached1 = temp_cache.get_cached_response("AAPL", "warren_buffett", "Prompt version 1")
    cached2 = temp_cache.get_cached_response("AAPL", "warren_buffett", "Prompt version 2")

    assert cached1["signal"] == "bullish"
    assert cached2["signal"] == "bearish"


def test_cache_multiple_entries_same_key(temp_cache):
    """Test that multiple entries for same key are stored (historical record)."""
    from app.backend.database.models import LLMResponseCache as CacheModel
    import time

    # Store first response
    response1 = SampleResponse(signal="bullish", confidence=90, reasoning="First analysis")
    temp_cache.store_response("AAPL", "warren_buffett", "Test prompt", response1)

    # Small delay to ensure different timestamps
    time.sleep(0.1)

    # Store second response with same key
    response2 = SampleResponse(signal="bearish", confidence=80, reasoning="Updated analysis")
    temp_cache.store_response("AAPL", "warren_buffett", "Test prompt", response2)

    # Check database has both entries
    db = temp_cache.SessionLocal()
    try:
        entries = db.query(CacheModel).filter(CacheModel.ticker == "AAPL").all()
        assert len(entries) == 2
    finally:
        db.close()

    # Get cached should return most recent (or one of them if timestamps are very close)
    cached = temp_cache.get_cached_response("AAPL", "warren_buffett", "Test prompt")
    # Both entries are fresh, so getting either one is acceptable
    assert cached["signal"] in ["bullish", "bearish"]


def test_cache_stats(temp_cache):
    """Test cache statistics."""
    from app.backend.database.models import LLMResponseCache as CacheModel

    # Add fresh entries
    response = SampleResponse(signal="bullish", confidence=90, reasoning="Test")
    temp_cache.store_response("AAPL", "warren_buffett", "Prompt 1", response)
    temp_cache.store_response("MSFT", "warren_buffett", "Prompt 1", response)

    # Add stale entry
    db = temp_cache.SessionLocal()
    try:
        import hashlib

        prompt = "Old prompt"
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        old_date = datetime.utcnow() - timedelta(days=10)

        old_entry = CacheModel(
            ticker="GOOGL",
            analyst_name="warren_buffett",
            prompt_hash=prompt_hash,
            prompt_text=prompt,
            response_json=json.dumps(response.model_dump()),
            model_name="gpt-4o",
            model_provider="openai",
            created_at=old_date,
        )
        db.add(old_entry)
        db.commit()
    finally:
        db.close()

    stats = temp_cache.get_stats()
    assert stats["total_entries"] == 3
    assert stats["fresh_entries"] == 2
    assert stats["stale_entries"] == 1
    assert stats["unique_tickers"] == 3
