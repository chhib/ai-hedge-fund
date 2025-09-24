"""Reference mapping between internal FinancialMetrics fields and Börsdata KPI inputs.

The mapping intentionally refers to KPI metadata by `nameEn` strings so the
client can resolve concrete `kpiId` values at runtime after downloading
`/v1/instruments/kpis/metadata`. Growth and latest-value shortcuts lean on the
screener calculation endpoints where Börsdata exposes them; everything else can
be satisfied through KPI summary payloads. Derived entries fall back to
financial reports when no direct KPI exists.
"""

from __future__ import annotations

from typing import Literal, TypedDict

SourceType = Literal["kpi", "screener", "derived"]
ReportType = Literal["year", "r12", "quarter"]


class MetricMapping(TypedDict, total=False):
    source: SourceType
    metadata_match: list[str]
    default_report_type: ReportType
    screener_calc_group: str
    screener_calc: str
    notes: str
    dependencies: list[str]


# Mapping keyed by FinancialMetrics attribute name
FINANCIAL_METRICS_MAPPING: dict[str, MetricMapping] = {
    "market_cap": {
        "source": "derived",
        "metadata_match": ["Market Cap"],
        "default_report_type": "r12",
        "notes": (
            "Use KPI when available; otherwise multiply latest close price by the "
            "most recent shares outstanding from reports."
        ),
        "dependencies": ["latest_close_price", "shares_outstanding"],
    },
    "enterprise_value": {
        "source": "kpi",
        "metadata_match": ["Enterprise Value"],
        "default_report_type": "r12",
    },
    "price_to_earnings_ratio": {
        "source": "kpi",
        "metadata_match": ["P/E", "Price to Earnings"],
        "default_report_type": "r12",
    },
    "price_to_book_ratio": {
        "source": "kpi",
        "metadata_match": ["P/B", "Price to Book"],
        "default_report_type": "r12",
    },
    "price_to_sales_ratio": {
        "source": "kpi",
        "metadata_match": ["P/S", "Price to Sales"],
        "default_report_type": "r12",
    },
    "enterprise_value_to_ebitda_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/EBITDA"],
        "default_report_type": "r12",
    },
    "enterprise_value_to_revenue_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/Sales", "EV/Revenue"],
        "default_report_type": "r12",
    },
    "free_cash_flow_yield": {
        "source": "kpi",
        "metadata_match": ["Free Cash Flow Yield", "FCF Yield"],
        "default_report_type": "r12",
    },
    "peg_ratio": {
        "source": "screener",
        "metadata_match": ["PEG"],
        "default_report_type": "r12",
        "screener_calc_group": "1year",
        "screener_calc": "latest",
    },
    "gross_margin": {
        "source": "kpi",
        "metadata_match": ["Gross Margin"],
        "default_report_type": "year",
    },
    "operating_margin": {
        "source": "kpi",
        "metadata_match": ["Operating Margin"],
        "default_report_type": "year",
    },
    "net_margin": {
        "source": "kpi",
        "metadata_match": ["Net Margin", "Profit Margin"],
        "default_report_type": "year",
    },
    "return_on_equity": {
        "source": "kpi",
        "metadata_match": ["Return on Equity"],
        "default_report_type": "r12",
    },
    "return_on_assets": {
        "source": "kpi",
        "metadata_match": ["Return on Assets"],
        "default_report_type": "r12",
    },
    "return_on_invested_capital": {
        "source": "kpi",
        "metadata_match": ["Return on Invested Capital", "ROIC"],
        "default_report_type": "r12",
    },
    "asset_turnover": {
        "source": "kpi",
        "metadata_match": ["Asset Turnover"],
        "default_report_type": "r12",
    },
    "inventory_turnover": {
        "source": "kpi",
        "metadata_match": ["Inventory Turnover"],
        "default_report_type": "r12",
    },
    "receivables_turnover": {
        "source": "kpi",
        "metadata_match": ["Receivables Turnover"],
        "default_report_type": "r12",
    },
    "days_sales_outstanding": {
        "source": "kpi",
        "metadata_match": ["Days Sales Outstanding"],
        "default_report_type": "r12",
    },
    "operating_cycle": {
        "source": "derived",
        "metadata_match": ["Operating Cycle"],
        "default_report_type": "r12",
        "dependencies": ["days_sales_outstanding", "days_inventory_outstanding"],
        "notes": (
            "If the dedicated KPI is unavailable, add DSO and days inventory outstanding "
            "derived from report data."
        ),
    },
    "working_capital_turnover": {
        "source": "kpi",
        "metadata_match": ["Working Capital Turnover"],
        "default_report_type": "r12",
    },
    "current_ratio": {
        "source": "kpi",
        "metadata_match": ["Current Ratio"],
        "default_report_type": "year",
    },
    "quick_ratio": {
        "source": "kpi",
        "metadata_match": ["Quick Ratio"],
        "default_report_type": "year",
    },
    "cash_ratio": {
        "source": "kpi",
        "metadata_match": ["Cash Ratio"],
        "default_report_type": "year",
    },
    "operating_cash_flow_ratio": {
        "source": "derived",
        "metadata_match": ["Operating Cash Flow Ratio"],
        "default_report_type": "r12",
        "dependencies": ["operating_cash_flow", "current_liabilities"],
        "notes": "Divide operating cash flow (cash-flow report) by current liabilities (balance sheet).",
    },
    "debt_to_equity": {
        "source": "kpi",
        "metadata_match": ["Debt/Equity"],
        "default_report_type": "year",
    },
    "debt_to_assets": {
        "source": "kpi",
        "metadata_match": ["Debt/Assets"],
        "default_report_type": "year",
    },
    "interest_coverage": {
        "source": "kpi",
        "metadata_match": ["Interest Coverage"],
        "default_report_type": "r12",
    },
    "revenue_growth": {
        "source": "screener",
        "metadata_match": ["Sales Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "earnings_growth": {
        "source": "screener",
        "metadata_match": ["Earnings Growth", "Net Income Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "book_value_growth": {
        "source": "screener",
        "metadata_match": ["Book Value Growth", "Equity Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "earnings_per_share_growth": {
        "source": "screener",
        "metadata_match": ["EPS Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "free_cash_flow_growth": {
        "source": "screener",
        "metadata_match": ["Free Cash Flow Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "operating_income_growth": {
        "source": "screener",
        "metadata_match": ["Operating Income Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "ebitda_growth": {
        "source": "screener",
        "metadata_match": ["EBITDA Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
    },
    "payout_ratio": {
        "source": "kpi",
        "metadata_match": ["Payout Ratio"],
        "default_report_type": "year",
    },
    "earnings_per_share": {
        "source": "kpi",
        "metadata_match": ["Earnings per Share", "EPS"],
        "default_report_type": "quarter",
    },
    "book_value_per_share": {
        "source": "kpi",
        "metadata_match": ["Book Value per Share"],
        "default_report_type": "year",
    },
    "free_cash_flow_per_share": {
        "source": "kpi",
        "metadata_match": ["Free Cash Flow per Share", "FCF/Share"],
        "default_report_type": "r12",
    },
}


DERIVED_REPORT_DEPENDENCIES = {
    "operating_cash_flow": {
        "statement": "cash_flow",
        "keys": ["NetCashFromOperatingActivities", "OperatingCashFlow"],
    },
    "current_liabilities": {
        "statement": "balance_sheet",
        "keys": ["CurrentLiabilities"],
    },
    "shares_outstanding": {
        "statement": "income_statement",
        "keys": ["AverageSharesOutstanding", "SharesOutstanding"],
    },
    "days_inventory_outstanding": {
        "statement": "calculated",
        "keys": ["DaysInventoryOutstanding"],
    },
    "latest_close_price": {
        "statement": "price",
        "keys": ["c"],
    },
}
"""Helper hints for translating Börsdata report payload keys into derived metrics."""
