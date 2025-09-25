from langchain_core.messages import HumanMessage
from src.graph.state import AgentState, show_agent_reasoning
from src.utils.progress import progress
import pandas as pd
import numpy as np
import json
from src.utils.api_key import get_api_key_from_state
from src.tools.api import get_insider_trades, get_company_events


##### Sentiment Agent #####
def sentiment_analyst_agent(state: AgentState, agent_id: str = "sentiment_analyst_agent"):
    """Analyzes market sentiment and generates trading signals for multiple tickers."""
    data = state.get("data", {})
    end_date = data.get("end_date")
    tickers = data.get("tickers")
    api_key = get_api_key_from_state(state, "BORSDATA_API_KEY")
    # Initialize sentiment analysis for each ticker
    sentiment_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching insider trades")

        # Get the insider trades
        insider_trades = get_insider_trades(
            ticker=ticker,
            end_date=end_date,
            limit=1000,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "Analyzing trading patterns")

        # Get the signals from the insider trades
        transaction_shares = pd.Series([t.transaction_shares for t in insider_trades]).dropna()
        insider_signals = np.where(transaction_shares < 0, "bearish", "bullish").tolist()

        progress.update_status(agent_id, ticker, "Fetching company calendar")

        calendar_events = get_company_events(ticker, end_date, limit=100, api_key=api_key)
        calendar_signals: list[str] = []
        for event in calendar_events:
            category = getattr(event, "category", "")
            if category == "dividend":
                calendar_signals.append("bullish")
            elif category == "report":
                calendar_signals.append("neutral")
            else:
                calendar_signals.append("neutral")

        progress.update_status(agent_id, ticker, "Combining signals")
        insider_weight = 0.6
        calendar_weight = 0.4

        bullish_signals = (
            insider_signals.count("bullish") * insider_weight
            + calendar_signals.count("bullish") * calendar_weight
        )
        bearish_signals = (
            insider_signals.count("bearish") * insider_weight
            + calendar_signals.count("bearish") * calendar_weight
        )

        if bullish_signals > bearish_signals:
            overall_signal = "bullish"
        elif bearish_signals > bullish_signals:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        total_weighted_signals = len(insider_signals) * insider_weight + len(calendar_signals) * calendar_weight
        confidence = 0
        if total_weighted_signals > 0:
            confidence = round((max(bullish_signals, bearish_signals) / total_weighted_signals) * 100, 2)

        calendar_bullish = calendar_signals.count("bullish")
        calendar_bearish = calendar_signals.count("bearish")
        calendar_neutral = calendar_signals.count("neutral")

        calendar_signal_value = "bullish" if calendar_bullish > calendar_bearish else (
            "bearish" if calendar_bearish > calendar_bullish else "neutral"
        )

        calendar_confidence = 0
        if len(calendar_signals) > 0:
            calendar_confidence = round(
                (max(calendar_bullish, calendar_bearish) / len(calendar_signals)) * 100,
                2,
            )

        latest_event = max(
            calendar_events,
            key=lambda event: getattr(event, "date", ""),
            default=None,
        )

        reasoning = {
            "insider_trading": {
                "signal": (
                    "bullish"
                    if insider_signals.count("bullish") > insider_signals.count("bearish")
                    else "bearish"
                    if insider_signals.count("bearish") > insider_signals.count("bullish")
                    else "neutral"
                ),
                "confidence": round((max(insider_signals.count("bullish"), insider_signals.count("bearish")) / max(len(insider_signals), 1)) * 100),
                "metrics": {
                    "total_trades": len(insider_signals),
                    "bullish_trades": insider_signals.count("bullish"),
                    "bearish_trades": insider_signals.count("bearish"),
                    "weight": insider_weight,
                    "weighted_bullish": round(insider_signals.count("bullish") * insider_weight, 1),
                    "weighted_bearish": round(insider_signals.count("bearish") * insider_weight, 1),
                }
            },
            "calendar_events": {
                "signal": calendar_signal_value,
                "confidence": calendar_confidence,
                "metrics": {
                    "total_events": len(calendar_signals),
                    "bullish_events": calendar_bullish,
                    "bearish_events": calendar_bearish,
                    "neutral_events": calendar_neutral,
                    "weight": calendar_weight,
                    "weighted_bullish": round(calendar_bullish * calendar_weight, 1),
                    "weighted_bearish": round(calendar_bearish * calendar_weight, 1),
                    "latest_event": (
                        f"{latest_event.title} on {latest_event.date}"
                        if latest_event is not None
                        else None
                    ),
                }
            },
            "combined_analysis": {
                "total_weighted_bullish": round(bullish_signals, 1),
                "total_weighted_bearish": round(bearish_signals, 1),
                "signal_determination": f"{'Bullish' if bullish_signals > bearish_signals else 'Bearish' if bearish_signals > bullish_signals else 'Neutral'} based on weighted signal comparison"
            }
        }

        sentiment_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4))

    # Create the sentiment message
    message = HumanMessage(
        content=json.dumps(sentiment_analysis),
        name=agent_id,
    )

    # Print the reasoning if the flag is set
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(sentiment_analysis, "Sentiment Analysis Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = sentiment_analysis

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": [message],
        "data": data,
    }
