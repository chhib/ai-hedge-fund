# Börsdata Integration Plan

This document lays out the concrete steps to migrate the application from the legacy FinancialDatasets provider to Börsdata, aligning with the project log and endpoint inventory.

## 1. Client Architecture
- Introduce `src/data/borsdata_client.py` encapsulating HTTP access, auth, rate limiting, and pagination.
- Split feature wrappers into focused modules:
  - `borsdata_prices.py`: historical + snapshot price utilities.
  - `borsdata_kpis.py`: FinancialMetrics assembly powered by the mapping in `src/data/borsdata_metrics_mapping.py`.
  - `borsdata_reports.py`: generic accessors for income/balance/cash-flow statements for derived metrics.
  - `borsdata_holdings.py`: insider/short/buyback helpers.
- Refactor `src/tools/api.py` to delegate to the new client, keeping the public function signatures stable for agents and backtesting code.

## 2. Authentication & Configuration
- Load `BORSDATA_API_KEY` from `.env` (using `python-dotenv` hook already present in the project) and pass it as the `authKey` query parameter.
- Remove `FINANCIAL_DATASETS_API_KEY` references once all consumers are ported.
- Allow explicit API key override parameters on public functions (mirroring current behaviour) for testing hooks.

## 3. Rate Limiting & Caching
- Implement a token-bucket limiter (100 calls / 10s) inside the shared client; respect `Retry-After` headers for safety.
- Leverage batch endpoints (`/stockprices/last`, KPI summary arrays, holdings batches) to minimise call volume.
- Reuse the existing cache abstraction in `src/data/cache.py`; adjust cache keys to incorporate Börsdata-specific parameters (instrument id, report type, calc group).
- Record limiter stats in debug logs so integration tests can assert throttling behaviour.

## 4. Data Model Alignment
- Extend `FinancialMetrics` assembly to:
  - Resolve instrument tickers → `insId` once per request batch and include `reportCurrency`.
  - Populate KPI-backed fields via the mapping table; fall back to report-derived calculations for gaps (market cap, operating cash flow ratio, operating cycle).
  - Normalise screener growth percentages to match current expectations (decimal vs percentage).
- Update price models to translate Börsdata keys (`o/h/l/c/v/d`) into the existing `Price` schema with ISO date handling.
- Replace company facts lookups using instrument metadata + description endpoints; document missing attributes that Börsdata does not expose.

## 5. Testing Strategy
- Maintain Börsdata-specific fixtures under `tests/fixtures/api/` (prices, financial metrics, calendar, insider trades) so integration tests and harnesses can replay API responses offline.
- Add unit tests for:
  - KPI mapping resolution (metadata lookup + screener fallbacks).
  - Rate limiter behaviour (burst > 100 calls triggers wait/backoff).
  - Derived metric calculations (market cap, operating cash flow ratio).
- Update integration tests to exercise agents/backtester flows using mocked Börsdata responses instead of FinancialDatasets.

## 6. Migration Steps
1. Implement instrumentation utilities (instrument cache, limiter) and replace price retrieval.
2. Port FinancialMetrics using the mapping reference; maintain parity with prior API responses.
3. Swap line item searches to the reports endpoint with local filtering.
4. Transition insider trades to `/v1/holdings/insider` and adapt pagination.
5. Remove legacy FinancialDatasets dependencies, environment variables, and tests.
6. Update documentation (`README`, `PROJECT_LOG.md`) once the migration is functional.

## 7. News Replacement Strategy
The Börsdata API does not provide a general-purpose news feed. To keep the product aligned with Börsdata-only data while preserving user value:

- **Adopt**: replace the existing news feature with Börsdata's report and dividend calendars (`/v1/instruments/report/calendar`, `/v1/instruments/dividend/calendar`). Present upcoming and recent corporate events in place of narrative articles.
- **Enhance**: extend the UI/backend to label the feed as "Corporate Events" and include links to downloaded reports where available.
- **Defer external feeds**: document a future enhancement path to integrate a dedicated news provider (e.g., Finnhub, FinancialModelingPrep) if stakeholders decide narrative news is mandatory; this requires separate API keys and legal review.
- **Communicate**: surface the change in release notes and adjust any agent/backtester prompts that referenced "news" to avoid stale expectations.

This strategy avoids introducing new third-party dependencies, keeps the migration focused on Börsdata data, and provides users with timely company information sourced from endpoints that are already available in the API stack.
