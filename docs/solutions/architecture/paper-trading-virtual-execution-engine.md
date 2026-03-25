---
title: "Paper Trading -- Virtual Execution Engine for Pod-Based Trading System"
category: architecture
date: 2026-03-25
tags: [paper-trading, virtual-execution, pod-architecture, forward-testing, portfolio-management, execution-pipeline, decision-db]
module: src/services/paper_engine.py
related_modules: [src/services/paper_metrics.py, src/data/decision_store.py, src/config/pod_config.py, src/services/portfolio_runner.py, src/cli/hedge.py]
severity: high
detection_method: "Architectural gap identified during trading pod shop buildout -- pods lacked intermediate validation tier between backtesting and live IBKR execution"
---

# Paper Trading -- Virtual Execution Engine

## Problem

AI hedge fund pods had no intermediate proving ground between backtesting and live IBKR execution. Strategies could only be validated against historical data (backtest) or real capital (live). There was no way to forward-test against real market data without risking money. This was identified as the riskiest gap in the system during the Trading Pod Shop ideation (#4 in the implementation sequence).

## Root Cause

The pipeline supported exactly two execution modes: backtest (historical replay) and live (IBKR gateway). No virtual forward-looking execution tier existed. The Pod dataclass had no concept of execution tier, and `run_pods()` assumed all pods route to IBKR after merging proposals.

## Solution

Six implementation units delivered across three phases:

### Phase 1: Configuration & Schema

**Pod Tier Config** -- Extended the `Pod` dataclass (`src/config/pod_config.py`) and `config/pods.yaml` with `tier: paper|live` and `starting_capital` fields. Default tier is `paper`. CLI `--tier` flag overrides per-run. This gates execution routing at the pod level.

**Decision DB Extension** -- Added two append-only tables to `src/data/decision_store.py`:
- `paper_positions`: per-pod virtual holdings (ticker, shares, cost_basis, current_price)
- `paper_snapshots`: portfolio value time series (total_value, cash, positions_value, cumulative_return_pct)
- Added `runs.pod_id` index for efficient JOINs in `get_paper_execution_outcomes()`
- Consolidated `get_latest_paper_positions()` to a single subselect query (avoiding two-query pattern)

### Phase 2: Execution Engine

**PaperExecutionEngine** (`src/services/paper_engine.py`) -- Standalone module responsible for the full virtual trade lifecycle:
- Loads virtual portfolio from Decision DB or cold-starts with `starting_capital`
- Validates sells against virtual holdings (long-only guard mirroring IBKR's `_validate_sells_against_positions()`)
- Fills at the recommendation's `limit_price` (last known price at run time)
- Processes sells before buys to free cash first
- Uses weighted average cost basis on position increases
- Records fills as `execution_outcomes` with `execution_type='paper'`
- `_build_snapshot()` helper centralizes return calculation (extracted during code review to eliminate duplication)

**Mark-to-Market** -- Before processing new trades, updates all open position values with current Borsdata prices. A `record=False` flag prevents double-writing snapshots when trades follow immediately.

### Phase 3: Integration & Observability

**Pipeline Fork** -- `run_pods()` in `src/services/portfolio_runner.py` splits pods by tier after proposals are generated. Paper pods execute independently through PaperExecutionEngine; live pods merge and route to IBKR. All-paper runs skip IBKR entirely (no gateway required).

**Performance Dashboard** -- `src/services/paper_metrics.py` computes Sharpe ratio, Sortino ratio, max drawdown (reusing the backtester's `PerformanceMetricsCalculator`), plus win rate and average trade P&L from realized trades. `hedge pods status` surfaces the full metrics table with columns for Value, Cash, Return %, Sharpe, Max DD, Win %, Avg P&L, and Trades.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Fill price = limit_price | Simplicity and determinism over realism. Paper trading validates strategy direction, not execution modeling. |
| Per-pod isolation (not merged virtual portfolio) | Mirrors real pod shop where each pod manages its own book. A fund-level view can be derived later. |
| Decision DB as single store | Consistent with "single source of truth" philosophy. `execution_type='paper'` discriminator keeps paper/live data distinguishable. |
| Win rate = realized only | Only closed (sold) trades count. Unrealized P&L shown separately. N/A when no trades closed. |
| Tier switch keeps shadow paper book after promotion | Governor Pod Lifecycle automation needs a continuous per-pod equity curve even after a pod is promoted to live. Promoted pods still participate in merged live execution, but their isolated shadow book continues so drawdown and Sharpe-based demotion remain measurable. |
| `record=False` on M2M | Avoids double-write when trades follow. Without this, each pod run writes 2 sets of positions and 2 snapshots. |

## Prevention Strategies

1. **Double-write guard**: Always pass `record=False` to `mark_to_market()` when `execute_paper_trades()` will follow. The trade execution writes the final state. If you add a new code path that calls M2M without subsequent trades, use `record=True` (the default).

2. **Snapshot computation single-source**: All return calculations MUST go through `_build_snapshot()`. Search for the formula `total_value - self.starting_capital` before any PR merge to verify no duplicates have been introduced.

3. **Long-only guard sync**: Paper engine mirrors IBKR's `_validate_sells_against_positions()`. If the IBKR guard changes, the paper guard must be updated too. Both should eventually share a common validation function.

4. **Price fallback auditing**: M2M falls back to `cost_basis` when no current price is available, logging a WARNING. Monitor for excessive fallbacks, which indicate stale data silently masking real P&L.

5. **Append-only growth budget**: 18 pods x 365 days x ~5 positions = ~33k position rows/year. With the double-write fix, this is manageable for years. If the system scales to 50+ pods or sub-daily runs, implement a pruning/archival strategy.

6. **Manager state transplant**: The paper path creates `EnhancedPortfolioManager` and transplants `prefetched_data` and `exchange_rates`. If new internal state is added to the manager, the transplant in `portfolio_runner.py` must be updated. A future `PriceService` extraction would eliminate this fragile coupling.

7. **Shadow-book continuity is intentional**: Do not reintroduce the old "freeze paper portfolio on promotion" assumption. Lifecycle automation depends on a continuous pod-level shadow history after promotion because live execution is merged at the fund level and cannot support pod-specific drawdown demotion on its own.

## Developer Checklist

- [ ] Understand the cycle: load portfolio -> M2M (`record=False`) -> generate recommendations -> execute trades -> record snapshot
- [ ] Search for `_build_snapshot` before adding return calculations
- [ ] Update both engines if modifying sell validation logic
- [ ] Test with multiple pods (cross-pod state leakage only surfaces with 2+)
- [ ] Verify exactly one snapshot per pod per cycle in Decision DB
- [ ] If adding fields to `EnhancedPortfolioManager`, update the transplant block in `portfolio_runner.py`

## Cross-References

- **Origin vision**: `docs/ideation/2026-03-24-trading-pod-shop-ideation.md` (7 ranked ideas, dependency chain)
- **Prior compound learning**: `docs/solutions/architecture/monolith-decomposition-pod-abstraction.md` (EPM decomposition + pod abstraction)
- **Requirements**: `docs/brainstorms/2026-03-24-paper-trading-requirements.md` (R1-R8)
- **Plan**: `docs/plans/2026-03-25-001-feat-paper-trading-virtual-execution-plan.md`
- **PRs**: #6 (Decision DB), #7 (EPM decomposition), #8 (Pod abstraction), #9 (Paper trading)
- **Session**: `logs/sessions/session_111.md` Session 119
