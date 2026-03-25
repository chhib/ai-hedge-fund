---
date: 2026-03-24
topic: trading-pod-shop
focus: Transform from 5 favorite analysts to a trading pod shop with decision DB, paper trading promotion, always-on server, and web UI
---

# Ideation: Trading Pod Shop Architecture

## Codebase Context

**Project**: AI hedge fund -- Python/Poetry, FastAPI backend, Vite/React frontend. 19 analyst agents (13 famous-investor personas + 4 core + 2 sentiment). Pipeline: Borsdata API -> Parallel Fetcher -> SQLite Cache -> Analysts -> Portfolio Manager -> Governor -> IBKR Orders.

**Current state**:
- No pod abstraction: analysts are flat functions in a list, selected by "favorites" preset
- No decision DB: analyst outputs are transient (analysis_cache uses UPSERT, not append)
- No paper trading stage: goes straight from backtest to live IBKR execution
- Batch CLI only (`hedge rebalance`): no daemon/server mode, no scheduler
- Web UI exists (FastAPI + Vite/React) but is basic, CLI-first, no pod dashboards
- `enhanced_portfolio_manager.py` is 67KB monolith accumulating orchestration logic
- Rate limits are the scaling bottleneck (200+ tickers x 19 analysts)
- Multi-layer caching already proven (4 SQLite cache layers across 4 DB files)
- Governor system with Bayesian scorecard for analyst weighting exists
- IBKR integration battle-tested but fragile (50+ sessions of hardening)

**Key institutional learnings**:
- Parallel signal merge bug: naive dict assignment silently drops data -- must merge at ticker level
- At scale, LLM rate limits are primary constraint, not CPU (max_workers default 4)
- Governor + scorecard is the control plane -- build on it, not around it
- IBKR edge cases required 50+ sessions of iterative hardening

## Ranked Ideas

