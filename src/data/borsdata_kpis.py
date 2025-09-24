"""Assembly helpers that translate Börsdata KPI payloads into `FinancialMetrics`."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

from .borsdata_client import BorsdataAPIError, BorsdataClient
from .borsdata_metrics_mapping import FINANCIAL_METRICS_MAPPING
from .models import FinancialMetrics

PERIOD_TO_REPORT_TYPE = {
    "ttm": "r12",
    "r12": "r12",
    "rolling": "r12",
    "annual": "year",
    "year": "year",
    "y": "year",
    "quarter": "quarter",
    "quarterly": "quarter",
    "q": "quarter",
}

DEFAULT_REPORT_TYPE = "r12"
SUMMARY_LIMIT_MULTIPLIER = 3  # Fetch a little extra so filtering by end_date still yields enough rows.


@dataclass
class PeriodRecord:
    """Aggregated per-period context that includes KPI values and report metadata."""

    key: Tuple[int, int]
    report_date: Optional[datetime] = None
    report_period: str = ""
    report: Dict[str, Any] = field(default_factory=dict)
    kpis: Dict[int, Optional[float]] = field(default_factory=dict)


def _normalise_name(value: str | None) -> str:
    return (value or "").strip().lower()


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        # Fall back to common formats (YYYY-MM-DD)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(cleaned.split("+")[0], fmt)
            except ValueError:
                continue
    return None


def _fallback_report_date(year: int, period: int, report_type: str) -> Optional[datetime]:
    if year is None or period is None:
        return None
    report_type = report_type.lower()
    if report_type == "year":
        return datetime(year, 12, 31)
    if report_type in {"quarter", "r12"}:
        month = max(1, min(12, period * 3))
        last_day = calendar.monthrange(year, month)[1]
        return datetime(year, month, last_day)
    return None


def _format_date(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.date().isoformat()


def _map_period_to_report_type(period: Optional[str]) -> str:
    if not period:
        return DEFAULT_REPORT_TYPE
    return PERIOD_TO_REPORT_TYPE.get(period.strip().lower(), DEFAULT_REPORT_TYPE)


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
    ) -> list[FinancialMetrics]:
        instrument = self._client.get_instrument(ticker, api_key=api_key)
        instrument_id = int(instrument["insId"])
        base_currency = instrument.get("reportCurrency") or instrument.get("stockPriceCurrency") or ""

        report_type = _map_period_to_report_type(period)
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

        end_date_dt = _parse_iso_date(end_date)
        contexts = self._build_period_records(
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
            calc_group = config.get("screener_calc_group")
            calc = config.get("screener_calc")
            if not calc_group or not calc:
                continue
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
    def _build_period_records(
        self,
        summary_payload: Dict[str, Any],
        reports_payload: Dict[str, Any],
        report_type: str,
        limit: int,
        end_date: Optional[datetime],
    ) -> list[PeriodRecord]:
        period_map: Dict[Tuple[int, int], PeriodRecord] = {}

        for group in summary_payload.get("kpis") or []:
            raw_kpi_id = group.get("KpiId") or group.get("kpiId")
            if raw_kpi_id is None:
                continue
            try:
                kpi_id = int(raw_kpi_id)
            except (TypeError, ValueError):
                continue
            for entry in group.get("values") or []:
                year = entry.get("y") or entry.get("year")
                period_value = entry.get("p") or entry.get("period")
                if year is None or period_value is None:
                    continue
                try:
                    key = (int(year), int(period_value))
                except (TypeError, ValueError):
                    continue
                ctx = period_map.setdefault(key, PeriodRecord(key=key))
                ctx.kpis[kpi_id] = _safe_float(entry.get("v"))

        for report in reports_payload.get("reports") or []:
            year = report.get("year")
            period_value = report.get("period")
            if year is None or period_value is None:
                continue
            try:
                key = (int(year), int(period_value))
            except (TypeError, ValueError):
                continue
            ctx = period_map.setdefault(key, PeriodRecord(key=key))
            ctx.report = report
            raw_date = report.get("report_End_Date") or report.get("reportDate") or report.get("report_Date")
            parsed = _parse_iso_date(raw_date)
            if parsed is None:
                parsed = _fallback_report_date(key[0], key[1], report_type)
            ctx.report_date = parsed
            ctx.report_period = _format_date(parsed) or f"{key[0]}-P{key[1]}"

        contexts: list[PeriodRecord] = []
        for key, ctx in period_map.items():
            if ctx.report_date is None:
                ctx.report_date = _fallback_report_date(key[0], key[1], report_type)
            if not ctx.report_period:
                ctx.report_period = _format_date(ctx.report_date) or f"{key[0]}-P{key[1]}"
            if end_date and ctx.report_date and ctx.report_date.date() > end_date.date():
                continue
            contexts.append(ctx)

        contexts.sort(
            key=lambda item: (
                item.report_date or datetime.min,
                item.key[0],
                item.key[1],
            ),
            reverse=True,
        )
        return contexts[:limit]

    def _resolve_metric_kpis(self, metadata: Iterable[Dict[str, Any]]) -> Dict[str, Optional[int]]:
        lookup: Dict[str, int] = {}
        for entry in metadata:
            name = _normalise_name(entry.get("nameEn"))
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
                candidate_id = lookup.get(_normalise_name(candidate))
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
        numeric = _safe_float(value)
        if numeric is None:
            return None
        if is_percent:
            numeric /= 100.0
        return numeric

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
                return _safe_float(kpi_value)
            if not report:
                return None
            shares = _safe_float(report.get("number_Of_Shares") or report.get("shares_outstanding") or report.get("sharesOutstanding"))
            price = _safe_float(report.get("stock_Price_Average") or report.get("stockPriceAverage") or report.get("stock_Price_Close"))
            if shares is None or price is None:
                return None
            return shares * price

        if metric_name == "operating_cash_flow_ratio":
            if not report:
                return None
            operating_cf = _safe_float(report.get("cash_Flow_From_Operating_Activities") or report.get("cashFlowFromOperatingActivities"))
            current_liabilities = _safe_float(report.get("current_Liabilities") or report.get("currentLiabilities"))
            if operating_cf is None or current_liabilities in (None, 0):
                return None
            return operating_cf / current_liabilities

        if metric_name == "operating_cycle":
            dso = _safe_float(payload.get("days_sales_outstanding"))
            if dso is None:
                return None
            inventory_turnover = _safe_float(payload.get("inventory_turnover"))
            days_inventory_outstanding = None
            if inventory_turnover not in (None, 0):
                days_inventory_outstanding = 365.0 / inventory_turnover
            if days_inventory_outstanding is None:
                return None
            return dso + days_inventory_outstanding

        return None


__all__ = ["FinancialMetricsAssembler"]
