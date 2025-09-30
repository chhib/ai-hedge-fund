from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from typing_extensions import Literal

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress
import json

from src.tools.api import get_financial_metrics
from src.utils.data_cache import get_cached_or_fetch_financial_metrics


class FundamentalsAnalystSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: int
    reasoning: str


class FundamentalsAnalyst:
    """Simplified class wrapper for compatibility with legacy interfaces."""

    def analyze(self, context: dict[str, Any]) -> FundamentalsAnalystSignal:
        metrics = context.get("financial_data")
        if metrics is None:
            return FundamentalsAnalystSignal(signal="neutral", confidence=0, reasoning="Missing financial metrics")

        positives: list[str] = []
        negatives: list[str] = []
        neutrals: list[str] = []

        profitability_checks = [
            (getattr(metrics, "return_on_equity", None), 0.15, "Return on equity"),
            (getattr(metrics, "net_margin", None), 0.20, "Net margin"),
            (getattr(metrics, "operating_margin", None), 0.15, "Operating margin"),
        ]
        for value, threshold, label in profitability_checks:
            if value is None:
                neutrals.append(f"{label} unavailable")
            elif value >= threshold:
                positives.append(f"{label} {value:.1%} above threshold")
            elif value <= 0:
                negatives.append(f"{label} {value:.1%} negative")
            else:
                negatives.append(f"{label} {value:.1%} below threshold")

        growth_checks = [
            (getattr(metrics, "revenue_growth", None), 0.10, "Revenue growth"),
            (getattr(metrics, "earnings_growth", None), 0.10, "Earnings growth"),
            (getattr(metrics, "book_value_growth", None), 0.08, "Book value growth"),
        ]
        for value, threshold, label in growth_checks:
            if value is None:
                neutrals.append(f"{label} unavailable")
            elif value >= threshold:
                positives.append(f"{label} {value:.1%} strong")
            elif value <= 0:
                negatives.append(f"{label} {value:.1%} contracting")
            else:
                negatives.append(f"{label} {value:.1%} modest")

        current_ratio = getattr(metrics, "current_ratio", None)
        if current_ratio is not None:
            if current_ratio >= 1.5:
                positives.append(f"Current ratio {current_ratio:.2f} shows liquidity")
            else:
                negatives.append(f"Current ratio {current_ratio:.2f} tight")
        else:
            neutrals.append("Current ratio unavailable")

        debt_to_equity = getattr(metrics, "debt_to_equity", None)
        if debt_to_equity is not None:
            if debt_to_equity <= 0.5:
                positives.append(f"Debt/Equity {debt_to_equity:.2f} conservative")
            else:
                negatives.append(f"Debt/Equity {debt_to_equity:.2f} elevated")
        else:
            neutrals.append("Debt/Equity unavailable")

        fcf_per_share = getattr(metrics, "free_cash_flow_per_share", None)
        eps = getattr(metrics, "earnings_per_share", None)
        if fcf_per_share is not None and eps is not None and eps != 0:
            if fcf_per_share >= eps * 0.8:
                positives.append("FCF conversion supports earnings quality")
            else:
                negatives.append("FCF conversion weak versus EPS")
        else:
            neutrals.append("FCF conversion unavailable")

        valuation_checks = [
            (getattr(metrics, "price_to_earnings_ratio", None), 25, "P/E"),
            (getattr(metrics, "price_to_book_ratio", None), 3, "P/B"),
            (getattr(metrics, "price_to_sales_ratio", None), 5, "P/S"),
        ]
        for value, threshold, label in valuation_checks:
            if value is None:
                neutrals.append(f"{label} unavailable")
            elif value <= threshold:
                positives.append(f"{label} {value:.2f} reasonable")
            else:
                negatives.append(f"{label} {value:.2f} expensive")

        total_checks = len(positives) + len(negatives)
        if total_checks == 0:
            signal = "neutral"
            confidence = 0
        else:
            if len(positives) > len(negatives):
                signal = "bullish"
            elif len(negatives) > len(positives):
                signal = "bearish"
            else:
                signal = "neutral"

            spread = abs(len(positives) - len(negatives))
            confidence = int((spread / total_checks) * 100)

        reasoning_parts = positives + negatives + neutrals
        reasoning = "; ".join(reasoning_parts) if reasoning_parts else "No fundamental factors available"

        return FundamentalsAnalystSignal(signal=signal, confidence=confidence, reasoning=reasoning)




