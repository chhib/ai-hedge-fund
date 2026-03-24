---
title: "Decompose EnhancedPortfolioManager monolith into pipeline stages and pod abstraction system"
category: architecture
date: 2026-03-24
tags:
  - refactoring
  - pipeline-architecture
  - pod-abstraction
  - portfolio-management
  - independent-pnl-tracking
  - yaml-config
  - decision-db
  - concurrency
component: "src/agents/enhanced_portfolio_manager.py, src/services/pipeline/, src/config/pod_config.py, config/pods.yaml"
problem_type: architecture-refactoring-and-feature-addition
severity: high
---

# Decompose EnhancedPortfolioManager into Pipeline Stages and Pod Abstraction

## Problem

The `EnhancedPortfolioManager` (1,658 lines) was a monolith where signal collection, aggregation, position sizing, and trade generation were tightly coupled in a single class. Analysts ran as a flat list emitting per-ticker signals that merged into one consensus score. There was no abstraction for grouping analysts into independent strategy units, proposing portfolios per-analyst, or tracking per-analyst performance -- all prerequisites for the trading pod shop vision.

## Root Cause

Monolithic class accumulating orchestration logic over 50+ sessions. No separation of concerns between pipeline stages. All analyst configuration was hardcoded in Python presets ("all", "famous", "core", "favorites") with no config-driven mechanism.

## Solution

### Phase 1: EPM Decomposition (Pure Refactoring)

Extracted 4 pipeline modules into `src/services/pipeline/`:

| Module | Functions | Purpose |
|--------|-----------|---------|
| `signal_aggregator.py` | `aggregate_signals()`, `apply_long_only_constraint()`, `apply_ticker_penalties()` | Weighted signal merge per ticker |
| `position_sizer.py` | `select_top_positions()`, `calculate_target_positions()` | Top-N selection + target weight calculation |
| `trade_generator.py` | `generate_recommendations()`, `calculate_updated_portfolio()`, cash validation, rounding | Diff current vs target, produce orders |
| `signal_collector.py` | `SignalCollectionConfig` + `collect_signals()` | Parallel analyst execution with caching |

EPM methods became thin delegations:

```python
# Before: 30-line method inside EPM
def _aggregate_signals(self, signals, analyst_weights=None):
    ticker_signals = {}
    for signal in signals:
        ...  # all logic inline

# After: thin delegation
def _aggregate_signals(self, signals, analyst_weights=None):
    from src.services.pipeline.signal_aggregator import aggregate_signals
    return aggregate_signals(signals, analyst_weights, universe=self.universe)
```

**Decomposition order**: pure functions first (aggregator, position sizer), then coupled functions (trade generator, signal collector). Each extraction validated the approach before tackling the next.

### Phase 2: Pod Config System

```yaml
# config/pods.yaml
defaults:
  max_picks: 3
  enabled: true

pods:
  - name: warren_buffett
    analyst: warren_buffett
  - name: fundamentals
    analyst: fundamentals_analyst
  # ... 16 more pods
```

- `Pod` dataclass: `name`, `analyst`, `enabled`, `max_picks`
- `load_pods()` validates analyst keys against `ANALYST_CONFIG`
- `resolve_pods("all" | "buffett,simons" | "buffett")` for CLI selection

### Phase 3: Pod Proposer (Two-Stage)

Each pod analyzes all tickers individually (unchanged), then synthesizes a portfolio proposal:

- **LLM path**: second LLM call with analyst persona + all signals -> structured portfolio proposal
- **Deterministic path**: sort by `|signal| * confidence`, take top N, proportional weights
- **Fallback**: LLM failure automatically falls back to deterministic path

```python
def propose_portfolio(pod, signals, run_id, model_config):
    if uses_llm:
        try:
            return _propose_portfolio_llm(pod, signals, run_id, model_config)
        except Exception:
            return _propose_portfolio_deterministic(pod, signals, run_id)
    else:
        return _propose_portfolio_deterministic(pod, signals, run_id)
```

### Phase 4: Decision DB Extension

New `pod_proposals` table:

```sql
CREATE TABLE IF NOT EXISTS pod_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pod_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    target_weight REAL NOT NULL,
    signal_score REAL,
    reasoning TEXT,
    created_at TEXT NOT NULL
)
```

