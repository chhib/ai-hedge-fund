---
title: "feat: Fix IBKR market data snapshot warm-up and add price diagnostics"
type: feat
status: active
date: 2026-03-24
---

# feat: Fix IBKR market data snapshot warm-up and add price diagnostics

## Overview

The system already fetches live IBKR market data before placing orders (`_apply_snapshot_prices` in `ibkr_execution.py:589`), but the snapshot returns empty for some tickers (e.g., HOVE on CPH). This causes orders to use stale Borsdata 3-day-average prices, triggering IBKR's "price exceeds 3% constraint" and "no market data" warnings.

## Problem Statement

Three issues compound:

1. **No warm-up handling**: IBKR's `/iserver/marketdata/snapshot` returns empty on the first call for any conid. It requires a "prime" call to tell iServer to start streaming internally, then a second call ~1s later to get actual data. The current code calls once and moves on.

2. **Silent failure**: When the snapshot returns no data for a ticker, `_apply_snapshot_prices()` silently keeps the stale Borsdata price. The user has no visibility into which orders used live vs stale prices.

3. **Exchange subscriptions unknown**: Some tickers may return empty because the IBKR account lacks a market data subscription for that exchange (e.g., CPH for Danish stocks). The snapshot response includes field `6509` (Market Data Availability) which indicates `R` (real-time), `D` (delayed), `Z` (frozen), etc. — but we don't check or log it.

## Proposed Solution

### Phase 1: Handle warm-up pattern (core fix)

In `ibkr_client.py:get_marketdata_snapshot()` or in `ibkr_execution.py` at the call site (line 187):

```python
# ibkr_execution.py:187 — replace single call with warm-up pattern
conids = [order.conid for order in resolved_orders]
ibkr.get_marketdata_snapshot(conids)       # Prime call (returns empty)
time.sleep(1.5)                            # Wait for iServer to start streaming
snapshot = ibkr.get_marketdata_snapshot(conids)  # Actual data call
_apply_snapshot_prices(resolved_orders, snapshot, report)
```

Also request field `6509` to detect subscription issues:
```python
# ibkr_client.py:168
def get_marketdata_snapshot(self, conids: Iterable[int], fields: str = "31,84,86,6509") -> Any:
```

### Phase 2: Price source diagnostics

Add logging/reporting to `_apply_snapshot_prices()` so each order shows its price source:

```python
# In _apply_snapshot_prices, track what happened per order:
if bid > 0 or ask > 0 or last > 0:
    report.notes.append(f"{order.intent.ticker}: Live price (bid={bid}, ask={ask}, last={last})")
else:
    availability = row.get("6509", "unknown")
    report.warnings.append(
        f"{order.intent.ticker}: No live market data (availability={availability}), "
        f"using Borsdata price {order.intent.limit_price}"
    )
```

### Phase 3: Batch conids for large universes

IBKR has a 100 market-data-lines limit. For 200+ tickers, batch the snapshot requests:

```python
BATCH_SIZE = 50  # Conservative batch size
for i in range(0, len(conids), BATCH_SIZE):
    batch = conids[i:i+BATCH_SIZE]
    ibkr.get_marketdata_snapshot(batch)  # Prime
time.sleep(1.5)
for i in range(0, len(conids), BATCH_SIZE):
    batch = conids[i:i+BATCH_SIZE]
    snapshot_batch = ibkr.get_marketdata_snapshot(batch)
    all_snapshots.extend(snapshot_batch or [])
```

## Technical Considerations

- **Warm-up adds ~1.5s latency**: This is acceptable since it runs once before all orders, not per-order.
- **Stale price fallback is intentional**: If the snapshot truly returns nothing (no subscription), using the Borsdata price is still better than skipping the order entirely. But the user should be warned.
- **The 3% constraint is from IBKR**: This is a server-side safety check. If our price is accurate (live snapshot), IBKR won't trigger it. The warning only fires when our limit price diverges from IBKR's internal last-known price.
- **Market hours matter**: Borsdata gives daily close prices. If the market opened and moved 5% since yesterday's close, the 3-day average will be even further off. The live snapshot solves this for open markets; for closed markets, the stale price is unavoidable.

## Acceptance Criteria

- [ ] Snapshot warm-up: first call primes, second call retrieves data
- [ ] Field `6509` requested and logged to diagnose subscription gaps
- [ ] Each order in the execution report shows whether it used live or stale pricing
- [ ] Orders for open-market tickers with valid subscriptions use bid/ask prices (no more "price exceeds 3%" warnings)
- [ ] Large universes (200+ tickers) are batched to respect IBKR limits
- [ ] Orders for closed-market or unsubscribed tickers fall back to Borsdata price with a clear warning

## Key Files

| File | Change |
|------|--------|
| `src/integrations/ibkr_execution.py:187` | Add warm-up call + sleep before snapshot |
| `src/integrations/ibkr_execution.py:589-618` | Add price source diagnostics to `_apply_snapshot_prices()` |
| `src/integrations/ibkr_client.py:168` | Add field `6509` to default snapshot fields |

## Dependencies & Risks

- **CPH subscription**: If the IBKR account simply doesn't have Copenhagen market data, no amount of warm-up will help. The diagnostic logging will surface this so the user can subscribe.
- **Rate limits**: 10 req/s for snapshot endpoint. Batching 200+ tickers in groups of 50 with warm-up means ~8 requests total — well within limits.
