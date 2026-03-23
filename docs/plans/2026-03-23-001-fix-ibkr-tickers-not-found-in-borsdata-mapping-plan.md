---
title: "fix: IBKR dot-format tickers not found in Borsdata market mapping"
type: fix
status: active
date: 2026-03-23
---

# fix: IBKR dot-format tickers not found in Borsdata market mapping

## Overview

When running `hedge rebalance --universe portfolios/ibkr_universe.txt`, 30 tickers produce a "not in the Borsdata mapping" warning. 26 of these **do exist in Borsdata** but use a different format. The remaining 4 are genuinely missing from Borsdata's API.

## Problem Statement

There are two distinct issues producing the warning:

### Issue 1: Dot-to-space format mismatch (26 tickers)

The IBKR universe file uses dot-separated share classes (`EMBRAC.B`, `HM.B`, `SHB.B`) while the Borsdata ticker mapping cache stores them with spaces (`EMBRAC B`, `HM B`, `SHB B`). The market detection function `get_ticker_market()` does a direct `ticker.upper()` lookup without converting dots to spaces, so it returns `None` for every Nordic B/A-share in IBKR format.

**Evidence from cache:**
```
EMBRAC B        -> Nordic      (exists)
EMBRAC.B        -> NOT FOUND   (lookup fails)
```

Affected tickers: CLIME.B, KLARA.B, INDU.A, SHB.B, NIBE.B, TITA.B, HM.B, SOLAR.B, INISS.B, K2A.B, CRNO.B, STOR.B, BAHN.B, BEIJ.B, EMBRAC.B, MTG.B, BERNER.B, HEBA.B, LUND.B, VSSAB.B, ENGCON.B, RECY.B, TRMD.A, TCC.A, PLAZ.B, AMH2.B

### Issue 2: Tickers genuinely not in Borsdata API (4 tickers)

These are in the universe file but not in Borsdata's instrument database at all:

| Ticker | Company | Note |
|--------|---------|------|
| CFLT | Confluent Inc | US tech stock, not in Borsdata coverage |
| CLA | (Nordic) | Borsdata has `CLA B` but not bare `CLA` — universe file may have wrong ticker |
| CMH | Chordate Medical | Small Nordic stock, may not be in Borsdata coverage |
| DORO | Doro | Nordic stock, may have been delisted or renamed in Borsdata |

## Proposed Solution

### Fix 1: Add dot-to-space fallback in `get_market()` (primary fix)

In `src/data/borsdata_ticker_mapping.py`, modify `TickerMapping.get_market()` to try the space-separated variant when a dot-separated ticker is not found:

```python
# src/data/borsdata_ticker_mapping.py:166
def get_market(self, ticker: str) -> Optional[str]:
    if not self._loaded:
        self.ensure_loaded()

    upper = ticker.upper()
    result = self._mapping.get(upper)
    if result is None and "." in upper:
        # IBKR uses dots for share classes (LUND.B), Borsdata uses spaces (LUND B)
        result = self._mapping.get(upper.replace(".", " "))
    return result
```

This is a 3-line change. No other files need modification — all callers go through `get_market()` or the convenience wrapper `get_ticker_market()`.

### Fix 2: Investigate/fix the 4 genuinely missing tickers

- **CLA**: Check if this should be `CLA B` in `borsdata_universe.txt` (Borsdata has `CLA B` → Nordic)
- **CFLT, CMH, DORO**: Verify against the Borsdata API whether these are genuinely not covered. If confirmed missing, consider marking them as known gaps (like `PARANS` in `borsdata_unmatched.txt`).

## Acceptance Criteria

- [ ] `get_market("EMBRAC.B")` returns `"Nordic"` (not `None`)
- [ ] `get_market("EMBRAC B")` still returns `"Nordic"` (no regression)
- [ ] `get_market("AAPL")` still returns `"global"` (no regression)
- [ ] Running `hedge rebalance --universe portfolios/ibkr_universe.txt` shows at most 4 unknown tickers (the genuinely missing ones), not 30
- [ ] `CLA` entry in `borsdata_universe.txt` corrected if applicable

## Context

The warning is non-fatal (unknown tickers fall back to `"global"` market routing), but it:
1. Misroutes 26 Nordic tickers to the global API path, potentially fetching wrong/empty data
2. Produces noisy output that obscures genuinely missing tickers
3. Undermines user trust in the mapping system

The root gap is that System 1 (market detection in `borsdata_ticker_mapping.py`) and System 2 (IBKR↔Borsdata conversion in `ticker_mapper.py`) don't share normalization logic. The proposed fix adds the minimum normalization needed without coupling the two systems.
