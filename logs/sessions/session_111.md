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

## Session 113 (Market-aware order execution with sell-first sequencing)
**Date**: 2026-03-24 | **Model**: Claude Opus 4.6 (1M context)

- **Feature**: Orders now partitioned by market open/closed status before execution. Closed-market orders are deferred with clear skip reason (e.g., "Market closed (NYSE CLOSED)")
- **Feature**: `EXCHANGE_SESSIONS` constant covers 18 exchanges (Nordic, European, US, Canadian) with timezone-aware open/close hours
- **Feature**: `_is_market_open(exchange)` checks timezone-local hours including weekend detection
- **Feature**: Warning when buys may lack cash from sells deferred on closed markets
- **Root cause**: At 13:40 CET, sells on NYSE/TSX were silently filtered (market closed), leaving only buys which then prompted without available cash. The existing sell-before-buy sequencing worked but had no market-hours awareness
- **Decision**: Unknown exchanges and SMART routing default to "assume open" -- let IBKR reject rather than skip valid orders
- **Tests**: 27/27 IBKR execution tests passing

## Session 114 (Long-only guard: validate sells against live IBKR positions)
**Date**: 2026-03-24 | **Model**: Claude Opus 4.6 (1M context)

- **Feature**: `_validate_sells_against_positions()` fetches live IBKR positions before building orders and skips sells for tickers not held in the account
- **Feature**: Sell quantities clamped to actual holdings to prevent accidental short selling on cash accounts (ISK)
- **Root cause**: SFL sell on cash account U22372535 triggered "Short stock positions can only be held in a margin account" because IBKR didn't see the position in that account. The long-only guard now catches this early with a clear "Not held in account (long-only)" skip reason
- **Tests**: Updated FakeIBKRClient with `get_positions()` and added position data to 4 tests; 27/27 passing