##### Fundamental Agent #####
def fundamentals_analyst_agent(state: AgentState, agent_id: str = "fundamentals_analyst_agent"):
    """Analyzes fundamental data and generates trading signals for multiple tickers."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    next_ticker = data.get("next_ticker")  # For progress tracking
    api_key = get_api_key_from_state(state, "BORSDATA_API_KEY")
    # Initialize fundamental analysis for each ticker
    fundamental_analysis = {}
    any_ticker_succeeded = False

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Using cached financial metrics")

        # Get the financial metrics from cache or API
        financial_metrics = get_cached_or_fetch_financial_metrics(ticker, end_date, state, api_key)

        if not financial_metrics:
            progress.update_status(agent_id, ticker, "Error")
            continue

        # Pull the most recent financial metrics
        metrics = financial_metrics[0]

        # Initialize signals list for different fundamental aspects
        signals = []
        reasoning = {}

        progress.update_status(agent_id, ticker, "Analyzing profitability")
        # 1. Profitability Analysis
        return_on_equity = metrics.return_on_equity
        net_margin = metrics.net_margin
        operating_margin = metrics.operating_margin

        thresholds = [
            (return_on_equity, 0.15),  # Strong ROE above 15%
            (net_margin, 0.20),  # Healthy profit margins
            (operating_margin, 0.15),  # Strong operating efficiency
        ]
        profitability_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)

        signals.append("bullish" if profitability_score >= 2 else "bearish" if profitability_score == 0 else "neutral")
        reasoning["profitability_signal"] = {
            "signal": signals[0],
            "details": (f"ROE: {return_on_equity:.2%}" if return_on_equity else "ROE: N/A") + ", " + (f"Net Margin: {net_margin:.2%}" if net_margin else "Net Margin: N/A") + ", " + (f"Op Margin: {operating_margin:.2%}" if operating_margin else "Op Margin: N/A"),
        }

        progress.update_status(agent_id, ticker, "Analyzing growth")
        # 2. Growth Analysis
        revenue_growth = metrics.revenue_growth
        earnings_growth = metrics.earnings_growth
        book_value_growth = metrics.book_value_growth

        thresholds = [
            (revenue_growth, 0.10),  # 10% revenue growth
            (earnings_growth, 0.10),  # 10% earnings growth
            (book_value_growth, 0.10),  # 10% book value growth
        ]
        growth_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)

        signals.append("bullish" if growth_score >= 2 else "bearish" if growth_score == 0 else "neutral")
        reasoning["growth_signal"] = {
            "signal": signals[1],
            "details": (f"Revenue Growth: {revenue_growth:.2%}" if revenue_growth else "Revenue Growth: N/A") + ", " + (f"Earnings Growth: {earnings_growth:.2%}" if earnings_growth else "Earnings Growth: N/A"),
        }

        progress.update_status(agent_id, ticker, "Analyzing financial health")
        # 3. Financial Health
        current_ratio = metrics.current_ratio
        debt_to_equity = metrics.debt_to_equity
        free_cash_flow_per_share = metrics.free_cash_flow_per_share
        earnings_per_share = metrics.earnings_per_share

        health_score = 0
        if current_ratio and current_ratio > 1.5:  # Strong liquidity
            health_score += 1
        if debt_to_equity and debt_to_equity < 0.5:  # Conservative debt levels
            health_score += 1
        if free_cash_flow_per_share and earnings_per_share and free_cash_flow_per_share > earnings_per_share * 0.8:  # Strong FCF conversion
            health_score += 1

        signals.append("bullish" if health_score >= 2 else "bearish" if health_score == 0 else "neutral")
        reasoning["financial_health_signal"] = {
            "signal": signals[2],
            "details": (f"Current Ratio: {current_ratio:.2f}" if current_ratio else "Current Ratio: N/A") + ", " + (f"D/E: {debt_to_equity:.2f}" if debt_to_equity else "D/E: N/A"),
        }

        progress.update_status(agent_id, ticker, "Analyzing valuation ratios")
        # 4. Price to X ratios
        pe_ratio = metrics.price_to_earnings_ratio
        pb_ratio = metrics.price_to_book_ratio
        ps_ratio = metrics.price_to_sales_ratio

        thresholds = [
            (pe_ratio, 25),  # Reasonable P/E ratio
            (pb_ratio, 3),  # Reasonable P/B ratio
            (ps_ratio, 5),  # Reasonable P/S ratio
        ]
        price_ratio_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)

        signals.append("bearish" if price_ratio_score >= 2 else "bullish" if price_ratio_score == 0 else "neutral")
        reasoning["price_ratios_signal"] = {
            "signal": signals[3],
            "details": (f"P/E: {pe_ratio:.2f}" if pe_ratio else "P/E: N/A") + ", " + (f"P/B: {pb_ratio:.2f}" if pb_ratio else "P/B: N/A") + ", " + (f"P/S: {ps_ratio:.2f}" if ps_ratio else "P/S: N/A"),
        }

        progress.update_status(agent_id, ticker, "Calculating final signal")
        # Determine overall signal
        bullish_signals = signals.count("bullish")
        bearish_signals = signals.count("bearish")

        if bullish_signals > bearish_signals:
            overall_signal = "bullish"
        elif bearish_signals > bullish_signals:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        # Calculate confidence level
        total_signals = len(signals)
        confidence = round(max(bullish_signals, bearish_signals) / total_signals, 2) * 100

        fundamental_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4), next_ticker=next_ticker)
        any_ticker_succeeded = True

    # Create the fundamental analysis message
    message = HumanMessage(
        content=json.dumps(fundamental_analysis),
        name=agent_id,
    )

    # Print the reasoning if the flag is set
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(fundamental_analysis, "Fundamental Analysis Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = fundamental_analysis

    if any_ticker_succeeded:
        progress.update_status(agent_id, None, "Done")
    else:
        progress.update_status(agent_id, None, "Error")
    
    return {
        "messages": [message],
        "data": data,
    }
