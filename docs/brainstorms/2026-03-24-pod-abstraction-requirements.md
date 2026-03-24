---
date: 2026-03-24
topic: pod-abstraction
---

# Pod Abstraction: Config-Driven Analyst Pods with Independent Paper P&L

## Problem Frame

Analysts are a flat list of functions selected by hardcoded presets ("all", "famous", "core", "favorites"). They emit per-ticker signals that merge into one aggregated score -- there is no concept of an analyst proposing a complete portfolio, no independent P&L tracking per analyst, and no way to evaluate which analyst strategies actually perform well over time. The trading pod shop vision requires each analyst to operate as an independent pod: proposing its own portfolio, tracking its own paper returns, and being evaluable as a standalone strategy -- while still merging into one portfolio for real execution.

## Requirements

### Pod Definition and Configuration

- R1. A **pod** is a named, config-driven unit containing one analyst. The pod is the atomic unit of strategy in the system.
- R2. All pods are defined in a single `pods.yaml` config file (location TBD during planning). Each pod entry specifies: name, analyst key, enabled flag, max picks (default 3), and any pod-specific overrides (universe filter, governor profile).
- R3. Adding a new pod requires only a YAML entry -- no code changes. Removing or disabling a pod is a config change.
- R4. The hardcoded `_resolve_analyst_list()` preset chain is replaced by pod config resolution. CLI can still accept `--pod <name>` or `--pods all` to select which pods run.

### Pod Portfolio Proposal (New Analyst Output)

- R5. Each pod analyzes all tickers in the universe individually (existing per-ticker analysis behavior, unchanged).
- R6. After analyzing all tickers, each pod proposes a **complete portfolio**: its top N picks (configurable, default 3) with target allocation weights. Long-only. This is a new output layer -- the analyst goes from "signal emitter" to "portfolio proposer."
- R7. The portfolio proposal is the pod's own investment thesis based on its per-ticker analyses. The analyst agent (LLM or deterministic) synthesizes its individual ticker signals into a ranked portfolio.

### Decision DB Integration

- R8. The `pod_id` field (already nullable in Decision DB) is populated for every record when pods are active. Each pod's per-ticker signals, portfolio proposals, and downstream records are tagged with its pod_id.
- R9. A new record type captures each pod's **portfolio proposal**: pod_id, run_id, ranked list of picks with target weights, reasoning for the portfolio composition, created_at.
- R10. All existing Decision DB tables (signals, aggregations, governor_decisions, trade_recommendations, execution_outcomes) continue to work. Pod-level data is additive, not a schema break.

### Paper P&L Tracking

- R11. Each pod's proposed portfolio is tracked as a **virtual portfolio** with mark-to-market paper P&L. Using Borsdata close prices, the system can calculate each pod's paper return over any time period.
- R12. Paper P&L is computed from the sequence of portfolio proposals in Decision DB -- no separate positions table needed initially. Each proposal is a snapshot of the pod's desired portfolio at that point in time.
- R13. Paper P&L enables answering: "Which pod had the best returns over the last 30 days? 90 days?" This is the foundation for the future investment manager agent.

### Merged Execution

- R14. For real IBKR execution, all active (enabled) pods' portfolio proposals are **merged** into one combined portfolio. Initial merge: equal weight per pod.
- R15. The merged portfolio goes through the existing pipeline: governor evaluation, position sizing, trade generation, IBKR execution. From the governor's perspective, it sees one portfolio to evaluate.
- R16. The merge step is a clearly separated function so it can be replaced later with performance-weighted or investment-manager-driven allocation.

### CLI Integration

- R17. `hedge rebalance` accepts pod selection: `--pod buffett`, `--pods "buffett,simons"`, or `--pods all`. Replaces current `--analysts` flag.
- R18. A new `hedge pods` command shows pod status: name, analyst, enabled, latest proposal date, paper P&L summary.

## Success Criteria

- Can answer "what portfolio did the Buffett pod propose on March 5, and how has it performed since?"
- Can compare paper P&L across all pods over a rolling window
- Can run all pods end-to-end and see merged execution output
- Adding a new pod = adding a YAML entry, running `hedge rebalance --pods all`
- Decision DB queries by pod_id return the full chain: signals -> proposal -> merged trades -> execution
- Existing single-analyst CLI usage (`hedge rebalance --analysts fundamentals`) continues working or has a clear migration path

