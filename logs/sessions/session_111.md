# Sessions 111-120 (Current)

_This is the active session file. New sessions should be added here._

## Session 111 (Fix dot-format ticker lookup in BorsdataClient data fetching)
**Date**: 2026-03-24 | **Model**: Claude Opus 4.6 (1M context)

- **Fix**: `BorsdataClient.get_instrument()` now falls back to space-separated lookup when dot-separated IBKR tickers fail -- same root cause as Session 110 but in the data fetching layer instead of market detection
- **Root cause**: Session 110 fixed market routing (System 1) but the actual API data fetching (System 2) also received IBKR dot-format tickers (`BEIJ.B`) and failed to find them since Borsdata stores `BEIJ B`
- **Scope**: Single convergence point fix in `borsdata_client.py:get_instrument()` -- all callers (prices, financials, line items, instruments) go through this method
- **Verified**: `BEIJ.B`, `HEBA.B`, `LUND.B`, `INDU.A`, `NIBE.B`, `EMBRAC.B` all resolve correctly against live Borsdata API

## Session 112 (IBKR market data snapshot warm-up + price diagnostics)
**Date**: 2026-03-24 | **Model**: Claude Opus 4.6 (1M context)

- **Feature**: IBKR snapshot now uses warm-up pattern -- prime call, 1.5s sleep, then data call -- fixing empty snapshot responses that caused stale Borsdata prices to be used
- **Feature**: Added field `6509` (Market Data Availability) to snapshot requests to diagnose subscription gaps (R=realtime, D=delayed, Z=frozen)
- **Feature**: `_apply_snapshot_prices()` now logs per-order price source: live bid/ask/last vs Borsdata fallback with availability code
- **Root cause**: IBKR's `/iserver/marketdata/snapshot` returns empty on first call for any conid; requires a "prime" call first. This caused HOVE (CPH) to use stale 3-day-average price, triggering IBKR's "price exceeds 3%" and "no market data" warnings
- **Cleanup**: Removed CFLT, CMH, DORO from both universe files (not in Borsdata coverage)
- **Tests**: 27/27 IBKR execution tests passing
