import datetime
import pandas as pd

from src.data.cache import get_cache
from src.data.models import (
    CompanyEvent,
    FinancialMetrics,
    Price,
    LineItem,
    InsiderTrade,
)
from src.data.borsdata_client import BorsdataAPIError, BorsdataClient
from src.data.borsdata_kpis import FinancialMetricsAssembler
from src.data.borsdata_reports import LineItemAssembler
from pydantic import BaseModel

# Global mapping for ticker markets
_ticker_markets = {}

def set_ticker_markets(ticker_markets: dict[str, str]) -> None:
    """Set the market mapping for each ticker (Nordic/Global)."""
    global _ticker_markets
    _ticker_markets = ticker_markets or {}

def use_global_for_ticker(ticker: str) -> bool:
    return _ticker_markets.get(ticker.upper()) == "global"

# Global cache instance
_cache = get_cache()
_borsdata_client = BorsdataClient()
_financial_metrics_assembler = FinancialMetricsAssembler(_borsdata_client)
_line_item_assembler = LineItemAssembler(_borsdata_client)


def _get_borsdata_client(api_key: str | None) -> BorsdataClient:
    """Return a Börsdata client configured with the requested API key."""
    if api_key:
        return BorsdataClient(api_key=api_key)
    return _borsdata_client


def _normalise_calendar_date(raw: str | None) -> str | None:
    """Convert Börsdata calendar timestamps into YYYY-MM-DD strings."""
    if not raw:
        return None

    cleaned = raw.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(cleaned)
    except ValueError:
        # Fallback to the date portion if present
        try:
            dt = datetime.datetime.fromisoformat(raw.split("T")[0])
        except ValueError:
            return None

    return dt.date().isoformat()


def _make_event_id(category: str, instrument_id: int, date: str, *extras: str | int | float | None) -> str:
    """Build a stable cache identifier for calendar events."""
    suffix_parts = [str(ex) for ex in extras if ex not in (None, "", [])]
    joined_suffix = ":".join(suffix_parts)
    base = f"{category}:{instrument_id}:{date}"
    return f"{base}:{joined_suffix}" if joined_suffix else base


