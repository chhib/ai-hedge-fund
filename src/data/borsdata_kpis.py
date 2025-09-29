"""Assembly helpers that translate Börsdata KPI payloads into `FinancialMetrics`."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple
import time

from .borsdata_client import BorsdataAPIError, BorsdataClient
from .borsdata_common import (
    build_period_records,
    map_period_to_report_type,
    normalise_name,
    parse_iso_date,
    PeriodRecord,
    safe_float,
    SUMMARY_LIMIT_MULTIPLIER,
)
from .borsdata_metrics_mapping import FINANCIAL_METRICS_MAPPING
from .models import FinancialMetrics


class FinancialMetricsAssembler:
    """Builds `FinancialMetrics` sequences by orchestrating Börsdata endpoints."""

    # Class-level cache for all-instruments KPI responses
    # This allows multiple tickers to benefit from the same API calls
    _kpi_cache: Dict[str, Dict[str, Any]] = {}
    _cache_timestamps: Dict[str, float] = {}
    _cache_ttl = 300  # 5 minutes cache TTL

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
            prices = self._client.get_stock_prices(instrument_id, original_currency=True, api_key=api_key)
            if prices:
                current_price = safe_float(prices[-1].get("c"))
        except Exception:
            current_price = None

        report_type = map_period_to_report_type(period)
        summary_max = max(limit * SUMMARY_LIMIT_MULTIPLIER, limit)
        
        # 1. Fetch all required data in bulk
        summary_payload = self._client.get_kpi_summary(
            instrument_id,
            report_type,
            max_count=summary_max,
            original_currency=True,
            api_key=api_key,
        )
        reports_payload = self._client.get_reports(
            instrument_id,
            report_type,
            max_count=summary_max,
            original_currency=True,
            api_key=api_key,
        )
        essential_metrics = {
            'return_on_equity', 'debt_to_equity', 'operating_margin', 'current_ratio',
            'price_to_earnings_ratio', 'price_to_book_ratio', 'price_to_sales_ratio',
            'earnings_per_share', 'free_cash_flow_per_share', 'revenue_growth', 'free_cash_flow_growth',
            'return_on_invested_capital', 'beta', 'revenue', 'free_cash_flow'
        }

        screener_kpis = {}
        essential_configs = {name: config for name, config in FINANCIAL_METRICS_MAPPING.items()
                           if name in essential_metrics and 'kpi_id' in config}

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        def fetch_kpi(metric_name, config):
            start_time = time.time()
            try:
                kpi_id = config['kpi_id']
                calc_group = config.get('screener_calc_group', 'last')
                calc = config.get('screener_calc', 'latest')

                cache_key = f"{kpi_id}_{calc_group}_{calc}_{use_global}"
                current_time = time.time()

                if (cache_key in self._kpi_cache and
                    cache_key in self._cache_timestamps and
                    current_time - self._cache_timestamps[cache_key] < self._cache_ttl):

                    response = self._kpi_cache[cache_key]
                else:
                    response = self._client.get_kpi_all_instruments(
                        kpi_id, calc_group, calc, use_global=use_global, api_key=api_key
                    )
                    if response:
                        self._kpi_cache[cache_key] = response
                        self._cache_timestamps[cache_key] = current_time

                if response and response.get('values'):
                    for item in response['values']:
                        if item.get('i') == instrument_id:
                            return kpi_id, safe_float(item.get('n'))

                if metric_name in essential_metrics:
                    try:
                        response = self._client.get_kpi_screener_value(
                            instrument_id, kpi_id, calc_group, calc, api_key=api_key
                        )
                        if response and response.get('value'):
                            return kpi_id, safe_float(response['value']['n'])
                    except BorsdataAPIError:
                        pass
            except BorsdataAPIError:
                pass
            return None, None

        essential_results = {}
        with ThreadPoolExecutor(max_workers=min(16, len(essential_configs))) as executor:
            future_to_metric = {
                executor.submit(fetch_kpi, metric_name, config): metric_name
                for metric_name, config in essential_configs.items()
            }

            for future in as_completed(future_to_metric):
                kpi_id, value = future.result()
                if kpi_id is not None and value is not None:
                    screener_kpis[kpi_id] = value

        # 2. Build period records
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

        # 3. Create a dictionary of all available KPIs from the screener payload
        # This is now done before building period records

        # 4. Get KPI metadata to map metric names to KPI IDs
        metadata = self._client.get_kpi_metadata(api_key=api_key)
        metric_to_kpi = self._resolve_metric_kpis(metadata)

        # 5. Assemble the FinancialMetrics objects
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
                    config = FINANCIAL_METRICS_MAPPING.get(metric_name, {})
                    if config.get("is_percentage", False):
                        value = value / 100.0
                    payload[metric_name] = value

        # Second pass: fill in missing values from the bulk screener fetch
        for payload in records:
            for metric_name in metric_names:
                if payload.get(metric_name) is None:
                    kpi_id = metric_to_kpi.get(metric_name)
                    if kpi_id in screener_kpis:
                        value = screener_kpis[kpi_id]
                        if value is not None:
                            config = FINANCIAL_METRICS_MAPPING.get(metric_name, {})
                            if config.get("is_percentage", False):
                                value = value / 100.0
                            payload[metric_name] = value
        
        # Third pass: derived metrics
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
            # First check for explicit kpi_id in config
            explicit_kpi_id = config.get("kpi_id")
            if explicit_kpi_id is not None:
                kpi_id = explicit_kpi_id
            else:
                # Fall back to metadata matching
                for candidate in config.get("metadata_match", []) or []:
                    candidate_id = lookup.get(normalise_name(candidate))
                    if candidate_id is not None:
                        kpi_id = candidate_id
                        break
            metric_to_kpi[metric_name] = kpi_id
        return metric_to_kpi





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

            if shares is None:
                return None

            price_to_use = None
            if current_price is not None:
                price_to_use = current_price
                # Note: Börsdata API handles currency conversion via original=0/1 parameter
                # We rely on the API to provide data in consistent currency context
            else:
                price_to_use = safe_float(report.get("stock_Price_Average") or report.get("stockPriceAverage") or report.get("stock_Price_Close"))

            if price_to_use is None:
                return None

            return shares * price_to_use

        if metric_name in ("enterprise_value_to_ebit_ratio", "ev_to_ebit"):
            market_cap = payload.get("market_cap")

            if not report:
                return None

            net_debt = safe_float(report.get("net_Debt") or report.get("netDebt"))
            if net_debt is None:
                net_debt = 0.0

            operating_income = safe_float(report.get("operating_Income") or report.get("operatingIncome"))

            if market_cap is None or operating_income in (None, 0):
                return None

            enterprise_value = market_cap + net_debt
            return enterprise_value / operating_income

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
        # Note: Börsdata API ensures currency consistency when original=0/1 is used properly
        if current_price is not None and current_price > 0:
            if metric_name == "price_to_earnings_ratio":
                # First try to get P/E directly from Börsdata (KPI ID 2)
                pe_ratio = safe_float(ctx.kpis.get(2))  # KPI ID 2: P/E
                if pe_ratio is not None:
                    return pe_ratio

                # Fall back to calculation using EPS
                eps = safe_float(ctx.kpis.get(6))  # KPI ID 6: Earnings/share
                if eps is not None and eps != 0:
                    return current_price / eps

            elif metric_name == "price_to_book_ratio":
                bvps = safe_float(ctx.kpis.get(8))  # KPI ID 8: Book value/share
                if bvps is not None and bvps != 0:
                    return current_price / bvps

            elif metric_name == "price_to_sales_ratio":
                rps = safe_float(ctx.kpis.get(5))  # KPI ID 5: Revenue/share
                if rps is not None and rps != 0:
                    return current_price / rps

        # Populate revenue_per_share from KPI data
        if metric_name == "revenue_per_share":
            return safe_float(ctx.kpis.get(5))  # KPI ID 5: Revenue/share

        if metric_name == "free_cash_flow":
            if not report:
                return None
            return safe_float(report.get("free_Cash_Flow"))

        if metric_name == "beta":
            return None

        return None


__all__ = ["FinancialMetricsAssembler"]