### 1. Decision DB -- Append-Only Ledger with Full Provenance
**Description:** Create a unified `decisions` table that records every analyst signal (run_id, pod_id, ticker, analyst, signal, confidence, reasoning, regime, governor weights, timestamp) as immutable append-only rows. Absorb the fragmented write paths (analysis_cache.py's UPSERT, analysis_storage.py's session writes, governor_history.db's snapshots) into one canonical store. Add an `executions` table linking decisions to what actually happened (IBKR fills, paper fills, or skipped).
**Rationale:** Highest-leverage single change. Every downstream feature -- scorecards, pod promotion, paper trading P&L, web dashboards, meta-analysis -- requires a queryable history of what each analyst said and what happened next. Currently analysis_cache uses UPSERT (overwrites on re-run), so signal drift is invisible.
**Downsides:** Migration risk with 4 existing DBs. DB size growth at scale. Schema evolution strategy needed early.
**Confidence:** 90%
**Complexity:** Medium
**Status:** Shipped (PR #6, Session 117)

### 2. Pod Abstraction -- Config-Driven Analyst Groups with Independent Lifecycle
**Description:** Introduce a Pod dataclass (name, analyst_names, universe_filter, governor_profile, position_limits, capital_allocation, execution_tier, schedule) replacing the hardcoded _resolve_analyst_list() if/elif chain. Pods defined in YAML config files. Each pod gets own rebalance run, decision journal entries, and scorecard history.
**Rationale:** Structural change everything else depends on. Without pods, can't run independent strategies with separate capital and risk profiles. The current 'favorites' preset is a workaround.
**Downsides:** Rethinking governor aggregation across pods. Significant EPM refactoring. Coordination between pods sharing same IBKR account.
**Confidence:** 85%
**Complexity:** High
**Status:** Shipped (PRs #7+#8, Session 118)

### 3. Decompose the 67KB EnhancedPortfolioManager into Pipeline Stages
**Description:** Extract enhanced_portfolio_manager.py (1,554 lines) into composable modules: SignalCollector, SignalAggregator, PositionSizer, TradeGenerator. Original class becomes thin orchestrator.
**Rationale:** Enabler for pod abstraction. Pods need own signal collection while sharing pricing/sizing. Each stage independently testable. Backtester can reuse same stages.
**Downsides:** Pure refactoring with no user-visible change. Risk of regression during extraction.
**Confidence:** 85%
**Complexity:** Medium
**Status:** Shipped (PR #7, Session 118)

### 4. Paper Trading Tier -- Virtual Execution with Forward P&L Tracking
**Description:** PaperTradingEngine that consumes same order list as ibkr_execution.py but records virtual fills using live Borsdata close prices. Track virtual positions, cash, and daily mark-to-market P&L per pod. Promotion to live requires configurable thresholds.
**Rationale:** Riskiest gap is backtest-to-live jump. Paper trading creates proving ground with real data and no capital risk. Enables promotion pipeline (backtest -> paper -> live).
**Downsides:** No real bid/ask spreads or slippage. Needs daily mark-to-market job. Simpler than real P&L (no dividends, FX).
**Confidence:** 80%
**Complexity:** High
**Status:** Shipped (PR #9, Session 119)

### 5. Daemon Mode -- APScheduler + FastAPI in One Process
**Description:** `hedge serve` command starting long-running process with APScheduler (per-pod cron schedules) + existing FastAPI backend. Market-hours awareness via EXCHANGE_SESSIONS. Health/status/trigger endpoints. CLI triggers via HTTP.
**Rationale:** Pod shop can't function with manual `hedge rebalance`. Market-hours logic exists but is reactive. FastAPI already runs as server -- avoid second long-running service.
**Downsides:** Needs monitoring, restart-on-crash, graceful shutdown. IBKR session keepalive fragile. Concurrent pod rate-limit competition.
**Confidence:** 80%
**Complexity:** Medium-High
**Status:** Unexplored

### 6. Governor-Driven Pod Promotion Ladder -- Automatic Promotion and Demotion
**Description:** Extend PortfolioGovernor with pod lifecycle state machine: backtest -> paper -> live. Monitor rolling P&L and scorecard metrics. Auto-promote when thresholds met, auto-demote on drawdown. Manual override always available.
**Rationale:** Governor + scorecard is existing control plane. Promotion gates are threshold checks on existing metrics. Without automation, 15 pods require constant manual oversight.
**Downsides:** False demotions during regime changes. Threshold calibration difficulty. Continuous monitoring is new pattern.
**Confidence:** 70%
**Complexity:** Medium
**Status:** Unexplored

### 7. Web UI Pod Dashboard -- Manage, Monitor, and Control Pods
**Description:** Extend FastAPI with /api/pods endpoints, React frontend with Pods page showing status, tier, signals, scorecard, P&L, and toggle controls. Builds on existing CRUD patterns.
**Rationale:** Web UI exists but disconnected from production. 15-pod shop needs visual management, not CLI flags and YAML.
**Downsides:** Frontend scope creep. Needs all backend pieces to be meaningful. Existing React app may need rework.
**Confidence:** 75%
**Complexity:** Medium-High
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Governor as event bus | Over-engineering for current scale; no immediate consumers |
| 2 | Actor/pull model (analysts from queue) | Premature for 15 pods; analyst_task_queue already provides durability |
| 3 | Governor auto-composes pods from scorecard | Removes human judgment from strategy selection; user wants to manage pods |
| 4 | Consolidate 4 SQLite DBs (standalone) | Subsumed by Decision DB; better done incrementally |
| 5 | Paper trading as decision-replay | Loses forward-looking validation; backtester already does historical replay |
| 6 | Analyst signal correlation detection | Niche optimization; premature until pod infrastructure exists |
| 7 | IBKR circuit breaker anomaly detection | Incremental safety; existing guards sufficient for now |
| 8 | LLM rate-limit pooling | Premature Day 1; current max_workers cap works for sequential pods |
| 9 | Scorecard-driven auto-rotation | Duplicates auto-compose; better as future governor enhancement |

## Implementation Sequence

Natural dependency chain:
1. Decision DB (foundation)
2. Monolith decomposition (enabler)
3. Pod abstraction (structure)
4. Paper trading (safety)
5. Daemon (operations)
6. Governor lifecycle (automation)
7. Web UI (control plane)

## Session Log
- 2026-03-24: Initial ideation (Claude Opus 4.6) -- 48 raw ideas from 6 sub-agents, 17 unique after dedup + 2 cross-cutting combos, 7 survivors
