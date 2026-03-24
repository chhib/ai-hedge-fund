# Sessions 111-120 (Current)

_This is the active session file. New sessions should be added here._

## Session 111 (Fix dot-format ticker lookup in BorsdataClient data fetching)
**Date**: 2026-03-24 | **Model**: Claude Opus 4.6 (1M context)

- **Fix**: `BorsdataClient.get_instrument()` now falls back to space-separated lookup when dot-separated IBKR tickers fail -- same root cause as Session 110 but in the data fetching layer instead of market detection
- **Root cause**: Session 110 fixed market routing (System 1) but the actual API data fetching (System 2) also received IBKR dot-format tickers (`BEIJ.B`) and failed to find them since Borsdata stores `BEIJ B`
- **Scope**: Single convergence point fix in `borsdata_client.py:get_instrument()` -- all callers (prices, financials, line items, instruments) go through this method
- **Verified**: `BEIJ.B`, `HEBA.B`, `LUND.B`, `INDU.A`, `NIBE.B`, `EMBRAC.B` all resolve correctly against live Borsdata API
