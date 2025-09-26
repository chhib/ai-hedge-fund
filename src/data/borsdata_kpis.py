"""Assembly helpers that translate Börsdata KPI payloads into `FinancialMetrics`."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from .borsdata_client import BorsdataAPIError, BorsdataClient
from .borsdata_common import (
    SUMMARY_LIMIT_MULTIPLIER,
    PeriodRecord,
    build_period_records,
    map_period_to_report_type,
    normalise_name,
    parse_iso_date,
    safe_float,
)
from .borsdata_metrics_mapping import FINANCIAL_METRICS_MAPPING
from .models import FinancialMetrics


class FinancialMetricsAssembler:
    """Builds `FinancialMetrics` sequences by orchestrating Börsdata endpoints."""

    def __init__(self, client: BorsdataClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def assemble(
        self,
        ticker: str,
        *,
        end_date: Optional[str],
        period: Optional[str],
        limit: int,
        api_key: Optional[str],
        use_global: bool = False,
    ) -> list[FinancialMetrics]:
        instrument = self._client.get_instrument(ticker, api_key=api_key, use_global=use_global)
        instrument_id = int(instrument["insId"])
        base_currency = instrument.get("reportCurrency") or instrument.get("stockPriceCurrency") or ""
        stock_currency = instrument.get("stockPriceCurrency") or base_currency

        # Get current stock price for ratio calculations
        current_price = None
        try:
            prices = self._client.get_stock_prices(instrument_id, api_key=api_key)
            if prices:
                current_price = safe_float(prices[-1].get("c"))  # Latest close price
        except Exception:
            current_price = None

        report_type = map_period_to_report_type(period)
        summary_max = max(limit * SUMMARY_LIMIT_MULTIPLIER, limit)
        summary_payload = self._client.get_kpi_summary(
            instrument_id,
            report_type,
            max_count=summary_max,
            api_key=api_key,
        )
        reports_payload = self._client.get_reports(
            instrument_id,
            report_type,
            max_count=summary_max,
            api_key=api_key,
        )

        end_date_dt = parse_iso_date(end_date)
        contexts = build_period_records(
            summary_payload,
            reports_payload,
            report_type,
            limit,
            end_date_dt,
        )
        if not contexts:
            return []

        metadata = self._client.get_kpi_metadata(api_key=api_key)
        metric_to_kpi = self._resolve_metric_kpis(metadata)

        records: list[Dict[str, Any]] = []
        metric_names = list(FINANCIAL_METRICS_MAPPING.keys())
        period_value = period.strip().lower() if period else "ttm"
        for ctx in contexts:
            currency = ctx.report.get("currency") or base_currency
            payload: Dict[str, Any] = {
                "ticker": ticker.upper(),
                "report_period": ctx.report_period,
                "period": period_value,
                "currency": currency,
            }
            for metric in metric_names:
                payload[metric] = None
            records.append(payload)

        # First pass: assign KPI summary values
        for payload, ctx in zip(records, contexts):
            for metric_name in metric_names:
                kpi_id = metric_to_kpi.get(metric_name)
                if kpi_id is None:
                    continue
                value = ctx.kpis.get(kpi_id)
                if value is not None:
                    payload[metric_name] = value

        # Screener-derived fields fall back to calc endpoints when missing
        screener_cache: Dict[Tuple[int, str, str], Optional[float]] = {}
        for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
            if config.get("source") != "screener":
                continue
            kpi_id = metric_to_kpi.get(metric_name)
            if kpi_id is None:
                continue
            calc = config.get("screener_calc")
            if not calc:
                continue
            calc_groups = self._resolve_screener_calc_groups(config, period_value, report_type)
            screener_value: Optional[float] = None
            for calc_group in calc_groups:
                cache_key = (kpi_id, calc_group, calc)
                if cache_key not in screener_cache:
                    value = self._fetch_screener_value(
                        instrument_id,
                        kpi_id,
                        calc_group,
                        calc,
                        api_key=api_key,
                        is_percent=calc.lower() == "percent",
                    )
                    screener_cache[cache_key] = value
                screener_value = screener_cache.get(cache_key)
                if screener_value is not None:
                    break
            if screener_value is None:
                continue
            for payload in records:
                if payload.get(metric_name) is None:
                    payload[metric_name] = screener_value

        # Derived metrics computed from previously resolved data
        for payload, ctx in zip(records, contexts):
            report_currency = payload.get("currency") or base_currency
            for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
                if config.get("source") != "derived":
                    continue
                if payload.get(metric_name) is not None:
                    continue
                derived_value = self._compute_derived_metric(metric_name, payload, ctx, current_price, stock_currency=stock_currency, report_currency=report_currency, instrument_id=instrument_id, api_key=api_key)
                if derived_value is not None:
                    payload[metric_name] = derived_value

        return [FinancialMetrics(**payload) for payload in records]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_metric_kpis(self, metadata: Iterable[Dict[str, Any]]) -> Dict[str, Optional[int]]:
        lookup: Dict[str, int] = {}
        for entry in metadata:
            name = normalise_name(entry.get("nameEn"))
            if not name:
                continue
            try:
                lookup[name] = int(entry.get("kpiId"))
            except (TypeError, ValueError):
                continue

        metric_to_kpi: Dict[str, Optional[int]] = {}
        for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
            kpi_id: Optional[int] = None
            for candidate in config.get("metadata_match", []) or []:
                candidate_id = lookup.get(normalise_name(candidate))
                if candidate_id is not None:
                    kpi_id = candidate_id
                    break
            metric_to_kpi[metric_name] = kpi_id
        return metric_to_kpi

    def _fetch_screener_value(
        self,
        instrument_id: int,
        kpi_id: int,
        calc_group: str,
        calc: str,
        *,
        api_key: Optional[str],
        is_percent: bool,
    ) -> Optional[float]:
        try:
            response = self._client.get_kpi_screener_value(
                instrument_id,
                kpi_id,
                calc_group,
                calc,
                api_key=api_key,
            )
        except BorsdataAPIError:
            return None
        value = ((response or {}).get("value") or {}).get("n")
        numeric = safe_float(value)
        if numeric is None:
            return None
        if is_percent:
            numeric /= 100.0
        return numeric

    def _resolve_screener_calc_groups(
        self,
        config: Dict[str, Any],
        period_value: str,
        report_type: str,
    ) -> list[str]:
        """Determine which screener calc groups to attempt for a metric."""

        def normalise_period(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
            cleaned = value.strip().lower()
            if not cleaned:
                return None
            aliases = {
                "annual": "year",
                "y": "year",
                "quarterly": "quarter",
                "q": "quarter",
                "ttm": "r12",
                "rolling": "r12",
            }
            return aliases.get(cleaned, cleaned)

        ordered_groups: list[str] = []
        overrides = config.get("screener_calc_group_overrides") or {}
        for key in (normalise_period(period_value), normalise_period(report_type)):
            if not key:
                continue
            override_group = overrides.get(key)
            if override_group:
                ordered_groups.append(override_group)

        default_group = config.get("screener_calc_group")
        if default_group:
            ordered_groups.append(default_group)

        seen: set[str] = set()
        deduped: list[str] = []
        for group in ordered_groups:
            normalised = (group or "").strip().lower()
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            deduped.append(normalised)
        return deduped

    def _get_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        instrument_id: int,
        api_key: Optional[str] = None,
    ) -> float:
        """Get exchange rate from one currency to another.

        For now, returns hardcoded common rates. In production, this should
        fetch real-time exchange rates from a financial data provider.
        """
        if from_currency == to_currency:
            return 1.0

        # Common exchange rates (approximate - should be real-time in production)
        rates = {
            ("USD", "SEK"): 10.8,
            ("SEK", "USD"): 1 / 10.8,
            ("USD", "EUR"): 0.85,
            ("EUR", "USD"): 1 / 0.85,
            ("SEK", "EUR"): 0.085,
            ("EUR", "SEK"): 1 / 0.085,
            ("USD", "CAD"): 1.35,
            ("CAD", "USD"): 1 / 1.35,
            ("CAD", "SEK"): 8.0,
            ("SEK", "CAD"): 1 / 8.0,
        }

        rate = rates.get((from_currency, to_currency))
        if rate is not None:
            return rate

        # Try inverse rate
        inverse_rate = rates.get((to_currency, from_currency))
        if inverse_rate is not None:
            return 1.0 / inverse_rate

        # Default to 1.0 if conversion not available
        return 1.0

    def _convert_price_to_report_currency(
        self,
        price: float,
        stock_currency: str,
        report_currency: str,
        instrument_id: int,
        api_key: Optional[str] = None,
    ) -> float:
        """Convert stock price from trading currency to report currency."""
        if stock_currency == report_currency:
            return price

        rate = self._get_exchange_rate(stock_currency, report_currency, instrument_id, api_key)
        return price * rate

    def _compute_derived_metric(
        self,
        metric_name: str,
        payload: Dict[str, Any],
        ctx: PeriodRecord,
        current_price: Optional[float] = None,
        stock_currency: Optional[str] = None,
        report_currency: Optional[str] = None,
        instrument_id: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> Optional[float]:
        report = ctx.report
        if metric_name == "market_cap":
            kpi_value = payload.get(metric_name)
            if kpi_value is not None:
                return safe_float(kpi_value)
            if not report:
                return None
            shares = safe_float(report.get("number_Of_Shares") or report.get("shares_outstanding") or report.get("sharesOutstanding"))
            price = safe_float(report.get("stock_Price_Average") or report.get("stockPriceAverage") or report.get("stock_Price_Close"))
            if shares is None or price is None:
                return None
            return shares * price

        if metric_name == "operating_cash_flow_ratio":
            if not report:
                return None
            operating_cf = safe_float(report.get("cash_Flow_From_Operating_Activities") or report.get("cashFlowFromOperatingActivities"))
            current_liabilities = safe_float(report.get("current_Liabilities") or report.get("currentLiabilities"))
            if operating_cf is None or current_liabilities in (None, 0):
                return None
            return operating_cf / current_liabilities

        if metric_name == "operating_cycle":
            dso = safe_float(payload.get("days_sales_outstanding"))
            if dso is None:
                return None
            inventory_turnover = safe_float(payload.get("inventory_turnover"))
            days_inventory_outstanding = None
            if inventory_turnover not in (None, 0):
                days_inventory_outstanding = 365.0 / inventory_turnover
            if days_inventory_outstanding is None:
                return None
            return dso + days_inventory_outstanding

        # Price ratio calculations using current stock price and per-share KPIs
        if current_price is not None and current_price > 0:
            # Convert stock price to report currency for accurate ratio calculations
            converted_price = current_price
            if stock_currency and report_currency and stock_currency != report_currency and instrument_id:
                converted_price = self._convert_price_to_report_currency(current_price, stock_currency, report_currency, instrument_id, api_key)

            if metric_name == "price_to_earnings_ratio":
                eps = safe_float(ctx.kpis.get(6))  # KPI ID 6: Earnings/share
                if eps is not None and eps != 0:
                    return converted_price / eps

            elif metric_name == "price_to_book_ratio":
                bvps = safe_float(ctx.kpis.get(8))  # KPI ID 8: Book value/share
                if bvps is not None and bvps != 0:
                    return converted_price / bvps

            elif metric_name == "price_to_sales_ratio":
                rps = safe_float(ctx.kpis.get(5))  # KPI ID 5: Revenue/share
                if rps is not None and rps != 0:
                    return converted_price / rps

        # Populate revenue_per_share from KPI data
        if metric_name == "revenue_per_share":
            return safe_float(ctx.kpis.get(5))  # KPI ID 5: Revenue/share

        return None


__all__ = ["FinancialMetricsAssembler"]
