# Börsdata Endpoint Mapping

This document captures the Börsdata REST API endpoints that will replace the legacy FinancialDatasets integrations. It is based on the official Swagger definition stored in `docs/reference/swagger_v1.json` (retrieved 2025-09-24) and highlights functional coverage as well as gaps that need follow-up solutions.

## Authentication & Base URL
- Base URL: `https://apiservice.borsdata.se` (per Swagger `servers` entry).
- All requests require the `authKey` query parameter carrying `BORSDATA_API_KEY`.
- Responses default to JSON; gzip compression is supported but optional.

## Instrument & Metadata Lookup
Purpose: convert user tickers to Börsdata instrument IDs and capture listing metadata used across the pipeline.
- `GET /v1/instruments` → `InstrumentV1[]` with `insId`, `ticker`, `yahoo`, sector/branch/country, `stockPriceCurrency`, `reportCurrency`.
- `GET /v1/instruments/{insId}` → single instrument details (same schema) for cache refresh.
- `GET /v1/instruments/markets`, `/countries`, `/sectors`, `/branches` → lookup tables for enrichment/mappings.
- `GET /v1/instruments/splits` and `/stockprices/last` expose support data (currency splits, last close) needed for validation and derived metrics.
Implication: we must maintain a ticker→`insId` cache and surface currency info alongside numeric data.

## Price Data
Replaces `get_prices`/`get_price_data`.
- `GET /v1/instruments/{insId}/stockprices` → historical OHLCV (`StockPriceV1`: `o`, `h`, `l`, `c`, `v`, `d`). Accepts `from`, `to`, `maxCount` (20y limit).
- `GET /v1/instruments/stockprices/last` → bulk latest close for all Nordic instruments (`StockPriceFullV1`, includes instrument id `i`).
- `GET /v1/instruments/stockprices/date?date=YYYY-MM-DD` → daily snapshot across instruments (Nordic only).
- Global variants exist (`/stockprices/global/...`) for PRO+; requires access flag check.
Notes:
- Responses use short keys (`o,h,l,c,v,d`); we must translate to existing `Price` model (open, high, low, close, volume, time) and decide timezone for `d` (UTC date string).
- `maxCount` limit (20/40) demands batching if we need >20 years of daily data.

## KPI & Derived Metrics
Targets `get_financial_metrics`, `search_line_items`, and portions of `get_market_cap`.
- `GET /v1/instruments/kpis/metadata` → `KpiMetadataV1[]` enumerating KPI IDs with English/Swedish names and formatting hints. Use this to map each `FinancialMetrics` field to a Börsdata KPI id or computed combination.
- `GET /v1/instruments/{insId}/kpis/{reportType}/summary` → compact snapshots grouped by KPI family (`reportType` in `{year, r12, quarter}`, optional `maxCount`). Useful for multi-KPI pulls without enumerating IDs manually.
- `GET /v1/instruments/{insId}/kpis/{kpiId}/{reportType}/{priceType}/history` → time series for a specific KPI and report granularity. `priceType` matches definitions in wiki (`mean`, `high`, `low`, etc.).
- `GET /v1/instruments/{insId}/kpis/{kpiId}/{calcGroup}/{calc}` → screener shortcut returning calculated KPI variants (e.g., `calcGroup=1year`, `calc=latest`).
Implementation considerations:
- Börsdata exposes KPIs individually; our wide `FinancialMetrics` model will need a mapping table translating each field to a `(kpiId, reportType, priceType/calc)` triple or deriving via reports.
- Several legacy metrics (e.g., `operating_cash_flow_ratio`, `receivables_turnover`) may require ratios computed from `Reports` endpoint data when no direct KPI exists. We need to verify coverage once we enumerate KPI metadata.

## Financial Statements / Line Items
Supports `search_line_items` and additional fundamentals.
- `GET /v1/instruments/{insId}/reports/{reportType}` → structured income/balance/cash-flow line items (`ReportV1`). Accepts `maxCount` (20 for year, 40 for r12/quarter) and `original=1` to keep native currency. This endpoint can replace bespoke line-item searches by filtering the response locally.
- `GET /v1/instruments/reports/metadata` → provides report column definitions for dynamic mapping if we need localization.
Follow-up:
- Determine if caching aggregated `ReportV1` payloads per instrument-date satisfies existing query patterns or if we require a thinner subset for performance.

## Insider & Ownership Data
Replaces `get_insider_trades` (Nordic scope; PRO+ for some ventures).
- `GET /v1/holdings/insider?instList=...` → batched insider transactions (max 50 instruments). Returns `InsiderRespV1` where `values[]` are `InsiderRowV1` elements (shares, price, amount, transaction type, verification date).
- Related endpoints (`/holdings/shorts`, `/holdings/buyback`) may become relevant if legacy functionality covers those categories.
Adaptation path:
- Need to transform `InsiderRowV1` into our `InsiderTrade` schema, including deriving ticker (`insId` → ticker) and mapping transaction codes to semantic flags (buy/sell, program participation). Pagination must be emulated client-side because API expects batched instrument IDs.

## Company News Coverage
The Swagger spec and README lack any `/news` endpoints. Börsdata currently exposes calendars (`/v1/instruments/report/calendar`, `/dividend/calendar`) and descriptions but no general news feed.
Implication:
- Legacy `get_company_news` cannot be ported directly. We must either (1) drop/replace news-driven features, (2) source news from an alternative provider, or (3) leverage report/dividend calendars as partial substitutes. This gap needs a product/UX decision before removing FinancialDatasets news support.

## Market Cap & Company Facts
- No direct market-cap endpoint. Options:
  - Combine latest price from `/stockprices/last` with `number_Of_Shares` from the most recent `ReportV1`.
  - Explore KPI metadata for market-cap related calculations (confirm via metadata fetch).
- Instrument metadata offers exchange, sector, and currency data but lacks extended `CompanyFacts` fields (e.g., employee counts). Identify which attributes are essential and plan replacements or deprecations.

## Rate Limiting & Pagination
- Global rate limit remains 100 calls / 10 seconds with `429` + `Retry-After` header.
- Many endpoints support batching (instrument arrays, summary lists) to stay within quotas; our client should exploit these to prevent throttling.
- For history endpoints with `maxCount` limits, we must iterate over date windows while respecting rate limits.

## Outstanding Questions
1. Enumerate KPI IDs that map to each `FinancialMetrics` field; flag any metrics that require custom calculations.
2. Decide on the replacement (if any) for company news coverage given the missing Börsdata endpoint.
3. Confirm access level (Nordic vs Global) required for our user base and handle `418 No Global access` gracefully.
4. Determine caching strategy for instrument metadata and bulk price snapshots to amortize rate limits.
