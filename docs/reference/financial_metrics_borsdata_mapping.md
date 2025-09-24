# FinancialMetrics ↔ Börsdata KPI/Report Mapping

This reference links each field in `src/data/models.py::FinancialMetrics` to the Börsdata endpoint(s) that will supply the data once the migration is complete. Identifiers are expressed in terms of the metadata returned from `GET /v1/instruments/kpis/metadata` and the calculation shortcuts exposed through the screener/history endpoints. Fetch the metadata once per sync (it is small) and resolve the definitive `kpiId` integers by matching on the `nameEn` field.

- **Report type mapping**: `period="ttm" → r12`, `period="annual" → year`, `period="quarterly" → quarter` (backfill additional periods as needed).
- **Latest point selection**: use `calcGroup=1year&calc=latest` where a latest-value shortcut exists; otherwise read the most recent entry from `GET /v1/instruments/{insId}/kpis/{reportType}/summary`.
- **YoY/percent changes**: prefer screener calculations (e.g. `calcGroup=1year&calc=percent`) before deriving manually.
- **Report-derived metrics**: explicitly documented below; fall back to `/v1/instruments/{insId}/reports/{reportType}?maxCount=...&original=1` when a dedicated KPI is missing.

| FinancialMetrics field | Source type | KPI metadata match (nameEn) | Endpoint & parameters | Notes |
| --- | --- | --- | --- | --- |
| `market_cap` | Derived | `Market Cap` KPI (if available) or reports + price | Prefer `calcGroup=1year&calc=latest`; otherwise compute `latest_close * sharesOutstanding` using `/stockprices/last` and report line `Shares Outstanding`. |
| `enterprise_value` | KPI | `Enterprise Value` | `GET /kpis/{kpiId}/r12/latest` or summary | Screener calc exposes latest EV; confirm currency via instrument metadata. |
| `price_to_earnings_ratio` | KPI | `P/E` / `Price to Earnings` | KPI summary (`reportType=r12`) | Use `summary` to retrieve alongside other valuation KPIs. |
| `price_to_book_ratio` | KPI | `P/B` / `Price to Book` | KPI summary (`reportType=r12`) |  |
| `price_to_sales_ratio` | KPI | `P/S` / `Price to Sales` | KPI summary (`reportType=r12`) |  |
| `enterprise_value_to_ebitda_ratio` | KPI | `EV/EBITDA` | KPI summary (`reportType=r12`) |  |
| `enterprise_value_to_revenue_ratio` | KPI | `EV/Sales` / `EV/Revenue` | KPI summary (`reportType=r12`) |  |
| `free_cash_flow_yield` | KPI | `FCF Yield` / `Free Cash Flow Yield` | KPI summary (`reportType=r12`) | If KPI absent, compute `free_cash_flow_per_share / price`. |
| `peg_ratio` | KPI | `PEG` | Screener calc `calcGroup=1year&calc=latest` | Relies on growth projections; validate availability for target instruments. |
| `gross_margin` | KPI | `Gross Margin` | KPI summary (`reportType=year|r12|quarter`) | Select report type matching `period`. |
| `operating_margin` | KPI | `Operating Margin` | KPI summary |  |
| `net_margin` | KPI | `Net Margin` / `Profit Margin` | KPI summary | Uses net income margin. |
| `return_on_equity` | KPI | `Return on Equity` | KPI summary |  |
| `return_on_assets` | KPI | `Return on Assets` | KPI summary |  |
| `return_on_invested_capital` | KPI | `ROIC` / `Return on Invested Capital` | KPI summary | Validate if KPI returns % or multiplier. |
| `asset_turnover` | KPI | `Asset Turnover` | KPI summary |  |
| `inventory_turnover` | KPI | `Inventory Turnover` | KPI summary |  |
| `receivables_turnover` | KPI | `Receivables Turnover` | KPI summary |  |
| `days_sales_outstanding` | KPI | `Days Sales Outstanding` | KPI summary |  |
| `operating_cycle` | Derived | `Operating Cycle` KPI if present; else `DSO + DIO` | Combine `days_sales_outstanding` and `days_inventory_outstanding` (reports) if dedicated KPI missing. |
| `working_capital_turnover` | KPI | `Working Capital Turnover` | KPI summary |  |
| `current_ratio` | KPI | `Current Ratio` | KPI summary |  |
| `quick_ratio` | KPI | `Quick Ratio` | KPI summary |  |
| `cash_ratio` | KPI | `Cash Ratio` | KPI summary |  |
| `operating_cash_flow_ratio` | Derived | N/A | Reports: `Operating Cash Flow / Current Liabilities` | Use cash-flow statement (`Net Cash from Operating Activities`) divided by balance-sheet `Current Liabilities`. |
| `debt_to_equity` | KPI | `Debt/Equity` | KPI summary |  |
| `debt_to_assets` | KPI | `Debt/Assets` | KPI summary |  |
| `interest_coverage` | KPI | `Interest Coverage` | KPI summary | Typically EBIT / interest expense. |
| `revenue_growth` | KPI | `Sales Growth` | Screener calc `calcGroup=1year&calc=percent` (annual) or `quarter` for QoQ | Map `period` to calc group. |
| `earnings_growth` | KPI | `Net Income Growth` | Screener calc `calcGroup=1year&calc=percent` |  |
| `book_value_growth` | KPI | `Equity Growth` / `Book Value Growth` | Screener calc `calcGroup=1year&calc=percent` |  |
| `earnings_per_share_growth` | KPI | `EPS Growth` | Screener calc `calcGroup=1year&calc=percent` |  |
| `free_cash_flow_growth` | KPI | `Free Cash Flow Growth` | Screener calc `calcGroup=1year&calc=percent` | If unavailable, compute from reports. |
| `operating_income_growth` | KPI | `Operating Income Growth` | Screener calc `calcGroup=1year&calc=percent` |  |
| `ebitda_growth` | KPI | `EBITDA Growth` | Screener calc `calcGroup=1year&calc=percent` |  |
| `payout_ratio` | KPI | `Payout Ratio` | KPI summary (`reportType=year`) | Confirm r12 availability. |
| `earnings_per_share` | KPI | `EPS` / `Earnings per Share` | KPI summary (use same report type as period) | For quarterly, request `reportType=quarter`. |
| `book_value_per_share` | KPI | `Book Value/Share` | KPI summary |  |
| `free_cash_flow_per_share` | KPI | `Free Cash Flow/Share` | KPI summary (`reportType=r12`) | Derive from cash-flow reports if KPI unavailable. |

## Implementation Notes
- Cache `kpiId` lookups (name → id) locally to avoid recomputing on every call.
- When a KPI is missing for a given instrument, gracefully fall back to the derived formulas instead of failing the entire payload.
- Growth KPIs exposed via screener endpoints use percentage values (not decimals); normalise to the existing `FinancialMetrics` expectations.
- The KPI endpoints return numeric values without currency units; pair with `reportCurrency` from instrument metadata where currency context is required.
- For derived ratios, prefer report data expressed in the instrument's `reportCurrency` and ensure consistent period alignment before computing.

## Open Items
- Confirm exact `nameEn` strings and capture their resolved `kpiId` values once authenticated metadata access is available.
- Identify the report keys (`Shares Outstanding`, `Net Cash from Operating Activities`, `Current Liabilities`, etc.) and document their exact JSON paths for the derived metrics section.
- Validate that all KPIs deliver data for the target instruments (Nordic + potential Global); record fallbacks where values are consistently `null`.
