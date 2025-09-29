"""Utility functions for accessing cached financial data in analyst agents."""

from src.graph.state import AgentState
from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def get_cached_or_fetch_financial_metrics(ticker: str, end_date: str, state: AgentState, api_key: str = None, period: str = "ttm", limit: int = 10) -> list:
    """Get financial metrics from prefetched data or fallback to API call."""
    prefetched_data = state["data"].get("prefetched_financial_data", {})
    if ticker in prefetched_data and prefetched_data[ticker].get("metrics"):
        return prefetched_data[ticker]["metrics"]

    # Fallback to API call if not prefetched
    return get_financial_metrics(ticker, end_date, period=period, limit=limit, api_key=api_key)


def get_cached_or_fetch_line_items(ticker: str, line_items_list: list, end_date: str, state: AgentState, api_key: str = None, period: str = "ttm", limit: int = 10) -> list:
    """Get line items from prefetched data or fallback to API call."""
    prefetched_data = state["data"].get("prefetched_financial_data", {})
    if ticker in prefetched_data and prefetched_data[ticker]["line_items"]:
        return prefetched_data[ticker]["line_items"]

    # Fallback to API call if not prefetched
    return search_line_items(ticker, line_items_list, end_date, period=period, limit=limit, api_key=api_key)


def get_cached_or_fetch_market_cap(ticker: str, end_date: str, state: AgentState, api_key: str = None):
    """Get market cap from prefetched data or fallback to API call."""
    prefetched_data = state["data"].get("prefetched_financial_data", {})
    if ticker in prefetched_data and prefetched_data[ticker]["market_cap"] is not None:
        return prefetched_data[ticker]["market_cap"]

    # Fallback to API call if not prefetched
    return get_market_cap(ticker, end_date, api_key=api_key)


def is_data_prefetched(ticker: str, state: AgentState) -> bool:
    """Check if financial data has been prefetched for this ticker."""
    prefetched_data = state["data"].get("prefetched_financial_data", {})
    return ticker in prefetched_data and bool(prefetched_data[ticker].get("metrics"))