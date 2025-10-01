"""
Tests for analyst analysis storage and retrieval.
"""

import uuid
from pathlib import Path

import pytest

from src.data.analysis_storage import export_to_markdown, get_session_analyses, save_analyst_analysis


@pytest.fixture
def test_session_id():
    """Generate a unique session ID for testing."""
    return str(uuid.uuid4())


def test_save_and_retrieve_analysis(test_session_id):
    """Test saving and retrieving a single analyst analysis."""
    # Save a test analysis
    save_analyst_analysis(
        session_id=test_session_id,
        ticker="AAPL",
        analyst_name="warren_buffett",
        signal="bullish",
        signal_numeric=0.8,
        confidence=0.9,
        reasoning="Strong competitive moat and excellent management.",
        model_name="gpt-4o",
        model_provider="openai",
    )

    # Retrieve analyses
    analyses = get_session_analyses(test_session_id)

    # Verify
    assert len(analyses) == 1
    analysis = analyses[0]
    assert analysis["session_id"] == test_session_id
    assert analysis["ticker"] == "AAPL"
    assert analysis["analyst_name"] == "warren_buffett"
    assert analysis["signal"] == "bullish"
    assert analysis["signal_numeric"] == "0.8"
    assert analysis["confidence"] == "0.9"
    assert "competitive moat" in analysis["reasoning"]
    assert analysis["model_name"] == "gpt-4o"
    assert analysis["model_provider"] == "openai"


def test_save_multiple_analyses(test_session_id):
    """Test saving multiple analyses for different tickers and analysts."""
    # Save multiple analyses
    analyses_to_save = [
        ("AAPL", "warren_buffett", "bullish", 0.8, 0.9, "Great company"),
        ("AAPL", "technical_analyst", "neutral", 0.0, 0.7, "Sideways movement"),
        ("MSFT", "warren_buffett", "bullish", 0.7, 0.85, "Strong fundamentals"),
    ]

    for ticker, analyst, signal, signal_num, conf, reason in analyses_to_save:
        save_analyst_analysis(
            session_id=test_session_id, ticker=ticker, analyst_name=analyst, signal=signal, signal_numeric=signal_num, confidence=conf, reasoning=reason, model_name="gpt-4o", model_provider="openai"
        )

    # Retrieve all analyses
    analyses = get_session_analyses(test_session_id)

    # Verify
    assert len(analyses) == 3

    # Check ordering (should be by ticker, then analyst)
    assert analyses[0]["ticker"] == "AAPL"
    assert analyses[1]["ticker"] == "AAPL"
    assert analyses[2]["ticker"] == "MSFT"


def test_export_to_markdown(test_session_id, tmp_path):
    """Test exporting analyses to markdown file."""
    # Save test analyses
    save_analyst_analysis(
        session_id=test_session_id, ticker="AAPL", analyst_name="warren_buffett", signal="bullish", signal_numeric=0.8, confidence=0.9, reasoning="Excellent value proposition.", model_name="gpt-4o", model_provider="openai"
    )
    save_analyst_analysis(
        session_id=test_session_id, ticker="AAPL", analyst_name="technical_analyst", signal="neutral", signal_numeric=0.0, confidence=0.7, reasoning="Consolidating near support.", model_name="gpt-4o", model_provider="openai"
    )

    # Export to markdown
    output_path = tmp_path / "test_transcript.md"
    result_path = export_to_markdown(test_session_id, output_path)

    # Verify file exists
    assert result_path.exists()
    assert result_path == output_path

    # Read and verify content
    content = output_path.read_text()

    # Check header
    assert "# Analyst Transcript" in content
    assert test_session_id in content
    assert "**Model:** gpt-4o" in content
    assert "**Provider:** openai" in content

    # Check analyses are present
    assert "## AAPL" in content
    assert "### warren_buffett" in content
    assert "### technical_analyst" in content
    assert "**Signal:** bullish" in content
    assert "**Signal:** neutral" in content
    assert "Excellent value proposition" in content
    assert "Consolidating near support" in content


def test_export_empty_session():
    """Test exporting a session with no analyses raises an error."""
    fake_session_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="No analyses found"):
        export_to_markdown(fake_session_id)
