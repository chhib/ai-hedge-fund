"""Assembly helpers that translate Börsdata KPI payloads into `FinancialMetrics`."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

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
            prices = self._client.get_stock_prices(instrument_id, original_currency=True, api_key=api_key)  # Use original currency for consistency
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
            original_currency=True,  # Use original currency for consistency
            api_key=api_key,
        )
        reports_payload = self._client.get_reports(
            instrument_id,
            report_type,
            max_count=summary_max,
            original_currency=True,  # Use original currency for consistency
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
                    # Apply percentage conversion for metrics flagged as percentages
                    config = FINANCIAL_METRICS_MAPPING.get(metric_name, {})
                    if config.get("is_percentage", False):
                        value = value / 100.0
                    payload[metric_name] = value

        # Bulk KPI retrieval for comprehensive coverage
        bulk_cache: Dict[int, Optional[float]] = {}
        missing_kpi_ids = []
        for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
            if config.get("source") == "kpi":
                kpi_id = metric_to_kpi.get(metric_name)
                if kpi_id is not None:
                    # Check if any record is missing this metric
                    for payload in records:
                        if payload.get(metric_name) is None:
                            if kpi_id not in missing_kpi_ids:
                                missing_kpi_ids.append(kpi_id)
                            break
        
        # Fetch missing KPIs in bulk using multiple endpoints
        if missing_kpi_ids:
            try:
                # Try bulk screener values first (most comprehensive)
                bulk_data = self._client.get_all_kpi_screener_values(instrument_id, api_key=api_key)
                screener_values = bulk_data.get("values", []) if bulk_data else []
                for value_entry in screener_values:
                    kpi_id = value_entry.get("kpiId")
                    if kpi_id in missing_kpi_ids:
                        numeric_value = safe_float(value_entry.get("n"))
                        if numeric_value is not None:
                            bulk_cache[kpi_id] = numeric_value
            except Exception:
                pass  # Continue with individual fetches

            # Fill remaining gaps with individual screener calls
            for kpi_id in missing_kpi_ids:
                if kpi_id not in bulk_cache:
                    try:
                        screener_response = self._client.get_kpi_screener_value(
                            instrument_id, kpi_id, "last", "latest", api_key=api_key
                        )
                        value = ((screener_response or {}).get("value") or {}).get("n")
                        numeric_value = safe_float(value)
                        if numeric_value is not None:
                            bulk_cache[kpi_id] = numeric_value
                    except Exception:
                        pass  # Continue to next KPI

            # Fill remaining gaps with holdings endpoint
            for kpi_id in missing_kpi_ids:
                if kpi_id not in bulk_cache:
                    try:
                        holdings_response = self._client.get_kpi_holdings(instrument_id, kpi_id, api_key=api_key)
                        if holdings_response and "value" in holdings_response:
                            numeric_value = safe_float(holdings_response["value"])
                            if numeric_value is not None:
                                bulk_cache[kpi_id] = numeric_value
                    except Exception:
                        pass  # Continue to next KPI

        # Apply bulk-fetched values to records
        for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
            if config.get("source") == "kpi":
                kpi_id = metric_to_kpi.get(metric_name)
                if kpi_id in bulk_cache:
                    bulk_value = bulk_cache[kpi_id]
                    if bulk_value is not None:
                        for payload in records:
                            if payload.get(metric_name) is None:
                                # Apply percentage conversion for metrics flagged as percentages
                                final_value = bulk_value
                                if config.get("is_percentage", False):
                                    final_value = bulk_value / 100.0
                                payload[metric_name] = final_value

        # Screener-derived fields for specialized calculations
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
                    # Apply percentage conversion for metrics flagged as percentages
                    # Note: screener values with calc="percent" are already converted in _fetch_screener_value
                    final_value = screener_value
                    if (screener_value is not None and 
                        config.get("is_percentage", False) and 
                        calc.lower() not in ["percent"]):
                        final_value = screener_value / 100.0
                    payload[metric_name] = final_value

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

        return None


__all__ = ["FinancialMetricsAssembler"]
