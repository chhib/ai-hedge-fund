# Sessions 71-80

_Completed. Active sessions continue in `session_081.md`._

## Session 71 (IBKR Permission Error Handling)
- **Issue**: IBKR preview flow aborted all remaining previews after a single "No trading permissions" error, skipping orders in markets where permissions exist.
- **Fix**: Treat permission errors as per-order skips during preview; continue processing remaining orders. Global/batch permission errors still abort.
- **Tests**: `poetry run pytest tests/integrations/test_ibkr_execution.py -q`

## Session 72 (IBKR Sell-First Preview Sequencing)
- **Issue**: Buy previews fail with "Available converted to base: 0" when the account is fully invested and sells are needed to free cash.
- **Fix**: Preview-only runs now defer buy previews when sell orders exist; only sell orders are previewed and buys are marked as deferred until sells execute. Orders are also sequenced sells-before-buys for execution.
- **Tests**: `poetry run pytest tests/integrations/test_ibkr_execution.py -q`

## Session 73 (IBKR Contract Rules + Permission Precheck)
- **Issue**: IBKR previews failed with tick-size errors (e.g., min price variation) and 500 "No trading permissions" errors.
- **Fix**: Switched contract rules fetch to `/iserver/contract/rules` with fallback to `info-and-rules`, parse `incrementRules`/`increment` to select tick size based on price, and round with Decimal for precision. Added `canTradeAcctIds` precheck to skip orders lacking permissions before preview.
- **Tests**: `poetry run pytest tests/integrations/test_ibkr_execution.py -q`

## Session 74 (IBKR Universe Generator + LUND B Override)
- **Mapping Update**: Added IBKR contract override for LUND B (conid 1329566, SFB, SEK) in `data/ibkr_contract_mappings.json` to resolve the correct listing.
- **IBKR Universe File**: Added `scripts/build_ibkr_universe.py` to generate a separate IBKR universe file from the Börsdata universe, and generated `portfolios/ibkr_universe.txt`.
- **Usage**: `PYTHONPATH=. python3 scripts/build_ibkr_universe.py --input portfolios/borsdata_universe.txt --output portfolios/ibkr_universe.txt`

## Session 75 (IBKR Contract Override Builder)
- **Tooling**: Added `scripts/build_ibkr_contract_overrides.py` to auto-populate `data/ibkr_contract_mappings.json` by querying IBKR contract lookup endpoints for each Borsdata universe ticker, with ambiguous candidates written to `data/ibkr_contract_candidates.json`.
- **Heuristics**: Prefers exact symbol/localSymbol matches, then Nordic exchange hints, otherwise flags for manual review.
- **Usage**: `PYTHONPATH=. python3 scripts/build_ibkr_contract_overrides.py --input portfolios/borsdata_universe.txt --output data/ibkr_contract_mappings.json`

## Session 76 (IBKR Overrides for Current Holdings)
- **Overrides**: Added contract overrides for current holdings (HOVE, RANA, SBOK, DHT, SFL, STNG, TK, WB) using IBKR lookup results; updated SFL to SFB listing.
- **Next Batch**: Queried candidates for NVEC and MPCC; awaiting selection to add.

## Session 77 (IBKR Overrides: NVEC + MPCC Names)
- **Overrides**: Added NVEC (conid 17004501, NASDAQ, USD) and MPCC (conid 307129507, OSE, NOK) using IBKR search results with company names.
- **Clarification**: Future IBKR candidate reviews will include `companyName` from `/iserver/secdef/search` when available.

## Session 78 (IBKR Auth Retry Window)
- **Issue**: `hedge rebalance` aborted even right after login because gateway auth status lagged.
- **Fix**: Added a short retry window (5×2s) before failing when gateway is running but not yet authenticated.

## Session 79 (IBKR Submission Reply Loop)
- **Issue**: Orders with IBKR confirmation prompts could stall because we only sent a single reply and never captured the final submission response.
- **Fix**: Added a reply loop for order submissions (handles multi-step confirmations), captures final submission responses, and surfaces submitted order summaries in the CLI.
- **Tests**: `poetry run pytest tests/integrations/test_ibkr_execution.py -q`

## Session 80 (IBKR Account "All" Guard)
- **Issue**: IBKR gateway sometimes returns `selectedAccount=All`, causing portfolio/ledger requests to fail with "All not supported".
- **Fix**: Ignore "All" account ids when resolving accounts and prefer the first real account id.
- **Tests**: `poetry run pytest tests/integrations/test_ibkr_client.py -q`
