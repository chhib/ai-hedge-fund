---
title: "fix: Exclude untradeable Swedish ISK positions from portfolio"
type: fix
status: active
date: 2026-03-24
---

# fix: Exclude untradeable Swedish ISK positions from portfolio

## Overview

LUMI and LUG are held in ISK account U22372535 but have "No trading permissions" — they can't be bought or sold from this account. The system keeps trying to sell them every rebalance cycle, hitting IBKR errors. We should exclude them from the portfolio so the system treats them as if they don't exist.

## Problem

- LUMI (Lundin Mining) and LUG (Lundin Gold) are on SFB (Stockholm)
- ISK account U22372535 has no trading permissions for these
- Transfer to regular account U22372536 has been attempted but Client Portal doesn't offer it as a self-service destination (Sessions 107-108)
- Every rebalance cycle wastes API calls and user confirmations on these
- The portfolio manager incorrectly counts their value as available capital

## Proposed Solution

Add a hardcoded exclude list in `ibkr_client.py:_transform_positions()` that filters out these tickers before they enter the portfolio. This is the simplest, most visible approach.

```python
# Tickers stuck in ISK account with no trading permissions.
# These positions exist but cannot be bought or sold.
# See sessions 107-108 for transfer attempts.
EXCLUDED_ISK_POSITIONS = {"LUMI", "LUG"}
```

Filter in `_transform_positions()` before creating Position objects.

## Acceptance Criteria

- [ ] LUMI and LUG not included in portfolio when loaded from IBKR
- [ ] Warning logged when positions are excluded so user knows
- [ ] Portfolio value calculation does not include excluded positions
- [ ] Existing tests pass