`pod_id` on `runs` table (already existed, now populated). Other tables cascade via `run_id` JOIN -- no schema migration needed on the 5 existing tables.

### Phase 5: Pod Runner + Merger + CLI

**Merge algorithm** (equal-weight, consensus amplification):

```
3 pods, each gets 1/3 of total portfolio weight:
  Buffett: HEBA 40%, NIBE 35%, LUND 25%
  Simons:  HEBA 30%, ERIC 40%, VOLV 30%
  Fundmtl: NIBE 50%, HEBA 25%, SEB 25%

Merged:
  HEBA: (40+30+25)/3 = 31.7%  (consensus -- appears in all 3 pods)
  NIBE: (35+50)/3    = 28.3%
  ERIC: 40/3         = 13.3%
  VOLV: 30/3         = 10.0%
  LUND: 25/3         =  8.3%
  SEB:  25/3         =  8.3%
```

**CLI**: `hedge rebalance --pods all`, `hedge pods` status command.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| 1 pod = 1 analyst | Single analyst per pod | Simplest starting point; multi-analyst pods deferred |
| Track separate, trade merged | Independent paper P&L per pod, merged real execution | Enables per-analyst evaluation without multiple brokerage accounts |
| Equal-weight merge | All pods contribute equally | Performance-weighted merge deferred to investment manager agent |
| Sequential pod execution | Pods run one at a time | LLM rate limits (not CPU) are the binding constraint |
| Governor post-merge only | Risk checks on merged portfolio | Per-pod governance deferred to Governor Pod Lifecycle feature |
| pod_id on runs table only | Cascade via run_id JOIN | Avoids schema migration on 5 existing Decision DB tables |

## Prevention Strategies

### 1. Data Merge Safety

**Session 34 bug**: `dict.update()` silently drops data when merging parallel results. The `PodMerger` uses explicit per-ticker weight accumulation, never `dict.update()`.

**Rule**: any merge of results from multiple sources must use an accumulation pattern (e.g., `defaultdict(list)` or a dedicated merger class). Ban `dict.update()` for merge operations.

### 2. Timeout Preservation

**Session 55 bug**: `ThreadPoolExecutor` with no timeout caused infinite hangs. The 120s timeout per analyst x ticker task was preserved in the `signal_collector` extraction.

**Rule**: every `concurrent.futures` call must have an explicit timeout. Treat a missing timeout as a bug.

### 3. Passive Observer Pattern

All Decision DB writes (including new pod proposal recording) are wrapped in `try/except`. The Decision DB is a passive observer that cannot break the pipeline.

**Rule**: any observability/recording layer must be wrapped in broad `try/except` and tested in broken-observer mode.

### 4. Decomposition Sequencing

Extract pure functions first (lowest coupling), coupled functions last. One extraction per commit. Characterization tests before and after each extraction.

### Monolith Decomposition Checklist

1. Read git log for prior failed approaches (Session 34, 55 bugs)
2. Write characterization tests before any extraction
3. Inventory all instance state accessed by each method
4. Rank extractions by coupling score (lowest first)
5. Extract one module per commit with tests passing after each
6. Preserve all timeout/retry/error-handling configs explicitly
7. Merge operations get their own class with explicit semantics
8. Observers are always try/except and tested in broken-observer mode
9. Run full pipeline end-to-end after every extraction
10. Document the sequence and rationale in the session log

## Cross-References

- **Origin vision**: `docs/ideation/2026-03-24-trading-pod-shop-ideation.md` (7 ranked ideas, dependency chain)
- **Pod requirements**: `docs/brainstorms/2026-03-24-pod-abstraction-requirements.md` (R1-R18)
- **Pod plan**: `docs/plans/2026-03-24-005-feat-pod-abstraction-config-driven-analyst-pods-plan.md`
- **Decision DB requirements**: `docs/brainstorms/2026-03-24-decision-db-requirements.md` (foundation)
- **Decision DB plan**: `docs/plans/2026-03-24-004-feat-decision-db-append-only-ledger-plan.md`
- **Session log**: `logs/sessions/session_111.md` (Sessions 116-118)
- **PRs**: #7 (EPM decomposition), #8 (pod abstraction)
