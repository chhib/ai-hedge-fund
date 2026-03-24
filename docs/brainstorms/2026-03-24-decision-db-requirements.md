---
date: 2026-03-24
topic: decision-db
---

# Decision DB: Append-Only Decision Ledger

## Problem Frame

Analyst signals are currently transient -- analysis_cache.py uses UPSERT (overwrites on re-run), analysis_storage.py writes to a web-app DB with no structured link to execution outcomes, and governor snapshots live in a separate DB with no connection to the signals that produced them. The result: you cannot answer "what did the system recommend on March 5, at what price, and what happened next?" Every downstream feature in the trading pod shop vision (pod evaluation, paper trading, scorecards, dashboards, meta-analysis) requires a queryable history of the full decision chain.

## Requirements

### Signal Ledger
- R1. Every analyst signal is stored as an **immutable, append-only** row. Re-runs on the same day create new rows, never overwrite.
- R2. Each signal record includes: run_id, pod_id (nullable initially, required once pods exist), ticker, analyst_name, signal (bullish/neutral/bearish), signal_numeric, confidence, full reasoning transcript, model_name, model_provider, analysis_date, created_at timestamp.
- R3. Each signal record captures **price context at analysis time**: close price from Borsdata, and optionally bid/ask from IBKR if available. The Decision DB should be self-contained for evaluation without re-fetching historical prices.
- R4. The **full analyst transcript** (complete reasoning, not just a summary) is stored with each signal. Store as much as possible for future flexibility.

### Aggregation Records
- R5. After signals are collected for a run, store the **aggregated result**: run_id, pod_id, ticker, weighted_signal, consensus_score, contributing_analyst_count, aggregation_method, created_at.

### Governor Decision Records
- R6. Each governor evaluation is stored: run_id, pod_id, regime, risk_state, trading_enabled, deployment_ratio, min_cash_buffer, analyst_weights (JSON), ticker_penalties (JSON), reasons (JSON), benchmark_drawdown_pct, average_credibility, average_conviction, created_at.

### Trade Recommendation Records
- R7. Each generated trade recommendation is stored: run_id, pod_id, ticker, side (buy/sell/hold), quantity, target_weight, current_weight, limit_price, reason, created_at.

### Execution Outcome Records
- R8. Each execution outcome (IBKR fill, paper fill, rejection, deferral) is stored and **linked to the trade recommendation**: recommendation_id, execution_type (live/paper/skipped), fill_price, fill_quantity, fill_timestamp, ibkr_order_id (nullable), rejection_reason (nullable), created_at.

### Write Strategy
- R9. Signals are written **eagerly** as each analyst produces output (crash-resilient -- partial runs are preserved). Tagged with a run_id generated at pipeline start.
- R10. Aggregation, governor, trade, and execution records are written at their respective pipeline stages (not batched at end of run).

### Storage
- R11. New standalone **decisions.db** SQLite file in the `data/` directory. Existing databases (prefetch_cache.db, analyst_tasks.db, governor_history.db, hedge_fund.db) continue unchanged.
- R12. No migration of existing data. The Decision DB starts collecting from the first run after deployment. Old DBs remain the source of truth for historical data predating the Decision DB.

### Query Support
- R13. Efficient queries by: (a) run_id, (b) pod_id + date range, (c) analyst + ticker + date range, (d) ticker + date range across all analysts.
- R14. A single run's full decision chain (signals -> aggregation -> governor -> trades -> execution) is retrievable by run_id.

## Success Criteria

- Can answer "what did analyst X say about ticker Y on date Z, and at what price?"
- Can answer "what was the full decision chain for run R, from signals to execution?"
- Can trace a bad outcome back to its root cause (bad signal vs bad execution vs governor override)
- A mid-run crash preserves all signals written before the crash
- Existing functionality (analysis_cache, scorecard, governor, IBKR execution) continues working unchanged
- The Decision DB is usable as the data foundation for future pod evaluation, paper trading P&L, and dashboard queries

## Scope Boundaries

- NOT consolidating existing DBs into the Decision DB (future incremental migration)
- NOT switching the scorecard or governor to read from Decision DB yet (future migration)
- NOT building web UI endpoints for querying the Decision DB (that's the Dashboard idea)
- NOT building paper trading P&L evaluation on top of this data (that's the Paper Trading idea)
- NOT implementing pod_id population (requires the Pod Abstraction idea first; nullable for now)

## Key Decisions

- **Full pipeline capture**: Store the entire chain (signals -> aggregation -> governor -> trades -> execution), not just signals. Enables end-to-end attribution.
- **SQLite**: Consistent with the rest of the project. No Postgres complexity for a single-user system.
- **Eager writes**: Signals written as they arrive for crash resilience. No batching.
- **Standalone DB file**: New decisions.db, coexisting with old DBs. Eventually bring over the good parts of old storage.
- **Store everything**: Full transcripts, price context, governor reasoning. Collect now, decide how to use later.

## Dependencies / Assumptions

- Pipeline stages (signal collection, aggregation, governor, trade generation, execution) are identifiable integration points where writes can be injected
- Borsdata close prices are available at signal time (already fetched by the prefetch pipeline)
- IBKR bid/ask prices are best-effort (only available when gateway is running)
- run_id generation happens early in the pipeline (portfolio_runner.py or equivalent)
- pod_id is nullable until the Pod Abstraction idea is implemented

## Outstanding Questions

### Deferred to Planning
- [Affects R2, R6][Technical] Exact column types and index strategy -- should reasoning be stored as TEXT or JSON? Should we use SQLite JSON1 extension for querying nested fields?
- [Affects R1, R9][Technical] Where exactly in the pipeline to inject the eager write calls -- which functions in enhanced_portfolio_manager.py are the right integration points?
- [Affects R3][Technical] How to capture IBKR bid/ask alongside Borsdata close -- is the IBKR snapshot already available at signal time, or does it need a separate fetch?
- [Affects R11][Technical] Should the DB use WAL mode for concurrent reads from daemon + web UI?
- [Affects R5][Needs research] What does the current signal aggregation step produce exactly -- what intermediate data structures exist between raw signals and governor input?
- [Affects R14][Needs research] What is the best way to link records across tables -- foreign keys, or shared run_id + sequential writes?

## Next Steps

-> /ce:plan for structured implementation planning
