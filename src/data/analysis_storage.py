"""
Storage and retrieval of analyst analyses from portfolio manager runs.

Stores individual analyst analyses in SQLite database and provides
export functionality to markdown files for review.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# Database setup - reuse the existing backend database
BACKEND_DIR = Path(__file__).parent.parent.parent / "app" / "backend"
DATABASE_PATH = BACKEND_DIR / "hedge_fund.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Create engine and session
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db_session() -> Session:
    """Get a database session for storage operations."""
    return SessionLocal()


def save_analyst_analysis(session_id: str, ticker: str, analyst_name: str, signal: str, signal_numeric: float, confidence: float, reasoning: str, model_name: Optional[str] = None, model_provider: Optional[str] = None) -> None:
    """
    Save an individual analyst analysis to the database.

    Args:
        session_id: UUID identifying the portfolio manager run
        ticker: Stock ticker analyzed
        analyst_name: Name of the analyst
        signal: Signal string (bullish/neutral/bearish)
        signal_numeric: Numeric signal (-1.0 to 1.0)
        confidence: Confidence level (0.0 to 1.0)
        reasoning: Full text explanation from the analyst
        model_name: Optional LLM model name
        model_provider: Optional LLM provider name
    """
    # Import here to avoid circular dependencies
    from app.backend.database.models import AnalystAnalysis

    db = get_db_session()
    try:
        analysis = AnalystAnalysis(
            session_id=session_id,
            ticker=ticker,
            analyst_name=analyst_name,
            signal=signal,
            signal_numeric=str(signal_numeric),
            confidence=str(confidence),
            reasoning=reasoning,
            model_name=model_name,
            model_provider=model_provider,
        )
        db.add(analysis)
        db.commit()
    finally:
        db.close()


def get_session_analyses(session_id: str) -> List[dict]:
    """
    Retrieve all analyses for a given session.

    Args:
        session_id: UUID of the portfolio manager run

    Returns:
        List of analysis dictionaries with all fields
    """
    from app.backend.database.models import AnalystAnalysis

    db = get_db_session()
    try:
        analyses = db.query(AnalystAnalysis).filter(AnalystAnalysis.session_id == session_id).order_by(AnalystAnalysis.ticker, AnalystAnalysis.analyst_name).all()

        return [
            {
                "id": analysis.id,
                "created_at": analysis.created_at,
                "session_id": analysis.session_id,
                "ticker": analysis.ticker,
                "analyst_name": analysis.analyst_name,
                "signal": analysis.signal,
                "signal_numeric": analysis.signal_numeric,
                "confidence": analysis.confidence,
                "reasoning": analysis.reasoning,
                "model_name": analysis.model_name,
                "model_provider": analysis.model_provider,
            }
            for analysis in analyses
        ]
    finally:
        db.close()


def export_to_markdown(session_id: str, output_path: Optional[Path] = None) -> Path:
    """
    Export all analyses for a session to a markdown file.

    Args:
        session_id: UUID of the portfolio manager run
        output_path: Optional custom output path. If None, generates default name.

    Returns:
        Path to the created markdown file
    """
    analyses = get_session_analyses(session_id)

    if not analyses:
        raise ValueError(f"No analyses found for session {session_id}")

    # Generate output path if not provided
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"analyst_transcript_{timestamp}.md")

    # Group analyses by ticker
    by_ticker = {}
    for analysis in analyses:
        ticker = analysis["ticker"]
        if ticker not in by_ticker:
            by_ticker[ticker] = []
        by_ticker[ticker].append(analysis)

    # Generate markdown content
    lines = []
    lines.append(f"# Analyst Transcript - Session {session_id}")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Session ID:** {session_id}")

    # Add metadata if available
    if analyses:
        first = analyses[0]
        if first["model_name"]:
            lines.append(f"**Model:** {first['model_name']}")
        if first["model_provider"]:
            lines.append(f"**Provider:** {first['model_provider']}")

    lines.append("")
    lines.append(f"**Total Analyses:** {len(analyses)}")
    lines.append(f"**Tickers Analyzed:** {len(by_ticker)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Write analyses grouped by ticker
    for ticker in sorted(by_ticker.keys()):
        lines.append(f"## {ticker}")
        lines.append("")

        for analysis in by_ticker[ticker]:
            analyst_name = analysis["analyst_name"]
            signal = analysis["signal"]
            confidence = analysis.get("confidence", "N/A")
            reasoning = analysis["reasoning"]

            lines.append(f"### {analyst_name}")
            lines.append("")
            lines.append(f"**Signal:** {signal}")
            if confidence != "N/A":
                try:
                    conf_pct = float(confidence) * 100
                    lines.append(f"**Confidence:** {conf_pct:.1f}%")
                except (ValueError, TypeError):
                    lines.append(f"**Confidence:** {confidence}")
            lines.append("")
            lines.append(reasoning)
            lines.append("")
            lines.append("---")
            lines.append("")

    # Write to file
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
