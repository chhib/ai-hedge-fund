"""News sentiment analyst powered by Börsdata calendar events."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from typing_extensions import Literal

from src.data.models import CompanyEvent
from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_company_events
from src.utils.api_key import get_api_key_from_state
from src.utils.llm import call_llm
from src.utils.progress import progress

# Limit the LLM workload while still sampling recent company events
MAX_EVENTS_TO_ANALYZE = 5

# Default lookback for tickers not in portfolio (new positions under evaluation)
DEFAULT_LOOKBACK_DAYS = 30


class EventSentiment(BaseModel):
    """Represents the sentiment assessment for a single event."""
    event_index: int
    sentiment: Literal["positive", "negative", "neutral"]
    confidence: int = Field(description="Confidence 0-100")


class BulkSentimentAnalysis(BaseModel):
    """Represents sentiment analysis for multiple events."""
    events: List[EventSentiment]


class ClassifiedEvent(BaseModel):
    """Stores the mapped trading signal for a calendar event."""

    event_id: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float


def news_sentiment_agent(state: AgentState, agent_id: str = "news_sentiment_agent"):
    """Analyze recent company calendar events and derive a sentiment signal.

    For existing portfolio positions, analyzes events since the position was acquired.
    For new positions under evaluation, analyzes events from the last 30 days.
    """

    data = state.get("data", {})
    end_date = data.get("end_date")
    tickers = data.get("tickers")
    api_key = get_api_key_from_state(state, "BORSDATA_API_KEY")

    # Get position's acquisition date if available (passed from portfolio manager)
    position_date_acquired = data.get("position_date_acquired")

    # Determine the start date for event filtering
    if position_date_acquired:
        # Existing position: analyze events since acquisition
        event_start_date = position_date_acquired
        lookback_mode = f"since {position_date_acquired}"
    else:
        # New position: use default lookback
        default_start = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        event_start_date = default_start
        lookback_mode = f"last {DEFAULT_LOOKBACK_DAYS} days"

    sentiment_analysis: Dict[str, Dict[str, object]] = {}

    for ticker in tickers:
        # Check for prefetched events first (used by portfolio_manager)
        prefetched_data = data.get("prefetched_financial_data", {})
        ticker_data = prefetched_data.get(ticker, {})
        company_events = ticker_data.get("events") if ticker_data else None

        # Fallback to API call if events not prefetched
        if company_events is None:
            progress.update_status(agent_id, ticker, f"Fetching events ({lookback_mode})")
            company_events = get_company_events(
                ticker=ticker,
                start_date=event_start_date,
                end_date=end_date,
                limit=MAX_EVENTS_TO_ANALYZE * 4,
                api_key=api_key,
            )
        else:
            # Filter prefetched events by date
            progress.update_status(agent_id, ticker, f"Filtering events ({lookback_mode})")
            if event_start_date:
                company_events = _filter_events_by_date(company_events, event_start_date, end_date)

        classified_events: List[ClassifiedEvent] = []
        if company_events:
            recent_events = company_events[:MAX_EVENTS_TO_ANALYZE]
            total_to_analyze = len(recent_events)

            if total_to_analyze > 0:
                progress.update_status(
                    agent_id,
                    ticker,
                    f"Analyzing {total_to_analyze} events (bulk)",
                )

                # Bundle all events into a single LLM call
                prompt = _build_bulk_event_prompt(ticker, recent_events)
                response = call_llm(prompt, BulkSentimentAnalysis, agent_name=agent_id, state=state)

                # Process bulk response
                if response and response.events:
                    for event_sentiment in response.events:
                        idx = event_sentiment.event_index
                        if 0 <= idx < len(recent_events):
                            sentiment_label = event_sentiment.sentiment.lower()
                            signal = _map_sentiment_to_signal(sentiment_label)
                            confidence = float(event_sentiment.confidence)

                            classified_events.append(
                                ClassifiedEvent(
                                    event_id=getattr(recent_events[idx], "event_id", f"{ticker}-{idx}"),
                                    signal=signal,
                                    confidence=confidence,
                                )
                            )

        progress.update_status(agent_id, ticker, "Aggregating signals")

        bullish_signals = sum(1 for event in classified_events if event.signal == "bullish")
        bearish_signals = sum(1 for event in classified_events if event.signal == "bearish")
        neutral_signals = sum(1 for event in classified_events if event.signal == "neutral")
        total_signals = len(classified_events)

        if bullish_signals > bearish_signals:
            overall_signal = "bullish"
        elif bearish_signals > bullish_signals:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        confidence = _calculate_confidence_score(
            classified_events=classified_events,
            overall_signal=overall_signal,
            bullish_signals=bullish_signals,
            bearish_signals=bearish_signals,
            neutral_signals=neutral_signals,
        )

        reasoning = {
            "news_sentiment": {
                "signal": overall_signal,
                "confidence": confidence,
                "metrics": {
                    "total_events": total_signals,
                    "bullish_events": bullish_signals,
                    "bearish_events": bearish_signals,
                    "neutral_events": neutral_signals,
                    "events_classified_by_llm": total_signals,
                },
            }
        }

        sentiment_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4))

    message = HumanMessage(content=json.dumps(sentiment_analysis), name=agent_id)

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(sentiment_analysis, "News Sentiment Analysis Agent")

    state.setdefault("data", {})
    state["data"].setdefault("analyst_signals", {})
    state["data"]["analyst_signals"][agent_id] = sentiment_analysis

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": [message],
        "data": state["data"],
    }


def _map_sentiment_to_signal(sentiment: str) -> Literal["bullish", "bearish", "neutral"]:
    if sentiment == "positive":
        return "bullish"
    if sentiment == "negative":
        return "bearish"
    return "neutral"


def _build_bulk_event_prompt(ticker: str, events: List[CompanyEvent]) -> str:
    """Build a prompt that analyzes multiple events in a single LLM call."""
    events_text = []

    for idx, event in enumerate(events):
        event_lines = [
            f"Event {idx}:",
            f"  Category: {event.category}",
            f"  Title: {event.title}",
        ]

        if event.description:
            event_lines.append(f"  Description: {event.description}")
        if event.report_type:
            event_lines.append(f"  Report type: {event.report_type}")
        if event.amount is not None:
            event_lines.append(f"  Amount: {event.amount}")
        if event.currency:
            event_lines.append(f"  Currency: {event.currency}")
        if event.distribution_frequency:
            event_lines.append(f"  Distribution frequency: {event.distribution_frequency}")
        if event.dividend_type is not None:
            event_lines.append(f"  Dividend type: {event.dividend_type}")
        event_lines.append(f"  Date: {event.date}")

        events_text.append("\n".join(event_lines))

    all_events = "\n\n".join(events_text)

    return (
        f"Analyze the following company calendar events for {ticker} and determine the sentiment for each event.\n"
        "For each event, classify the sentiment as positive, negative, or neutral, and provide a confidence score from 0 to 100.\n"
        "Respond in JSON format with an array of events, where each event has 'event_index', 'sentiment', and 'confidence'.\n\n"
        f"{all_events}"
    )


def _calculate_confidence_score(
    *,
    classified_events: List[ClassifiedEvent],
    overall_signal: str,
    bullish_signals: int,
    bearish_signals: int,
    neutral_signals: int,
) -> float:
    total_signals = len(classified_events)
    if total_signals == 0:
        return 0.0

    signal_counts = {
        "bullish": bullish_signals,
        "bearish": bearish_signals,
        "neutral": neutral_signals,
    }

    matching_confidences = [
        event.confidence
        for event in classified_events
        if event.signal == overall_signal
    ]

    signal_proportion = (
        (signal_counts.get(overall_signal, 0) / total_signals) * 100
        if overall_signal in signal_counts and total_signals > 0
        else 0.0
    )

    if matching_confidences:
        avg_confidence = sum(matching_confidences) / len(matching_confidences)
        return round(0.7 * avg_confidence + 0.3 * signal_proportion, 2)

    return round(signal_proportion, 2)


def _filter_events_by_date(
    events: List[CompanyEvent],
    start_date: str,
    end_date: str | None,
) -> List[CompanyEvent]:
    """Filter events to only include those within the date range.

    Args:
        events: List of CompanyEvent objects
        start_date: ISO date string (YYYY-MM-DD) - include events on or after this date
        end_date: ISO date string (YYYY-MM-DD) - include events on or before this date

    Returns:
        Filtered list of events within the date range
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else datetime.now().date()
    except (ValueError, TypeError):
        # If date parsing fails, return all events
        return events

    filtered = []
    for event in events:
        try:
            # CompanyEvent has a `date` attribute which is a string
            event_date = datetime.strptime(event.date, "%Y-%m-%d").date()
            if start_dt <= event_date <= end_dt:
                filtered.append(event)
        except (ValueError, TypeError, AttributeError):
            # If event date parsing fails, include the event
            filtered.append(event)

    return filtered

