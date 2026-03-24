---
title: "feat: Market-aware order execution with sell-first sequencing"
type: feat
status: active
date: 2026-03-24
---

# feat: Market-aware order execution with sell-first sequencing

## Overview

The IBKR execution pipeline has sell-before-buy sequencing logic (lines 225-242), but it doesn't account for market hours. When sells are on closed markets (US/Canada) and buys are on open markets (Nordics), the sells get filtered out during contract resolution/preview, leaving only buys — which then fail because there's no cash from the unfunded sells.

## Problem Statement

From the 2026-03-24 rebalance run at 13:40 CET:

| Order | Side | Exchange | Market Status at 13:40 CET | What happened |
|-------|------|----------|---------------------------|---------------|
| SFL | SELL | NYSE | Closed (opens 15:30) | Likely filtered/failed |
| LUG | SELL | TSX | Closed (opens 15:30) | Likely filtered/failed |
| LUMI | SELL | SFB | Open but `--ibkr-skip-swedish-stocks` blocks | Skipped (buy-only skip, but may have other issues) |
| RANA | BUY | OSE | Open | Prompted first (no cash!) |
| MAU | BUY | XETRA | Open | Would have insufficient cash |
| SEA1 | BUY | OSE | Open | Would have insufficient cash |

Result: BUY RANA presented as first order because all sells were eliminated. User has 1,041 DKK cash but needs ~5,300 SEK of buys.

## Proposed Solution

### Phase 1: Market-hours-aware execution grouping

Group orders into execution waves by market session:

```
Wave 1: Orders on OPEN markets (execute now)
  - Nordic sells first, then Nordic buys
Wave 2: Orders on CLOSED markets (defer)
  - US/Canada sells and buys — report as "deferred until market opens"
```

**Market hours reference (all CET):**

| Market | Exchange Codes | Open | Close |
|--------|---------------|------|-------|
| Nordic | SFB, CPH, OSE, HEL | 09:00 | 17:30 |
| Europe | XETRA, LSE, AEB | 09:00-17:30 (varies) |
| US | NASDAQ, NYSE, AMEX, ARCA | 15:30 | 22:00 |
| Canada | TSX, TSXV | 15:30 | 22:00 |
| Japan | TSE | 02:00 | 08:00 |

Implementation in `ibkr_execution.py`:

```python
# src/integrations/ibkr_execution.py

from datetime import datetime
from zoneinfo import ZoneInfo

EXCHANGE_SESSIONS = {
    # (timezone, open_hour, open_min, close_hour, close_min)
    "SFB": ("Europe/Stockholm", 9, 0, 17, 30),
    "CPH": ("Europe/Copenhagen", 9, 0, 17, 30),
    "OSE": ("Europe/Oslo", 9, 0, 16, 30),
    "HEL": ("Europe/Helsinki", 10, 0, 18, 30),
    "XETRA": ("Europe/Berlin", 9, 0, 17, 30),
    "FWB": ("Europe/Berlin", 8, 0, 22, 0),
    "FWB2": ("Europe/Berlin", 8, 0, 22, 0),
    "LSE": ("Europe/London", 8, 0, 16, 30),
    "AEB": ("Europe/Amsterdam", 9, 0, 17, 30),
    "NASDAQ": ("America/New_York", 9, 30, 16, 0),
    "NYSE": ("America/New_York", 9, 30, 16, 0),
    "AMEX": ("America/New_York", 9, 30, 16, 0),
    "ARCA": ("America/New_York", 9, 30, 16, 0),
    "TSX": ("America/Toronto", 9, 30, 16, 0),
    "TSXV": ("America/Toronto", 9, 30, 16, 0),
}

def _is_market_open(exchange: str, now: datetime = None) -> bool:
    session = EXCHANGE_SESSIONS.get(exchange.upper().split(".")[0])
    if session is None:
        return True  # Unknown exchange — assume open, let IBKR reject
    tz_name, oh, om, ch, cm = session
    tz = ZoneInfo(tz_name)
    local_now = (now or datetime.now(tz)).astimezone(tz)
    if local_now.weekday() >= 5:  # Saturday/Sunday
        return False
    open_time = local_now.replace(hour=oh, minute=om, second=0, microsecond=0)
    close_time = local_now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return open_time <= local_now <= close_time
```

### Phase 2: Sell-first with cash dependency awareness

Modify the execution loop to:

1. **Partition into open-market and closed-market orders**
2. **Within open-market orders: sells first, then buys** (existing logic)
3. **If sells are on closed markets but buys need the cash: block buys too**

```python
# After building resolved_orders, before sequencing:
open_sells = [o for o in sells if _is_market_open(o.exchange or "SMART")]
open_buys = [o for o in buys if _is_market_open(o.exchange or "SMART")]
deferred_sells = [o for o in sells if not _is_market_open(o.exchange or "SMART")]
deferred_buys = [o for o in buys if not _is_market_open(o.exchange or "SMART")]

# Estimate if open sells + existing cash cover open buys
sell_proceeds_est = sum(o.intent.limit_price * o.intent.quantity for o in open_sells)
buy_cost_est = sum(o.intent.limit_price * o.intent.quantity for o in open_buys)

if buy_cost_est > sell_proceeds_est + available_cash:
    # Some buys depend on deferred sell proceeds — warn user
    report.warnings.append(
        f"Buy orders ({buy_cost_est:.0f}) exceed open-market sell proceeds "
        f"({sell_proceeds_est:.0f}) + cash ({available_cash:.0f}). "
        f"Deferred sells on closed markets: {[o.intent.ticker for o in deferred_sells]}"
    )
```

### Phase 3: Execution report shows market status

Add a column to the order summary showing market status:

```
SELL  19 SFL    @ 10.30 USD  [NYSE - CLOSED, deferred]
SELL   2 LUG   @ 93.34 CAD  [TSX - CLOSED, deferred]
SELL  11 LUMI  @ 198.35 SEK [SFB - OPEN]
BUY  22 RANA   @ 78.50 NOK  [OSE - OPEN, after sells]
BUY  14 MAU    @ 11.22 EUR  [XETRA - OPEN, after sells]
```

## Acceptance Criteria

- [ ] Orders on closed markets are deferred with clear "market closed" message
- [ ] Open-market sells execute before open-market buys
- [ ] If buys depend on cash from deferred sells, buys are blocked with explanation
- [ ] Execution report shows market open/closed status per order
- [ ] Weekend detection (no orders on Saturday/Sunday)
- [ ] Unknown exchanges default to "assume open" (let IBKR reject)
- [ ] Existing tests (27/27) continue to pass

## Key Files

| File | Change |
|------|--------|
| `src/integrations/ibkr_execution.py:142-285` | Add market-hours check, partition orders into open/deferred |
| `src/integrations/ibkr_execution.py` (new) | `_is_market_open()`, `EXCHANGE_SESSIONS` constant |
| `tests/integrations/test_ibkr_execution.py` | Tests for market-hours logic, sell-before-buy with mixed markets |

## Edge Cases

1. **All sells on closed markets, all buys on open markets**: Block all buys with "waiting for sell proceeds"
2. **Enough cash for some buys but not all**: Execute sells, then buys up to available cash, defer remaining
3. **SMART routing**: If exchange is "SMART" (IBKR auto-routes), check the `listing_exchange` field instead
4. **Pre-market/after-hours**: Some US stocks trade extended hours — for now, only consider regular hours
5. **Multi-currency cash**: Sell proceeds in USD don't directly fund NOK buys — FX conversion has a delay. For now, estimate in home currency using exchange rates already available in the portfolio