def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    """Fetch price data from cache or API."""
    # Create a cache key that includes all parameters to ensure exact matches
    cache_key = f"{ticker}_{start_date}_{end_date or 'none'}"

    # Check cache first - simple exact match
    if cached_data := _cache.get_prices(cache_key):
        return [Price(**price) for price in cached_data]

    client = _get_borsdata_client(api_key)

    try:
        raw_prices = client.get_stock_prices_by_ticker(
            ticker,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            use_global=use_global_for_ticker(ticker),
        )
    except BorsdataAPIError as exc:
        # Log the error for debugging, but don't crash the agent
        print(f"Could not fetch prices for {ticker}: {exc}")
        return []

    prices: list[Price] = []
    for entry in raw_prices:
        date_str = entry.get("d")
        close_value = entry.get("c")
        if not date_str or close_value is None:
            continue

        def _numerical(value, fallback):
            return float(value) if value is not None else float(fallback)

        open_value = _numerical(entry.get("o"), close_value)
        high_value = _numerical(entry.get("h"), close_value)
        low_value = _numerical(entry.get("l"), close_value)
        volume_value = int(entry.get("v") or 0)

        time_value = date_str if "T" in date_str else f"{date_str}T00:00:00Z"

        prices.append(
            Price(
                open=open_value,
                close=float(close_value),
                high=high_value,
                low=low_value,
                volume=volume_value,
                time=time_value,
            )
        )

    if not prices:
        return []

    # Cache the results using the comprehensive cache key
    _cache.set_prices(cache_key, [p.model_dump() for p in prices])
    return prices


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Fetch financial metrics from cache or API."""
    # Create a cache key that includes all parameters to ensure exact matches
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"

    # Check cache first - simple exact match
    if cached_data := _cache.get_financial_metrics(cache_key):
        return [FinancialMetrics(**metric) for metric in cached_data]

    client = _get_borsdata_client(api_key)
    assembler = _financial_metrics_assembler if client is _borsdata_client else FinancialMetricsAssembler(client)

    try:
        financial_metrics = assembler.assemble(
            ticker,
            end_date=end_date,
            period=period,
            limit=limit,
            api_key=api_key,
            use_global=use_global_for_ticker(ticker),
        )
    except BorsdataAPIError as exc:
        # Log the error for debugging, but don't crash the agent
        print(f"Could not fetch financial metrics for {ticker}: {exc}")
        return []

    if not financial_metrics:
        return []

    # Cache the results as dicts using the comprehensive cache key
    _cache.set_financial_metrics(cache_key, [m.model_dump() for m in financial_metrics])
    return financial_metrics


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Fetch line items via Börsdata reports and KPI summaries."""

    if not line_items:
        return []

    client = _get_borsdata_client(api_key)
    assembler = _line_item_assembler if client is _borsdata_client else LineItemAssembler(client)

    try:
        records = assembler.assemble(
            ticker,
            line_items,
            end_date=end_date,
            period=period,
            limit=limit,
            api_key=api_key,
            use_global=use_global_for_ticker(ticker),
        )
    except BorsdataAPIError as exc:
        # Log the error for debugging, but don't crash the agent
        print(f"Could not fetch line items for {ticker}: {exc}")
        return []

    if not records:
        return []

    class DynamicModel(BaseModel):
        model_config = {"extra": "allow"}

    return [DynamicModel(**record) for record in records]


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Fetch insider trades using Börsdata holdings endpoints."""

    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_insider_trades(cache_key):
        return [InsiderTrade(**trade) for trade in cached_data]

    client = _get_borsdata_client(api_key)

    try:
        instrument = client.get_instrument(ticker, api_key=api_key, use_global=use_global_for_ticker(ticker))
    except BorsdataAPIError as exc:
        # Log the error for debugging, but don't crash the agent
        print(f"Could not fetch instrument for {ticker}: {exc}")
        return []

    instrument_id = instrument.get("insId")
    if instrument_id is None:
        return []

    issuer_name = instrument.get("name")

    end_dt = datetime.date.fromisoformat(end_date)
    start_dt = datetime.date.fromisoformat(start_date) if start_date else None

    try:
        rows = client.get_insider_holdings([instrument_id], api_key=api_key)
    except BorsdataAPIError as exc:
        raise Exception(f"Error fetching Börsdata insider holdings for {ticker}: {exc}") from exc

    trades: list[InsiderTrade] = []

    for row in rows:
        transaction_date_str = _normalise_calendar_date(row.get("transactionDate"))
        filing_date_str = _normalise_calendar_date(row.get("verificationDate"))

        # Fallback to verification date if transaction date missing
        if transaction_date_str is None:
            transaction_date_str = filing_date_str
        if filing_date_str is None:
            filing_date_str = transaction_date_str

        if transaction_date_str is None or filing_date_str is None:
            continue

        try:
            transaction_date_dt = datetime.date.fromisoformat(transaction_date_str)
        except ValueError:
            continue

        if transaction_date_dt > end_dt:
            continue
        if start_dt and transaction_date_dt < start_dt:
            continue

        raw_shares = row.get("shares")
        if raw_shares is None:
            continue

        try:
            shares_value = float(raw_shares)
        except (TypeError, ValueError):
            continue

        transaction_type = row.get("transactionType")
        if transaction_type not in (None, 0, 1):
            shares_value = -abs(shares_value)
        else:
            shares_value = abs(shares_value)

        price_raw = row.get("price")
        amount_raw = row.get("amount")

        try:
            price_value = float(price_raw) if price_raw is not None else None
        except (TypeError, ValueError):
            price_value = None

        try:
            amount_value = float(amount_raw) if amount_raw is not None else None
        except (TypeError, ValueError):
            amount_value = None

        owner_position = row.get("ownerPosition")
        is_board_director = None
        if isinstance(owner_position, str):
            is_board_director = "director" in owner_position.lower()

        trade = InsiderTrade(
            ticker=ticker,
            issuer=issuer_name,
            name=row.get("ownerName"),
            title=owner_position,
            is_board_director=is_board_director,
            transaction_date=transaction_date_str,
            transaction_shares=shares_value,
            transaction_price_per_share=price_value,
            transaction_value=amount_value,
            shares_owned_before_transaction=None,
            shares_owned_after_transaction=None,
            security_title=None,
            filing_date=filing_date_str,
        )
        trades.append(trade)

    if not trades:
        return []

    trades.sort(key=lambda item: (item.filing_date or "", item.transaction_date or ""), reverse=True)
    trades = trades[:limit]

    _cache.set_insider_trades(cache_key, [trade.model_dump() for trade in trades])
    return trades


def get_company_events(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyEvent]:
    """Fetch company calendar events (reports + dividends) for a ticker."""

    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_company_events(cache_key):
        return [CompanyEvent(**event) for event in cached_data]

    client = _get_borsdata_client(api_key)

    try:
        instrument = client.get_instrument(ticker, api_key=api_key, use_global=use_global_for_ticker(ticker))
    except BorsdataAPIError as exc:
        # Log the error for debugging, but don't crash the agent
        print(f"Could not fetch instrument for {ticker}: {exc}")
        return []

    instrument_id = instrument.get("insId")
    if instrument_id is None:
        return []

    end_date_obj = datetime.date.fromisoformat(end_date)
    start_date_obj = datetime.date.fromisoformat(start_date) if start_date else None

    try:
        report_calendar = client.get_report_calendar([instrument_id], api_key=api_key)
        dividend_calendar = client.get_dividend_calendar([instrument_id], api_key=api_key)
    except BorsdataAPIError as exc:
        # Log the error for debugging, but don't crash the agent
        print(f"Could not fetch calendar data for {ticker}: {exc}")
        return []

    events: list[CompanyEvent] = []

    for report in report_calendar:
        event_date_str = _normalise_calendar_date(report.get("releaseDate"))
        if not event_date_str:
            continue

        event_date_obj = datetime.date.fromisoformat(event_date_str)
        if event_date_obj > end_date_obj:
            continue
        if start_date_obj and event_date_obj < start_date_obj:
            continue

        report_type = report.get("reportType")
        title = f"Report release ({report_type})" if report_type else "Report release"
        events.append(
            CompanyEvent(
                ticker=ticker,
                date=event_date_str,
                category="report",
                title=title,
                description="Börsdata report calendar entry",
                report_type=report_type,
                event_id=_make_event_id("report", instrument_id, event_date_str, report_type),
            )
        )

    for dividend in dividend_calendar:
        event_date_str = _normalise_calendar_date(dividend.get("excludingDate"))
        if not event_date_str:
            continue

        event_date_obj = datetime.date.fromisoformat(event_date_str)
        if event_date_obj > end_date_obj:
            continue
        if start_date_obj and event_date_obj < start_date_obj:
            continue

        amount_raw = dividend.get("amountPaid")
        amount = float(amount_raw) if amount_raw is not None else None
        currency = dividend.get("currencyShortName")
        distribution_frequency = dividend.get("distributionFrequency")
        dividend_type = dividend.get("dividendType")

        amount_label = f" {amount:.2f}" if amount is not None else ""
        currency_label = f" {currency}" if currency else ""
        title = f"Dividend{amount_label}{currency_label}".strip()
        description = "Börsdata dividend calendar entry"

        events.append(
            CompanyEvent(
                ticker=ticker,
                date=event_date_str,
                category="dividend",
                title=title,
                description=description,
                amount=amount,
                currency=currency,
                distribution_frequency=distribution_frequency,
                dividend_type=dividend_type,
                event_id=_make_event_id(
                    "dividend",
                    instrument_id,
                    event_date_str,
                    f"{amount_raw}" if amount_raw is not None else None,
                    currency,
                ),
            )
        )

    if not events:
        return []

    # Sort reverse-chronologically to surface the most recent events first
    events.sort(key=lambda e: e.date, reverse=True)
    events = events[:limit]

    _cache.set_company_events(cache_key, [event.model_dump() for event in events])
    return events


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Fetch market cap derived from Börsdata financial metrics."""

    financial_metrics = get_financial_metrics(ticker, end_date, api_key=api_key)
    if not financial_metrics:
        return None

    market_cap = financial_metrics[0].market_cap
    if market_cap is None:
        return None

    return market_cap


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices to a DataFrame."""
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


# Update the get_price_data function to use the new functions
def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str = None) -> pd.DataFrame:
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)