## Scope Boundaries

- NOT multi-analyst pods (future: pods with multiple analysts that "bounce off" each other)
- NOT investment manager agent (future: meta-agent that recommends pod allocation based on track record)
- NOT performance-weighted merge (future: pods with better track records get more weight in the merged portfolio)
- NOT daemon mode or scheduling (future: pods run on cron schedules)
- NOT web UI pod dashboard (future: visual pod management)
- NOT real-money capital partitioning per pod (all pods share one IBKR account, one merged portfolio)

## Key Decisions

- **1 pod = 1 analyst**: Simplest starting point. Multi-analyst pods are a future extension. Analyst agents already exist and work -- wrapping each in a pod adds identity and lifecycle without rewriting agents.
- **Portfolio proposer, not just signal emitter**: The key upgrade. Analysts go from "bullish on HEBA with 0.8 confidence" to "my portfolio: HEBA 40%, NIBE 35%, LUND 25%." This is what makes pods evaluable as strategies.
- **Paper P&L from proposals, not virtual positions**: Compute P&L from the sequence of portfolio proposals already stored in Decision DB. No separate position-tracking system needed. Simpler, and proposals are the source of truth.
- **Track separate, trade merged (Option C)**: Each pod's paper P&L is tracked independently for evaluation. Real IBKR trades come from a merged blend of all active pods. Gives clean evaluation data AND practical diversification.
- **Equal-weight merge to start**: All active pods contribute equally to the merged portfolio. Performance-weighted merge comes with the investment manager agent (future).
- **Single pods.yaml**: One file, all pods visible at a glance. Easy to diff, version control, and review.
- **EPM decomposition is a prerequisite**: The 67KB EnhancedPortfolioManager needs to be broken into pipeline stages (SignalCollector, Aggregator, PositionSizer, TradeGenerator) before pods can cleanly own their own runs. This is a separate planning/implementation step that comes first.
- **Long-only**: All pod portfolios are long-only. No short positions at the pod level.
- **All analysts become pods**: Deterministic analysts (technical, fundamentals, valuation, sentiment) propose portfolios by ranking tickers by score and taking the top N. LLM-based analysts synthesize their analyses into a portfolio with reasoning. Same pod interface, different internal mechanism.

## Dependencies / Assumptions

- **EPM decomposition must ship first**: Pods need clean pipeline stages to plug into. Without decomposition, pod integration would further bloat the monolith.
- **Decision DB is shipped**: pod_id nullable column exists, eager writes work, full pipeline chain is captured. Pods populate pod_id.
- **Borsdata close prices available for mark-to-market**: Paper P&L relies on daily close prices already fetched by the prefetch pipeline.
- **Analyst agents can be prompted to propose portfolios**: LLM-based analysts need a prompt upgrade to synthesize per-ticker signals into a ranked portfolio. Deterministic analysts need a new aggregation step.
- **Governor can evaluate a merged portfolio**: The existing governor sees one portfolio input -- the merge step produces this before governor evaluation.

## Outstanding Questions

### Deferred to Planning

- [Affects R2][Technical] Exact pods.yaml schema and location (config/ directory? project root?)
- [Affects R6][Technical] How to modify analyst agent prompts to request portfolio proposals -- single prompt with all ticker analyses, or two-stage (analyze then propose)?
- [Affects R9][Technical] Decision DB schema for portfolio proposals -- new table or extension of existing aggregations table?
- [Affects R11, R12][Needs research] Paper P&L computation: how to handle proposals that don't change between runs (same portfolio held)? Is P&L computed on-demand from proposals, or stored incrementally?
- [Affects R14][Technical] Merge algorithm details: how to handle N pods each proposing 3 picks with some overlap? Weighted average of target weights, or union of all picks with equal pod contribution?
- [Affects R4, R17][Technical] Migration path from `--analysts` flag to `--pods` flag -- backwards compatibility or clean break?
- [Affects EPM decomposition][Needs research] Which pipeline stages need extraction before pods can be wired in? Is full decomposition required, or can a minimal extraction (just the signal collection loop) unblock pods?

## Next Steps

-> `/ce:plan` for structured implementation planning (starting with EPM decomposition, then pod abstraction).
