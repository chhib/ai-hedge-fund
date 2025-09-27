"""Helpers that adapt Börsdata financial reports into application line items."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from .borsdata_client import BorsdataClient
from .borsdata_common import (
    SUMMARY_LIMIT_MULTIPLIER,
    build_period_records,
    map_period_to_report_type,
    normalise_name,
    parse_iso_date,
    safe_float,
)

# Direct report field lookups keyed by requested line item (normalised)
REPORT_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "revenue": ("revenues", "net_Sales", "netSales"),
    "gross_profit": ("gross_Income", "grossIncome"),
    "operating_income": ("operating_Income", "operatingIncome"),
    "net_income": ("profit_To_Equity_Holders", "net_Income", "netIncome"),
    "free_cash_flow": ("free_Cash_Flow", "freeCashFlow"),
    "cash_and_equivalents": ("cash_And_Equivalents", "cashAndEquivalents"),
    "current_assets": ("current_Assets", "currentAssets"),
    "current_liabilities": ("current_Liabilities", "currentLiabilities"),
    "total_assets": ("total_Assets", "totalAssets"),
    "shareholders_equity": ("total_Equity", "totalEquity"),
    "dividends_and_other_cash_distributions": ("dividend",),
    "outstanding_shares": ("number_Of_Shares", "numberOfShares"),
    "earnings_per_share": ("earnings_Per_Share", "earningsPerShare"),
    "intangible_assets": ("intangible_Assets", "intangibleAssets"),
    "non_current_liabilities": ("non_Current_Liabilities", "nonCurrentLiabilities"),
    "net_debt": ("net_Debt", "netDebt"),
    "cash_flow_from_operating_activities": ("cash_Flow_From_Operating_Activities", "cashFlowFromOperatingActivities"),
    "cash_flow_from_financing_activities": ("cash_Flow_From_Financing_Activities", "cashFlowFromFinancingActivities"),
    # Missing line items that original agents need
    "book_value_per_share": ("book_Value_Per_Share", "bookValuePerShare"),
    "total_debt": ("total_Debt", "totalDebt"),
    "capital_expenditure": ("capital_Expenditure", "capitalExpenditure", "capex"),
    "operating_expense": ("operating_Expenses", "operatingExpenses"),
    "total_liabilities": ("total_Liabilities", "totalLiabilities"),
}

# KPI fallbacks for derived values (normalised names)
LINE_ITEM_KPI_MAPPING: dict[str, tuple[str, ...]] = {
    "ebitda": ("ebitda",),
    "depreciation_and_amortization": (
        "depreciation and amortization",
        "depreciation amortization",
        "depreciation & amortization",
    ),
    "interest_expense": ("interest expense",),
    "research_and_development": ("research and development", "r&d expenses"),
    "return_on_invested_capital": ("return on invested capital", "roic"),
    "gross_margin": ("gross margin",),
    "operating_margin": ("operating margin",),
    # KPI fallbacks for missing line items
    "book_value_per_share": ("book value per share", "bvps"),
    "total_debt": ("total debt", "debt"),
    "capital_expenditure": ("capital expenditure", "capex", "cap ex"),
    "debt_to_equity": ("debt to equity", "debt/equity", "d/e ratio"),
    "operating_expense": ("operating expenses", "opex"),
    "total_liabilities": ("total liabilities", "liabilities"),
}


class LineItemAssembler:
    """Constructs application line-item payloads from Börsdata reports + KPI summaries."""

    def __init__(self, client: BorsdataClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def assemble(
        self,
        ticker: str,
        line_items: Iterable[str],
        *,
        end_date: Optional[str],
        period: Optional[str],
        limit: int,
        api_key: Optional[str],
        use_global: bool = False,
    ) -> list[Dict[str, Any]]:
        requested = list(dict.fromkeys(line_items))
        if not requested or limit <= 0:
            return []

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
        kpi_lookup = self._build_kpi_lookup(metadata)
        line_item_kpis = self._resolve_line_item_kpis(kpi_lookup)

        # Get screener data as additional fallback
        screener_data = None
        try:
            screener_data = self._client.get_all_kpi_screener_values(instrument_id, api_key=api_key)
        except Exception:
            # Screener data is optional - continue without it
            pass

        period_label = period.strip().lower() if period else "ttm"
        results: list[Dict[str, Any]] = []
        for ctx in contexts:
            report = ctx.report or {}
            currency = report.get("currency") or base_currency
            payload: Dict[str, Any] = {
                "ticker": ticker.upper(),
                "report_period": ctx.report_period,
                "period": period_label,
                "currency": currency,
            }
            for item in requested:
                normalised = normalise_name(item)
                payload[item] = self._compute_value(normalised, report, ctx, line_item_kpis, screener_data, kpi_lookup)
            results.append(payload)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_kpi_lookup(metadata: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        lookup: Dict[str, int] = {}
        for entry in metadata or []:
            raw_id = entry.get("kpiId") or entry.get("KpiId")
            try:
                kpi_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            name = normalise_name(entry.get("nameEn"))
            if not name:
                continue
            lookup[name] = kpi_id
        return lookup

    def _resolve_line_item_kpis(self, lookup: Dict[str, int]) -> Dict[str, list[int]]:
        mapping: Dict[str, list[int]] = {}
        for item, candidates in LINE_ITEM_KPI_MAPPING.items():
            ids: list[int] = []
            for candidate in candidates:
                kpi_id = lookup.get(normalise_name(candidate))
                if kpi_id is not None and kpi_id not in ids:
                    ids.append(kpi_id)
            if ids:
                mapping[item] = ids
        return mapping

    def _extract_report_value(self, report: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
        for key in keys:
            if key in report and report[key] not in (None, ""):
                return safe_float(report[key])
        return None

    def _get_kpi_value(self, ctx, kpi_ids: list[int]) -> Optional[float]:
        for kpi_id in kpi_ids:
            value = ctx.kpis.get(kpi_id)
            if value is not None:
                return value
        return None

    def _get_screener_value(self, item: str, screener_data: Optional[Dict[str, Any]], kpi_lookup: Optional[Dict[str, int]]) -> Optional[float]:
        """Get value from screener data as final fallback."""
        if not screener_data or not kpi_lookup:
            return None

        # Try to find KPI IDs for this line item
        kpi_ids = []
        if item in LINE_ITEM_KPI_MAPPING:
            for candidate in LINE_ITEM_KPI_MAPPING[item]:
                kpi_id = kpi_lookup.get(normalise_name(candidate))
                if kpi_id is not None:
                    kpi_ids.append(kpi_id)

        # Look for values in screener data
        screener_values = screener_data.get("values", [])
        for entry in screener_values:
            entry_kpi_id = entry.get("kpiId")
            if entry_kpi_id in kpi_ids:
                value = entry.get("n")  # 'n' is the numeric value field in screener data
                if value is not None:
                    return safe_float(value)

        return None

    def _compute_value(
        self,
        item: str,
        report: Dict[str, Any],
        ctx,
        line_item_kpis: Dict[str, list[int]],
        screener_data: Optional[Dict[str, Any]] = None,
        kpi_lookup: Optional[Dict[str, int]] = None,
    ) -> Optional[float]:
        report_value = self._extract_report_value

        # Frequently re-used building blocks (all floats or None)
        revenue = report_value(report, REPORT_FIELD_MAP.get("revenue", ()))
        gross_profit = report_value(report, REPORT_FIELD_MAP.get("gross_profit", ()))
        operating_income = report_value(report, REPORT_FIELD_MAP.get("operating_income", ()))
        net_income = report_value(report, REPORT_FIELD_MAP.get("net_income", ()))
        free_cash_flow = report_value(report, REPORT_FIELD_MAP.get("free_cash_flow", ()))
        cash = report_value(report, REPORT_FIELD_MAP.get("cash_and_equivalents", ()))
        current_assets = report_value(report, REPORT_FIELD_MAP.get("current_assets", ()))
        current_liabilities = report_value(report, REPORT_FIELD_MAP.get("current_liabilities", ()))
        total_assets = report_value(report, REPORT_FIELD_MAP.get("total_assets", ()))
        equity = report_value(report, REPORT_FIELD_MAP.get("shareholders_equity", ()))
        non_current_liabilities = report_value(report, REPORT_FIELD_MAP.get("non_current_liabilities", ()))
        net_debt = report_value(report, REPORT_FIELD_MAP.get("net_debt", ()))
        shares = report_value(report, REPORT_FIELD_MAP.get("outstanding_shares", ()))
        earnings_per_share = report_value(report, REPORT_FIELD_MAP.get("earnings_per_share", ()))

        if current_liabilities is not None and non_current_liabilities is not None:
            total_liabilities = current_liabilities + non_current_liabilities
        elif total_assets is not None and equity is not None:
            total_liabilities = total_assets - equity
        else:
            total_liabilities = None

        if net_debt is not None and cash is not None:
            total_debt_value = net_debt + cash
        elif net_debt is not None:
            total_debt_value = net_debt
        else:
            total_debt_value = None

        working_capital_value = None
        if current_assets is not None and current_liabilities is not None:
            working_capital_value = current_assets - current_liabilities

        gross_margin_value = None
        if revenue not in (None, 0) and gross_profit is not None:
            gross_margin_value = gross_profit / revenue

        operating_margin_value = None
        if revenue not in (None, 0) and operating_income is not None:
            operating_margin_value = operating_income / revenue

        kpi_cache: Dict[str, Optional[float]] = {}
        for key in (
            "ebitda",
            "depreciation_and_amortization",
            "interest_expense",
            "research_and_development",
            "return_on_invested_capital",
            "gross_margin",
            "operating_margin",
        ):
            ids = line_item_kpis.get(key)
            kpi_cache[key] = self._get_kpi_value(ctx, ids) if ids else None

        if item == "revenue":
            return revenue
        if item == "gross_profit":
            return gross_profit
        if item == "operating_income" or item == "ebit":
            return operating_income
        if item == "net_income":
            return net_income
        if item == "free_cash_flow":
            return free_cash_flow
        if item == "cash_and_equivalents":
            return cash
        if item == "current_assets":
            return current_assets
        if item == "current_liabilities":
            return current_liabilities
        if item == "total_assets":
            return total_assets
        if item == "shareholders_equity":
            return equity
        if item == "book_value_per_share":
            if equity is None or shares in (None, 0):
                return None
            return equity / shares
        if item == "dividends_and_other_cash_distributions":
            return report_value(report, REPORT_FIELD_MAP.get("dividends_and_other_cash_distributions", ()))
        if item == "outstanding_shares":
            return shares
        if item == "earnings_per_share":
            return earnings_per_share
        if item == "goodwill_and_intangible_assets":
            return report_value(report, REPORT_FIELD_MAP.get("intangible_assets", ()))
        if item == "total_liabilities":
            return total_liabilities
        if item == "working_capital":
            return working_capital_value
        if item == "capital_expenditure":
            operating_cf = report_value(report, REPORT_FIELD_MAP.get("cash_flow_from_operating_activities", ()))
            if operating_cf is None or free_cash_flow is None:
                return None
            return operating_cf - free_cash_flow
        if item == "operating_expense":
            if revenue is None or operating_income is None:
                return None
            return revenue - operating_income
        if item == "gross_margin":
            if gross_margin_value is not None:
                return gross_margin_value
            return kpi_cache.get("gross_margin")
        if item == "operating_margin":
            if operating_margin_value is not None:
                return operating_margin_value
            return kpi_cache.get("operating_margin")
        if item == "total_debt":
            return total_debt_value
        if item == "debt_to_equity":
            total_debt = total_debt_value
            if total_debt is None or equity in (None, 0):
                return None
            return total_debt / equity if equity else None
        if item == "return_on_invested_capital":
            roic_kpi = kpi_cache.get("return_on_invested_capital")
            if roic_kpi is not None:
                return roic_kpi
            total_debt = total_debt_value
            if equity is None or total_debt is None:
                return None
            invested_capital = total_debt + equity - (cash or 0.0)
            if invested_capital in (None, 0) or operating_income is None:
                return None
            return operating_income / invested_capital
        if item == "ebitda":
            value = kpi_cache.get("ebitda")
            if value is not None:
                return value
            depreciation = kpi_cache.get("depreciation_and_amortization")
            if depreciation is None or operating_income is None:
                return None
            return operating_income + depreciation
        if item == "depreciation_and_amortization":
            value = kpi_cache.get("depreciation_and_amortization")
            if value is not None:
                return value
            ebitda = kpi_cache.get("ebitda")
            if ebitda is None or operating_income is None:
                return None
            return ebitda - operating_income
        if item == "interest_expense":
            return kpi_cache.get("interest_expense")
        if item == "research_and_development":
            return kpi_cache.get("research_and_development")
        if item == "issuance_or_purchase_of_equity_shares":
            return report_value(report, REPORT_FIELD_MAP.get("cash_flow_from_financing_activities", ()))

        # Fallback: try direct report match if we have a mapping
        raw = self._extract_report_value(report, REPORT_FIELD_MAP.get(item, ()))
        if raw is not None:
            return raw

        # Final fallback: try screener data
        return self._get_screener_value(item, screener_data, kpi_lookup)
