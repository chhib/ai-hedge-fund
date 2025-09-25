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
            for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
                if config.get("source") != "derived":
                    continue
                if payload.get(metric_name) is not None:
                    continue
                derived_value = self._compute_derived_metric(metric_name, payload, ctx)
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

    def _compute_derived_metric(
        self,
        metric_name: str,
        payload: Dict[str, Any],
        ctx: PeriodRecord,
    ) -> Optional[float]:
        report = ctx.report
        if metric_name == "market_cap":
            kpi_value = payload.get(metric_name)
            if kpi_value is not None:
                return safe_float(kpi_value)
            if not report:
                return None
            shares = safe_float(
                report.get("number_Of_Shares")
                or report.get("shares_outstanding")
                or report.get("sharesOutstanding")
            )
            price = safe_float(
                report.get("stock_Price_Average")
                or report.get("stockPriceAverage")
                or report.get("stock_Price_Close")
            )
            if shares is None or price is None:
                return None
            return shares * price

        if metric_name == "operating_cash_flow_ratio":
            if not report:
                return None
            operating_cf = safe_float(
                report.get("cash_Flow_From_Operating_Activities")
                or report.get("cashFlowFromOperatingActivities")
            )
            current_liabilities = safe_float(
                report.get("current_Liabilities")
                or report.get("currentLiabilities")
            )
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

        return None


__all__ = ["FinancialMetricsAssembler"]
