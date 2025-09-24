"""Shared utilities for assembling Börsdata payloads into period-aligned records."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

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
    """Aggregated per-period context combining KPI values with report metadata."""

    key: Tuple[int, int]
    report_date: Optional[datetime] = None
    report_period: str = ""
    report: Dict[str, Any] = field(default_factory=dict)
    kpis: Dict[int, Optional[float]] = field(default_factory=dict)


def normalise_name(value: str | None) -> str:
    return (value or "").strip().lower()


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_iso_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(cleaned.split("+")[0], fmt)
            except ValueError:
                continue
    return None


def fallback_report_date(year: int | None, period: int | None, report_type: str) -> Optional[datetime]:
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


def format_report_date(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.date().isoformat()


def map_period_to_report_type(period: Optional[str]) -> str:
    if not period:
        return DEFAULT_REPORT_TYPE
    return PERIOD_TO_REPORT_TYPE.get(period.strip().lower(), DEFAULT_REPORT_TYPE)


def build_period_records(
    summary_payload: Dict[str, Any],
    reports_payload: Dict[str, Any],
    report_type: str,
    limit: int,
    end_date: Optional[datetime],
) -> list[PeriodRecord]:
    """Combine KPI summary + report payloads into ordered period contexts."""

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
            ctx.kpis[kpi_id] = safe_float(entry.get("v"))

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
        raw_date = (
            report.get("report_End_Date")
            or report.get("reportDate")
            or report.get("report_Date")
        )
        parsed = parse_iso_date(raw_date)
        if parsed is None:
            parsed = fallback_report_date(key[0], key[1], report_type)
        ctx.report_date = parsed
        ctx.report_period = format_report_date(parsed) or f"{key[0]}-P{key[1]}"

    contexts: list[PeriodRecord] = []
    for key, ctx in period_map.items():
        if ctx.report_date is None:
            ctx.report_date = fallback_report_date(key[0], key[1], report_type)
        if not ctx.report_period:
            ctx.report_period = format_report_date(ctx.report_date) or f"{key[0]}-P{key[1]}"
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

