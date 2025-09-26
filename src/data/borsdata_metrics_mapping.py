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
    screener_calc_group_overrides: dict[str, str]
    notes: str
    dependencies: list[str]


# Mapping keyed by FinancialMetrics attribute name
FINANCIAL_METRICS_MAPPING: dict[str, MetricMapping] = {
    "market_cap": {
        "source": "derived",
        "metadata_match": ["Market Cap"],
        "default_report_type": "r12",
        "notes": ("Use KPI when available; otherwise multiply latest close price by the " "most recent shares outstanding from reports."),
        "dependencies": ["latest_close_price", "shares_outstanding"],
    },
    "enterprise_value": {
        "source": "kpi",
        "metadata_match": ["Enterprise Value"],
        "kpi_id": 49,
        "default_report_type": "r12",
    },
    "price_to_earnings_ratio": {
        "source": "kpi",
        "metadata_match": ["P/E", "Price to Earnings"],
        "kpi_id": 2,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Direct KPI call to Börsdata P/E ratio (KPI ID 2)",
    },
    "price_to_book_ratio": {
        "source": "kpi",
        "metadata_match": ["P/B", "Price to Book"],
        "kpi_id": 4,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Direct KPI call to Börsdata P/B ratio (KPI ID 4)",
    },
    "price_to_sales_ratio": {
        "source": "kpi",
        "metadata_match": ["P/S", "Price to Sales"],
        "kpi_id": 3,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Direct KPI call to Börsdata P/S ratio (KPI ID 3)",
    },
    "enterprise_value_to_ebitda_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/EBITDA"],
        "kpi_id": 11,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "enterprise_value_to_ebit_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/EBIT"],
        "kpi_id": 10,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Direct KPI call to Börsdata EV/EBIT ratio (KPI ID 10)",
    },
    "enterprise_value_to_revenue_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/S"],
        "kpi_id": 15,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "ev_to_ebit": {
        "source": "kpi",
        "metadata_match": ["EV/EBIT"],
        "kpi_id": 10,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Alias for enterprise_value_to_ebit_ratio. Direct KPI call (KPI ID 10)",
    },
    "net_debt": {
        "source": "kpi",
        "metadata_match": ["Net Debt"],
        "default_report_type": "r12",
    },
    "operating_income": {
        "source": "kpi",
        "metadata_match": ["Operating Income", "EBIT"],
        "default_report_type": "r12",
    },
    "free_cash_flow_yield": {
        "source": "kpi",
        "metadata_match": ["FCF Yield"],
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
        "kpi_id": 28,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "operating_margin": {
        "source": "kpi",
        "metadata_match": ["Operating Margin"],
        "kpi_id": 29,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "net_margin": {
        "source": "kpi",
        "metadata_match": ["Net Margin", "Profit Margin"],
        "kpi_id": 30,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "return_on_equity": {
        "source": "kpi",
        "metadata_match": ["Return on Equity"],
        "kpi_id": 33,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "return_on_assets": {
        "source": "kpi",
        "metadata_match": ["Return on Assets"],
        "kpi_id": 34,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "return_on_invested_capital": {
        "source": "kpi",
        "metadata_match": ["Return on Invested Capital", "ROIC"],
        "kpi_id": 37,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "asset_turnover": {
        "source": "kpi",
        "metadata_match": ["Assets Turnover"],
        "kpi_id": 38,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
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
        "notes": ("If the dedicated KPI is unavailable, add DSO and days inventory outstanding " "derived from report data."),
    },
    "working_capital_turnover": {
        "source": "kpi",
        "metadata_match": ["Working Capital Turnover"],
        "default_report_type": "r12",
    },
    "current_ratio": {
        "source": "kpi",
        "metadata_match": ["Current Ratio"],
        "kpi_id": 44,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
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
        "metadata_match": ["Debt/Equity", "Debt to Equity"],
        "kpi_id": 40,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
    },
    "debt_to_assets": {
        "source": "derived",
        "metadata_match": ["Debt/Assets"],
        "default_report_type": "year",
        "dependencies": ["total_liabilities", "total_assets"],
    },
    "interest_coverage": {
        "source": "kpi",
        "metadata_match": ["Interest Coverage"],
        "default_report_type": "r12",
    },
    "revenue_growth": {
        "source": "screener",
        "metadata_match": ["Sales Growth %"],
        "kpi_id": 26,
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "cagr",
        "screener_calc_group_overrides": {"quarter": "1year", "3year": "3year", "5year": "5year", "r12": "1year"},
    },
    "earnings_growth": {
        "source": "screener",
        "metadata_match": ["EPS Growth %"],
        "kpi_id": 27,
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "cagr",
        "screener_calc_group_overrides": {"quarter": "1year", "3year": "3year", "5year": "5year"},
    },
    "book_value_growth": {
        "source": "screener",
        "metadata_match": ["Book Value Growth", "Equity Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
        "screener_calc_group_overrides": {"quarter": "quarter"},
    },
    "earnings_per_share_growth": {
        "source": "derived",
        "metadata_match": ["EPS Growth"],
        "default_report_type": "year",
        "dependencies": ["earnings_per_share"],
    },
    "free_cash_flow_growth": {
        "source": "screener",
        "metadata_match": ["FCF growth"],
        "kpi_id": 23,
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "cagr",
        "screener_calc_group_overrides": {"quarter": "1year", "3year": "3year", "5year": "5year"},
    },
    "operating_income_growth": {
        "source": "screener",
        "metadata_match": ["EBIT Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
        "screener_calc_group_overrides": {"quarter": "quarter"},
    },
    "ebitda_growth": {
        "source": "derived",
        "metadata_match": ["EBITDA Growth"],
        "default_report_type": "year",
        "dependencies": ["ebitda"],
    },
    "payout_ratio": {
        "source": "kpi",
        "metadata_match": ["Dividend Payout"],
        "default_report_type": "year",
    },
    "earnings_per_share": {
        "source": "kpi",
        "metadata_match": ["Earnings/share"],
        "kpi_id": 6,
        "default_report_type": "r12",
        "notes": "Available as KPI ID 6",
    },
    "book_value_per_share": {
        "source": "kpi",
        "metadata_match": ["Book value/share"],
        "default_report_type": "r12",
        "notes": "Available as KPI ID 8",
    },
    "free_cash_flow_per_share": {
        "source": "derived",
        "metadata_match": ["Free Cash Flow per Share", "FCF/Share"],
        "default_report_type": "r12",
    },
    "revenue_per_share": {
        "source": "kpi",
        "metadata_match": ["Revenue/share"],
        "default_report_type": "r12",
        "notes": "Available as KPI ID 5",
    },
    # New value-add metrics from Börsdata
    "price_to_fcf_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/FCF"],
        "kpi_id": 13,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Enterprise Value to Free Cash Flow ratio - new metric from Börsdata",
    },
    "fcf_margin": {
        "source": "kpi",
        "metadata_match": ["FCF margin"],
        "kpi_id": 31,
        "default_report_type": "year",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Free Cash Flow margin - new metric from Börsdata",
    },
    "cash_to_price_ratio": {
        "source": "kpi",
        "metadata_match": ["Cash/Price"],
        "kpi_id": 25,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Cash to Price ratio - new metric from Börsdata",
    },
    "dividend_yield": {
        "source": "kpi",
        "metadata_match": ["Dividend Yield"],
        "kpi_id": 1,
        "default_report_type": "r12",
        "screener_calc_group": "last",
        "screener_calc": "latest",
        "notes": "Dividend yield percentage - direct from Börsdata KPI",
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
    "revenue_per_share": {
        "statement": "kpi",
        "kpi_id": 5,
        "keys": ["Revenue/share"],
    },
    "price_divided_by_eps": {
        "statement": "calculated",
        "calculation": "divide",
        "numerator": "latest_close_price",
        "denominator": "earnings_per_share",
    },
    "price_divided_by_book_value": {
        "statement": "calculated",
        "calculation": "divide",
        "numerator": "latest_close_price",
        "denominator": "book_value_per_share",
    },
    "price_divided_by_revenue": {
        "statement": "calculated",
        "calculation": "divide",
        "numerator": "latest_close_price",
        "denominator": "revenue_per_share",
    },
}
"""Helper hints for translating Börsdata report payload keys into derived metrics."""
