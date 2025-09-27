
import json

with open('/Users/ksu541/Code/ai-hedge-fund/docs/borsdata_kpis.json', 'r') as f:
    borsdata_kpis = json.load(f)

kpi_lookup = {kpi['nameEn'].lower().strip(): kpi['kpiId'] for kpi in borsdata_kpis}
kpi_lookup_sv = {kpi['nameSv'].lower().strip(): kpi['kpiId'] for kpi in borsdata_kpis}


FINANCIAL_METRICS_MAPPING = {
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
        "source": "derived",
        "metadata_match": ["P/E", "Price to Earnings"],
        "default_report_type": "r12",
        "derivation": "price_divided_by_eps",
        "dependencies": ["latest_close_price", "earnings_per_share"],
        "notes": "Calculated as current price divided by earnings per share (KPI ID 6)",
    },
    "price_to_book_ratio": {
        "source": "derived",
        "metadata_match": ["P/B", "Price to Book"],
        "default_report_type": "r12",
        "derivation": "price_divided_by_book_value",
        "dependencies": ["latest_close_price", "book_value_per_share"],
        "notes": "Calculated as current price divided by book value per share (KPI ID 8)",
    },
    "price_to_sales_ratio": {
        "source": "derived",
        "metadata_match": ["P/S", "Price to Sales"],
        "default_report_type": "r12",
        "derivation": "price_divided_by_revenue",
        "dependencies": ["latest_close_price", "revenue_per_share"],
        "notes": "Calculated as current price divided by revenue per share (KPI ID 5)",
    },
    "enterprise_value_to_ebitda_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/EBITDA"],
        "default_report_type": "r12",
    },
    "enterprise_value_to_ebit_ratio": {
        "source": "derived",
        "metadata_match": ["EV/EBIT"],
        "default_report_type": "r12",
        "dependencies": ["market_cap", "net_debt", "operating_income"],
        "notes": "Derived as (Market Cap + Net Debt) / EBIT. Falls back to KPI if available.",
    },
    "enterprise_value_to_revenue_ratio": {
        "source": "kpi",
        "metadata_match": ["EV/S"],
        "default_report_type": "r12",
    },
    "ev_to_ebit": {
        "source": "derived",
        "metadata_match": ["EV/EBIT"],
        "default_report_type": "r12",
        "dependencies": ["market_cap", "net_debt", "operating_income"],
        "notes": "Alias for enterprise_value_to_ebit_ratio. Derived as (Market Cap + Net Debt) / EBIT. Falls back to KPI if available.",
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
        "source": "derived",
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
        "metadata_match": ["Assets Turnover"],
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
        "metadata_match": ["Debt/Equity", "Debt to Equity"],
        "default_report_type": "year",
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
        "metadata_match": ["Revenue growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
        "screener_calc_group_overrides": {"quarter": "quarter"},
    },
    "earnings_growth": {
        "source": "screener",
        "metadata_match": ["Earnings Growth", "Net Income Growth"],
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
        "screener_calc_group_overrides": {"quarter": "quarter"},
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
        "default_report_type": "year",
        "screener_calc_group": "1year",
        "screener_calc": "percent",
        "screener_calc_group_overrides": {"quarter": "quarter"},
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
}

output_content = """# Financial Metrics to Börsdata KPI Mapping

| Metric Name | Börsdata KPI Name | Börsdata KPI ID |
|---|---|---|
"""

for metric_name, config in FINANCIAL_METRICS_MAPPING.items():
    metadata_matches = config.get('metadata_match', [])
    found_match = False
    for match in metadata_matches:
        kpi_id = kpi_lookup.get(match.lower().strip())
        if not kpi_id:
            kpi_id = kpi_lookup_sv.get(match.lower().strip())

        if kpi_id:
            output_content += f"| {metric_name} | {match} | {kpi_id} |\n"
            found_match = True
            break
    if not found_match:
        output_content += f"| {metric_name} | *Not Found* | *N/A* |\n"

with open('/Users/ksu541/Code/ai-hedge-fund/docs/financial_metrics_borsdata_mapping.md', 'w') as f:
    f.write(output_content)
