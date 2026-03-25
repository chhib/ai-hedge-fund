---
date: 2026-03-25
topic: governor-pod-lifecycle
---

# Governor Pod Lifecycle -- Automatic Promotion and Demotion

## Problem Frame

The pod shop has 18 pods running on the daemon with paper trading, but tier assignment (paper vs live) is static YAML config. Promoting a pod to live requires manually editing `pods.yaml` and restarting the daemon. With 18 pods generating daily performance data, the operator must eyeball `hedge pods status`, mentally evaluate Sharpe/drawdown/win rate, decide which pods earned live status, edit YAML, and restart. This manual process doesn't scale and defeats the purpose of an always-on daemon.

The governor already evaluates market conditions and analyst quality for each run. Extending it to evaluate pods for tier promotion/demotion closes the loop: pods prove themselves on paper, earn live status automatically, and get demoted back to paper if they breach risk limits.

## Requirements

- R1. **Weekly promotion evaluation**: Every Monday, the daemon evaluates all paper pods against promotion gates. Pods that pass all gates are automatically promoted to live tier.
- R2. **Promotion gates**: A paper pod must meet ALL of the following to be promoted:
  - Minimum 30 days of paper trading history (sufficient snapshots for evaluation)
  - Annualized Sharpe ratio > 0.5 over the observation window
  - Positive cumulative return
  - Max drawdown from high-water mark < 10%
- R3. **Continuous drawdown monitoring**: On every daemon mark-to-market (every run), check each live pod's drawdown from its high-water mark. If drawdown exceeds 10%, immediately demote to paper -- do not wait for the weekly evaluation.
- R4. **Demotion on weekly evaluation**: During the Monday evaluation, live pods that no longer meet the maintenance thresholds (Sharpe > 0.0, drawdown < 10%) are demoted back to paper.
- R5. **Decision DB lifecycle events**: All promotion, demotion, and drawdown-stop events are recorded in Decision DB with the pod_id, old_tier, new_tier, reason, and metrics snapshot at the time of decision.
- R6. **Manual override via CLI**: `hedge pods promote <pod_name>` and `hedge pods demote <pod_name>` commands to manually change a pod's tier, bypassing automated gates. Overrides persist until the next automated evaluation cycle.
- R7. **Lifecycle status in hedge pods status**: The `hedge pods status` dashboard shows the current tier, days in tier, next evaluation date, and the most recent lifecycle event (e.g., "promoted 2026-03-20", "demoted: drawdown -11.2%").
- R8. **Configurable thresholds**: Promotion gates and drawdown limits are configurable in `config/pods.yaml` (or a dedicated lifecycle config section) with sensible defaults. The daemon reads them at startup.
- R9. **Daemon integration**: The weekly evaluation runs as a scheduled APScheduler job in the daemon (Monday mornings). The continuous drawdown check runs as part of each Phase 2 mark-to-market. No separate process.
- R10. **Tier transition is atomic**: When a pod is promoted or demoted, the tier change takes effect for the next daemon run. In-progress runs complete at the original tier.

## Success Criteria

- Paper pods that consistently generate positive risk-adjusted returns (Sharpe > 0.5) for 30+ days are automatically promoted to live without operator intervention.
- Live pods that breach the 10% drawdown limit are immediately demoted to paper, protecting capital.
- `hedge pods status` clearly shows which pods are on paper, which are live, why they were promoted/demoted, and when the next evaluation is.
- The operator can manually promote or demote any pod via CLI at any time.
- All lifecycle transitions are recorded in Decision DB for audit trail and future analysis.

## Scope Boundaries

- NOT a capital allocation system (no multipliers or variable position sizing based on pod rank) -- all pods get the same starting_capital for now
- NOT a composite ranking system for ordering pods -- promotion is binary (pass gates or not)
- NOT regime-conditional thresholds (e.g., stricter in bear markets) -- evaluate uniformly for now
- NOT correlation-based evaluation (measuring pod correlation to market or other pods)
- NOT a cooldown/probation period after demotion -- demoted pods can be re-promoted at the next weekly eval if they recover
- NOT changes to how the governor evaluates individual runs (market regime, deployment ratio, etc.) -- those existing behaviors are untouched

## Key Decisions

- **Two-tier system (paper -> live)**: No intermediate tiers. Simple, easy to reason about, and sufficient for 18 pods. Capital multiplier tiers deferred to a future enhancement.
- **10% drawdown from HWM as the hard stop**: More lenient than Millennium's 5% because our pods run concentrated Nordic small-cap strategies with inherently higher volatility.
- **Sharpe > 0.5 for promotion**: Lenient threshold appropriate for a new system with limited data. Can be tightened later via config.
- **30-day minimum observation**: Fast iteration over statistical rigor. Allows promoting pods within ~6 weeks of daemon startup. Configurable if the operator wants to extend.
- **Weekly evaluation + continuous drawdown**: Promotion is a deliberate weekly decision. Demotion on drawdown is a real-time circuit breaker. This matches industry practice.
- **Manual override without pin**: Overrides are temporary -- the next automated evaluation can change the tier back. This prevents forgotten manual overrides from creating stale state. If the operator wants a permanent override, they can set thresholds per-pod in config.
- **Sharpe measured on annualized basis**: Using the paper_snapshots time series (daily total_value) to compute returns and annualize. Consistent with paper_metrics.py which already computes this.

## Dependencies / Assumptions

- Paper trading (Milestone #4) is shipped and generating daily paper_snapshots per pod.
- Daemon mode (Milestone #5) is shipped and running scheduled pod execution.
- `paper_metrics.py` already computes Sharpe, Sortino, max drawdown, win rate -- reuse these.
- `PortfolioGovernor` already evaluates per-run market conditions -- lifecycle evaluation is a separate concern (pod-level, not run-level).
- Decision DB has `paper_snapshots` and `daemon_runs` tables for historical data.

## Outstanding Questions

### Resolve Before Planning

(none -- all product decisions resolved)

### Deferred to Planning

- [Affects R1][Technical] How does the daemon schedule the Monday evaluation job? New APScheduler cron job, or a hook into the existing Phase 1/2 flow?
- [Affects R3][Technical] Where does the continuous drawdown check hook in? During PaperExecutionEngine.mark_to_market(), or in the daemon's Phase 2 wrapper?
- [Affects R5][Technical] New Decision DB table (`lifecycle_events`) or extend `daemon_runs` with lifecycle columns?
- [Affects R8][Technical] Should lifecycle config live in `pods.yaml` (alongside pod definitions) or in a separate `config/lifecycle.yaml`?
- [Affects R10][Needs research] How to make tier transitions atomic when the daemon has in-flight runs -- reload pods from DB/config on each run, or cache with invalidation?

## Next Steps

-> `/ce:plan` for structured implementation planning
