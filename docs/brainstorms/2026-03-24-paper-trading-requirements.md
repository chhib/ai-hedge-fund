---
date: 2026-03-24
topic: paper-trading
---

# Paper Trading -- Virtual Execution with Forward P&L Tracking

## Problem Frame

The AI hedge fund currently jumps from historical backtesting directly to live IBKR execution with real capital. There is no intermediate proving ground where pods can run forward-looking strategies against real market data without risking money. This is the riskiest gap in the system -- a pod that looks good in backtests may behave differently in live market conditions due to regime changes, data timing, or strategy drift.

Paper trading creates a virtual execution tier where pods generate the same trade recommendations as live pods but fills are recorded virtually against real prices. Each pod builds a track record that can be evaluated before manual promotion to live trading.

This is item #4 from the [Trading Pod Shop ideation](../ideation/2026-03-24-trading-pod-shop-ideation.md), following the shipped Decision DB (#1), Monolith Decomposition (#2), and Pod Abstraction (#3).

## Requirements

- R1. **Paper execution engine**: Consume the same recommendation list that IBKR execution receives. Produce virtual fills using the last known price at run time (the `limit_price` from trade recommendations). No IBKR gateway needed for paper fills.
- R2. **Per-pod virtual portfolio**: Each paper pod maintains its own independent virtual portfolio -- cash balance, positions, and P&L. Portfolios are isolated; one pod's trades do not affect another's.
- R3. **Starting capital**: Global default starting capital (e.g., 100,000 SEK) for all paper pods, with per-pod override via `starting_capital` field in `pods.yaml`.
- R4. **Mark-to-market on every run**: Before processing new recommendations, update all open position values with current prices. P&L snapshots are recorded each run. No separate mark-to-market job required.
- R5. **Pod execution tier**: Each pod has a `tier` field in `pods.yaml` (values: `paper` or `live`, default: `paper`). CLI flags can override per-run. Paper pods get virtual fills; live pods follow the existing IBKR path.
- R6. **Decision DB integration**: Paper fills recorded in `execution_outcomes` with `execution_type = 'paper'`. Virtual portfolio state (positions, cash, P&L snapshots) stored in new Decision DB tables. Full provenance chain preserved: signals -> aggregation -> recommendations -> paper fills.
- R7. **Performance dashboard**: `hedge pods status` shows full performance metrics for paper pods: current positions, cash balance, total portfolio value, cumulative return %, Sharpe ratio, max drawdown, win rate, and average trade P&L.
- R8. **Long-only guard**: Paper pods respect long-only constraints -- skip sells for positions not held, clamp sell quantity to actual virtual holdings. Mirror IBKR execution's `_validate_sells_against_positions()` logic.

## Success Criteria

- A paper pod can run end-to-end: generate signals, propose portfolio, fill virtually, update positions, record to Decision DB
- Multiple paper pods run independently with fully isolated portfolios
- `hedge pods status` displays meaningful performance metrics after several runs
- Paper fills appear in Decision DB with complete provenance (queryable via `get_decision_chain`)
- Switching a pod from paper to live requires only changing `tier` in pods.yaml (or CLI flag)
- No IBKR gateway needed for paper pod execution

## Scope Boundaries

- **No promotion automation**: Automatic promotion/demotion based on performance thresholds is deferred to #6 (Governor Pod Lifecycle). Paper pods are manually promoted by changing `tier` in config.
- **No dividend/FX/splits handling**: P&L is simplified -- price appreciation and cash from fills only. Corporate actions are out of scope.
- **No real-time streaming**: Mark-to-market happens only during pod runs, not continuously.
- **No web UI**: Paper trading dashboard in the web app is deferred to #7 (Web UI Pod Dashboard).
- **No slippage modeling**: Paper fills execute at last known price with no spread or slippage simulation.

## Key Decisions

- **Fill price = last known price at run time**: Uses the `limit_price` already computed on trade recommendations. No extra data fetch, no intraday noise. Simpler and more deterministic than simulating bid/ask spreads.
- **Per-pod isolation over merged portfolio**: Each paper pod is its own independent book rather than merging into a shared virtual portfolio. Mirrors real pod shop structure where each pod manager has their own P&L. A merged fund-level view can be derived later if needed.
- **Decision DB as single store**: Paper portfolio state lives alongside all other decision data. No separate DB file. Consistent with the "single source of truth" principle established by Decision DB.
- **Mark-to-market on run, not on schedule**: Simplest approach -- avoids a new scheduling concern. P&L freshness matches the pod's run cadence.
- **Reuse backtester's PerformanceMetricsCalculator**: The backtesting engine already computes Sharpe, Sortino, max drawdown. Paper trading's performance dashboard should reuse this rather than reimplementing.

## Dependencies / Assumptions

- Decision DB (#1) and Pod Abstraction (#3) are shipped and stable
- Borsdata close prices are available for all tickers in pod universes
- The `limit_price` on trade recommendations is a reasonable fill price proxy
- `PerformanceMetricsCalculator` from the backtester can be extracted or called from outside the backtesting engine

## Outstanding Questions

### Deferred to Planning

- [Affects R5][Technical] Exact CLI flag design for tier override (`--paper`, `--live`, `--tier paper`, etc.)
- [Affects R6][Technical] Schema design for virtual portfolio tables (positions, P&L snapshots) in Decision DB
- [Affects R7][Needs research] Whether `PerformanceMetricsCalculator` can be reused directly or needs adaptation for forward-looking P&L (it currently expects a time series of portfolio values)
- [Affects R3][Technical] Default starting capital amount and currency handling for multi-market pods
- [Affects R4][Technical] How to fetch current prices for mark-to-market -- reuse Borsdata parallel fetcher or read from cache

## Next Steps

-> `/ce:plan` for structured implementation planning
