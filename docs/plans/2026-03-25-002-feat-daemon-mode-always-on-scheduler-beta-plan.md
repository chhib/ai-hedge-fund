---
title: "feat: Daemon Mode -- Always-On Pod Scheduler with Two-Phase Execution"
type: feat
status: completed
date: 2026-03-25
origin: docs/brainstorms/2026-03-25-daemon-mode-requirements.md
---

# feat: Daemon Mode -- Always-On Pod Scheduler with Two-Phase Execution

## Overview

Add `hedge serve` -- a standalone foreground daemon that schedules and executes pod runs autonomously using a two-phase daily cycle: analysis (pre-open LLM work) and execution (~1hr post-open with price-drift validation). The daemon communicates exclusively through Decision DB and manages the IBKR gateway lifecycle.

## Problem Frame

The trading pod shop has 18 pods, a Decision DB, and paper trading -- but every cycle requires manual `hedge rebalance --pods all`. A pod shop that depends on a human typing a CLI command is operationally unsustainable. Paper pods can't accumulate meaningful P&L history for promotion evaluation, and live pods can't execute on market-appropriate schedules. (see origin: docs/brainstorms/2026-03-25-daemon-mode-requirements.md)

## Requirements Trace

- R1. `hedge serve` starts a long-running foreground process
- R2. Two-phase daily cycle: analysis then execution
- R3. Per-pod scheduling with presets + cron override
- R4. Market-hours gating (skip closed markets, both tiers)
- R5. Price-drift revalidation in Phase 2
- R6. Escalating backoff retries (3x: 5min/15min/30min)
- R7. IBKR gateway lifecycle management
- R8. Decision DB as sole shared state
- R9. Standalone process (separate from FastAPI)
- R10. Structured logging to stdout
- R11. Graceful shutdown (finish current pod, cancel pending)

## Scope Boundaries

- NOT web UI integration (milestone #7)
- NOT governor-driven promotion/demotion (milestone #6)
- NOT notifications (Slack, email)
- NOT holiday calendars (weekends only)
- NOT intraday/sub-hourly scheduling
- NOT changes to existing `hedge rebalance` behavior

## Context & Research

### Relevant Code and Patterns

- `src/services/portfolio_runner.py:run_pods()` -- synchronous execution entry point the daemon wraps
- `src/config/pod_config.py:Pod` -- dataclass with `slots=True`, needs `schedule` field added
- `src/data/decision_store.py` -- append-only SQLite with WAL mode, singleton accessor, passive observer pattern (try/except on all writes)
- `src/integrations/ibkr_execution.py:EXCHANGE_SESSIONS` -- 18 exchanges with timezone + hours
- `src/integrations/ibkr_execution.py:_is_market_open()` -- reusable market-hours check
- `src/services/portfolio_runner.py:_start_ibkr_gateway()`, `_find_running_gateway()`, `_check_ibkr_gateway()` -- existing gateway helpers
- `src/cli/hedge.py` -- Click CLI group, pattern for adding new top-level commands
- `src/integrations/ibkr_client.py:_request()` -- request-level retry with 1-8s backoff (separate layer from daemon retry)

### Institutional Learnings

- **WAL multi-process access**: Current WAL testing covers intra-process threads only. Multi-process access (daemon + FastAPI + CLI) needs `PRAGMA busy_timeout` to avoid `SQLITE_BUSY` errors.
- **Passive observer pattern**: All Decision DB writes are `try/except` wrapped so recording failures cannot break the pipeline. Daemon state writes must follow the same pattern.
- **ThreadPoolExecutor 120s timeout**: `signal_collector.py` uses 120s timeout per analyst-ticker task. Graceful shutdown must let in-flight futures drain (up to 120s) rather than force-killing.
- **Dict merge bug**: Any aggregation of results from multiple pod runs must use accumulation pattern, not `dict.update()`.
- **IBKR client retry is request-level** (1-8s backoff). Daemon retry is pod-run-level (5/15/30min). These are independent layers.

## Key Technical Decisions

- **APScheduler 3.x `BackgroundScheduler`**: `run_pods()` is synchronous and uses ThreadPoolExecutor internally. AsyncIOScheduler would require async wrappers for no benefit. BackgroundScheduler runs jobs in its own thread pool, which fits. (Resolves deferred question from origin doc)
- **`analysis_only` flag on `run_pods()`**: The two-phase split is achieved by adding a config flag that makes `run_pods()` return after generating proposals without executing trades. This avoids duplicating orchestration logic. A new `execute_proposals()` function handles Phase 2.
- **New `daemon_runs` table**: Phase tracking, retry counts, and skip reasons stored in a new Decision DB table (not columns on existing `runs` table). Cleaner separation -- `runs` records pipeline runs, `daemon_runs` records scheduling metadata. Phase 2 references Phase 1 via `phase1_run_id`. (Resolves deferred question from origin doc)
- **Schedule presets derived from EXCHANGE_SESSIONS**: Presets map to timezone-aware cron expressions using the same exchange data. No duplicate market-hours data. (Resolves deferred question from origin doc)
- **`max_instances=1` per APScheduler job**: Prevents retry/schedule overlap. If a retry is running when the next scheduled time arrives, APScheduler skips it. (Resolves deferred question from origin doc)
- **Extract `_is_market_open()` to shared module**: Currently private in `ibkr_execution.py`. The daemon needs it for schedule gating. Move to `src/utils/market_hours.py` with `EXCHANGE_SESSIONS` so both modules can import it.
- **Price-drift threshold**: Default 5% absolute change (`abs(current - proposal) / proposal`). Configurable globally via `hedge serve --drift-threshold`. Per-trade skip when exceeded. (Resolves deferred question from origin doc)
- **Graceful shutdown is per-pod**: SIGINT/SIGTERM sets a flag. The current pod's `run_pods()` call finishes (including ThreadPoolExecutor drain). No new pods start. APScheduler pending jobs are cancelled. (Resolves deferred question from origin doc)
- **`busy_timeout` PRAGMA**: Add `PRAGMA busy_timeout=5000` to Decision DB `_initialize()` for safe multi-process concurrent access.

## Open Questions

### Resolved During Planning

- **Scheduler type**: BackgroundScheduler (sync codebase, ThreadPoolExecutor concurrency)
- **Phase handoff mechanism**: New `daemon_runs` table with `phase1_run_id` FK
- **Price-drift default**: 5% absolute change
- **Overlap prevention**: APScheduler `max_instances=1`
- **Shutdown granularity**: Per-pod (finish current, cancel rest)
- **Market-hours extraction**: Move to `src/utils/market_hours.py`

### Deferred to Implementation

- Exact preset names and cron expressions will be finalized when implementing the preset registry (likely: `nordic-morning`, `us-morning`, `nordic-close`, `weekly-nordic`)
- Whether `run_pods()` needs internal refactoring to cleanly support `analysis_only` or if it can be achieved with an early return after proposal generation
- IBKR gateway health check polling interval (likely 60s, but may need tuning based on gateway behavior)

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
hedge serve
    |
    v
[Daemon Bootstrap]
    |-- Load pods.yaml (with schedule fields)
    |-- Resolve schedule presets -> cron expressions
    |-- Start IBKR gateway (if not running)
    |-- Check IBKR auth -> log warning if not authenticated
    |-- Initialize APScheduler BackgroundScheduler
    |-- Register Phase 1 jobs (per-pod cron triggers)
    |-- Register IBKR health check job (periodic)
    |-- Install SIGINT/SIGTERM handler
    |-- Enter main loop (scheduler.start(), block until shutdown)

[Phase 1 Job: Analysis] (per pod, cron-triggered)
    |-- Check shutdown flag -> abort if set
    |-- Check market hours via _is_market_open() -> skip + log if closed
    |-- Record daemon_run (phase=analysis, status=running)
    |-- Call run_pods(config, analysis_only=True)
    |-- Record daemon_run (status=completed, proposals saved)
    |-- Schedule Phase 2 for this pod (~1hr later)
    |-- On failure: record + schedule retry with backoff

[Phase 2 Job: Execution] (per pod, delayed trigger from Phase 1)
    |-- Check shutdown flag
    |-- Check market hours (should still be open)
    |-- Load Phase 1 proposals from Decision DB
    |-- Price-drift check per ticker
    |-- If paper tier: execute via PaperExecutionEngine
    |-- If live tier: check IBKR auth -> skip if not authed
    |-- Execute trades
    |-- Record daemon_run (phase=execution, status=completed)

[IBKR Health Check] (periodic, e.g., every 60s)
    |-- Call _check_ibkr_gateway()
    |-- If down 3x consecutive: attempt restart
    |-- If unauthed: log warning with auth URL
    |-- Update internal gateway_status flag

[Shutdown]
    |-- Signal handler sets shutdown_requested event
    |-- Current run_pods() call finishes naturally
    |-- scheduler.shutdown(wait=True)
    |-- Log clean exit
```

## Implementation Units

- [x] **Unit 1: Market Hours Extraction + Pod Schedule Config**

  **Goal:** Move market-hours logic to a shared module and add schedule support to pods.

  **Requirements:** R3, R4

  **Dependencies:** None

  **Files:**
  - Create: `src/utils/market_hours.py`
  - Modify: `src/integrations/ibkr_execution.py` (import from new location)
  - Modify: `src/config/pod_config.py` (add `schedule` field to Pod)
  - Modify: `config/pods.yaml` (add `schedule` default)
  - Test: `tests/utils/test_market_hours.py`
  - Test: `tests/config/test_pod_config.py`

  **Approach:**
  - Extract `EXCHANGE_SESSIONS`, `_is_market_open()`, and `_market_status_label()` from `ibkr_execution.py` into `src/utils/market_hours.py` as public functions
  - `ibkr_execution.py` imports from the new module (backward-compatible)
  - Add `schedule: str = "nordic-morning"` to `Pod` dataclass
  - Add schedule preset registry mapping preset names to `(analysis_cron, execution_cron, timezone)` tuples, derived from `EXCHANGE_SESSIONS` data
  - Support raw cron strings as override (detect by presence of spaces/asterisks)
  - Add `schedule: nordic-morning` to `pods.yaml` defaults section

  **Patterns to follow:**
  - `src/config/pod_config.py` existing field pattern (slots=True dataclass, YAML defaults section)
  - `src/integrations/ibkr_execution.py` market-hours logic

  **Test scenarios:**
  - Preset resolution returns correct cron expressions for nordic-morning, us-morning
  - Raw cron expression passthrough works
  - Invalid preset name raises ValueError
  - Pod loader reads schedule field from YAML with defaults
  - `is_market_open()` still works for all 18 exchanges after extraction
  - Weekend detection still correct

  **Verification:**
  - All existing IBKR execution tests still pass (no behavioral change)
  - New market-hours tests cover timezone edge cases (Nordic vs US)
  - Pod config tests load schedule field correctly

- [x] **Unit 2: Decision DB Daemon State**

  **Goal:** Add `daemon_runs` table and busy_timeout for multi-process safety.

  **Requirements:** R8, R6

  **Dependencies:** None (can run in parallel with Unit 1)

  **Files:**
  - Modify: `src/data/decision_store.py` (new table, new methods, busy_timeout)
  - Test: `tests/data/test_decision_store.py`

  **Approach:**
  - Add `PRAGMA busy_timeout=5000` to `_initialize()` after WAL mode
  - New `daemon_runs` table: `id` (UUID PK), `pod_id`, `phase` (analysis/execution), `status` (scheduled/running/completed/failed/skipped), `retry_count` (int), `skip_reason` (nullable text), `phase1_run_id` (nullable, FK to self for Phase 2 -> Phase 1 linkage), `error_message` (nullable text), `started_at`, `completed_at`, `created_at`
  - New methods: `record_daemon_run()`, `update_daemon_run_status()`, `get_latest_daemon_run()`, `get_phase1_run_id()`
  - All writes wrapped in try/except (passive observer pattern)
  - `update_daemon_run_status()` is the one exception to append-only: daemon_runs status transitions are UPDATEs (scheduled -> running -> completed/failed/skipped). This is acceptable because daemon_runs is operational metadata, not decision audit trail

  **Patterns to follow:**
  - Existing `record_signal()`, `record_run()` patterns in `decision_store.py`
  - Parameterized queries, `self._connect()` per call, `with conn:` for commit

  **Test scenarios:**
  - Record and retrieve daemon run lifecycle (scheduled -> running -> completed)
  - Phase 2 references Phase 1 via `phase1_run_id`
  - Failed run records error_message and retry_count
  - Skipped run records skip_reason
  - busy_timeout prevents SQLITE_BUSY on concurrent writes (multi-thread simulation)
  - Broken Decision DB (simulated) does not crash the daemon write methods

  **Verification:**
  - All existing Decision DB tests still pass
  - New daemon_runs lifecycle tests cover all status transitions

- [x] **Unit 3: Two-Phase Pipeline Split**

  **Goal:** Enable `run_pods()` to return after analysis (Phase 1) and add a Phase 2 execution function that revalidates with price-drift check.

  **Requirements:** R2, R5

  **Dependencies:** Unit 2 (daemon_runs table for phase tracking)

  **Files:**
  - Modify: `src/services/portfolio_runner.py` (add `analysis_only` to RebalanceConfig, early return path, new `execute_proposals()` function)
  - Create: `src/services/price_validator.py` (price-drift check logic)
  - Test: `tests/services/test_portfolio_runner.py`
  - Test: `tests/services/test_price_validator.py`

  **Approach:**
  - Add `analysis_only: bool = False` to `RebalanceConfig`
  - In `run_pods()`, after the pod proposal loop completes but before the paper/live execution split: if `analysis_only` is True, return early with proposals in the outcome (no trades generated, no execution)
  - New `execute_proposals(phase1_run_id, config)` function:
    1. Load proposals from Decision DB for the given `phase1_run_id`
    2. For each proposal ticker, fetch current price from Borsdata
    3. Compare against proposal's assumed price -- if drift > threshold, mark trade as skipped with reason
    4. Split by tier: paper pods -> PaperExecutionEngine, live pods -> merge + governor + IBKR execution
    5. Return execution outcome
  - `PriceValidator` in `price_validator.py`: takes proposals + current prices, returns adjusted proposals with skip annotations. Threshold configurable (default 5%)
  - `hedge rebalance` behavior unchanged -- `analysis_only` defaults to False

  **Patterns to follow:**
  - `run_pods()` existing flow for proposal generation
  - `PaperExecutionEngine` pattern for per-pod execution
  - `src/services/pipeline/` module structure

  **Test scenarios:**
  - `run_pods(analysis_only=True)` returns proposals without executing trades
  - `execute_proposals()` loads correct proposals from Decision DB
  - Price drift below threshold: trade executes normally
  - Price drift above threshold: trade skipped with reason
  - Price drift exactly at threshold: trade executes (threshold is exclusive)
  - Missing current price (Borsdata unavailable): trade skipped with reason
  - Paper tier execution through PaperExecutionEngine works in Phase 2
  - `hedge rebalance` (no analysis_only flag) still works end-to-end unchanged

  **Verification:**
  - Existing `hedge rebalance` tests still pass (no regression)
  - Price validator handles edge cases (zero price, missing data)
  - Phase 1 proposals persist in Decision DB and Phase 2 reads them correctly

- [x] **Unit 4: IBKR Gateway Lifecycle Manager**

  **Goal:** Non-throwing gateway management that starts, monitors, and restarts the gateway, pausing live execution when unauthenticated.

  **Requirements:** R7

  **Dependencies:** Unit 1 (market hours for determining when live pods need gateway)

  **Files:**
  - Create: `src/services/gateway_manager.py`
  - Test: `tests/services/test_gateway_manager.py`

  **Approach:**
  - `GatewayManager` class with methods: `start()`, `check_health()`, `is_authenticated()`, `get_status()`
  - On init: attempt to find running gateway via `_find_running_gateway()`, start if not found via `_start_ibkr_gateway()`
  - `check_health()` calls `_check_ibkr_gateway()`. If down for 3 consecutive checks, attempt restart. If unauthed, log warning with auth URL
  - Internal state: `gateway_available: bool`, `gateway_authenticated: bool`, `consecutive_failures: int`
  - All methods non-throwing -- return status, never raise. Live pod execution checks `is_authenticated()` before proceeding
  - Reuses existing helpers from `portfolio_runner.py` (import, not duplicate)
  - Logging via `logging.getLogger(__name__)` for structured output

  **Patterns to follow:**
  - Existing `_find_running_gateway()`, `_start_ibkr_gateway()`, `_check_ibkr_gateway()` helpers
  - Passive observer error handling (try/except, never crash)

  **Test scenarios:**
  - Gateway already running and authenticated: reports healthy
  - Gateway not running: starts it, reports status
  - Gateway running but not authenticated: logs warning, reports unauthed
  - Gateway crashes (3 consecutive health check failures): triggers restart
  - Restart fails: reports unavailable, does not retry indefinitely
  - All methods return cleanly (no exceptions) even on internal errors

  **Verification:**
  - Gateway manager never throws exceptions
  - Status correctly reflects gateway state through lifecycle transitions

- [x] **Unit 5: Daemon Core -- Scheduler, Signal Handling, Retry Logic**

  **Goal:** The main daemon process: APScheduler BackgroundScheduler with per-pod cron jobs, SIGINT/SIGTERM handling, and escalating backoff retry wrapper.

  **Requirements:** R1, R6, R9, R10, R11

  **Dependencies:** Units 1-4 (all building blocks)

  **Files:**
  - Create: `src/services/daemon.py`
  - Test: `tests/services/test_daemon.py`

  **Approach:**
  - `PodDaemon` class encapsulating all daemon state:
    - `scheduler: BackgroundScheduler`
    - `shutdown_requested: threading.Event`
    - `gateway_manager: GatewayManager`
    - `config: DaemonConfig` (pods, drift_threshold, dry_run, model settings)
  - `start()`: resolve pod schedules -> register Phase 1 cron jobs (one per enabled pod, `max_instances=1`) -> register IBKR health check job (interval trigger, 60s) -> install signal handlers -> `scheduler.start()` -> block on `shutdown_requested.wait()`
  - `_run_phase1(pod)`: market-hours gate -> record daemon_run -> `run_pods(analysis_only=True)` -> on success: schedule one-shot Phase 2 job (~1hr later) -> on failure: schedule retry with escalating backoff
  - `_run_phase2(pod, phase1_run_id)`: market-hours check -> `execute_proposals(phase1_run_id)` -> record outcome -> on failure: retry
  - `_retry_wrapper(fn, pod, phase, attempt=0)`: calls `fn()`, on exception: if attempt < 3, schedule retry after `[300, 900, 1800][attempt]` seconds. Record each attempt in daemon_runs
  - Signal handler: `shutdown_requested.set()` -- main loop exits, `scheduler.shutdown(wait=True)` lets current job finish
  - Structured logging: `logging.getLogger("daemon")` with format including timestamp, pod, phase, event
  - APScheduler job IDs: `f"{pod.name}_phase1"` for cron jobs, `f"{pod.name}_phase2_{run_id}"` for one-shot Phase 2 jobs

  **Patterns to follow:**
  - `portfolio_runner.py:run_pods()` for constructing `RebalanceConfig`
  - `decision_store.py` passive observer pattern for all DB writes
  - Click-based CLI logging style (rich/colorama output for user-facing messages)

  **Test scenarios:**
  - Daemon starts, schedules correct number of Phase 1 jobs (one per enabled pod)
  - Phase 1 job fires, calls `run_pods(analysis_only=True)`, schedules Phase 2
  - Phase 2 job fires after delay, calls `execute_proposals()`
  - Market-hours gate: Phase 1 skips when market closed, logs skip reason
  - Retry on failure: first failure schedules retry at 5min, second at 15min, third at 30min, fourth gives up
  - SIGINT: sets shutdown flag, current job completes, scheduler stops
  - SIGTERM: same as SIGINT
  - Disabled pods are not scheduled
  - `max_instances=1` prevents overlapping runs for same pod
  - Dry-run mode: logs actions without calling `run_pods()`

  **Verification:**
  - Daemon starts and schedules all enabled pods
  - Graceful shutdown completes without orphaned threads
  - Retry escalation follows 5/15/30min pattern
  - Decision DB records all phase transitions

- [x] **Unit 6: CLI `hedge serve` Command**

  **Goal:** Add the `hedge serve` Click command that wires configuration to the daemon.

  **Requirements:** R1, R3, R10

  **Dependencies:** Unit 5 (daemon core)

  **Files:**
  - Modify: `src/cli/hedge.py` (add `serve` command)
  - Test: `tests/cli/test_hedge_serve.py`

  **Approach:**
  - `@cli.command("serve")` at the top level (peer to `rebalance`)
  - Options: `--pods` (which pods to schedule, default "all"), `--dry-run` (log without executing), `--drift-threshold` (price-drift %, default 5.0), `--model` / `--model-provider` (reuse existing options pattern from `rebalance`), IBKR options (reuse `--ibkr-port`, `--ibkr-account` pattern)
  - Constructs `DaemonConfig` from options, instantiates `PodDaemon`, calls `daemon.start()`
  - Startup banner: log resolved pod schedules, IBKR status, drift threshold
  - Add `apscheduler = "^3.10"` to `pyproject.toml` dependencies

  **Patterns to follow:**
  - `rebalance` command option pattern in `hedge.py`
  - Click option decorators with `envvar` defaults

  **Test scenarios:**
  - `hedge serve --help` shows all options
  - `hedge serve --pods "buffett,simons"` resolves correct pods
  - `hedge serve --dry-run` starts daemon in dry-run mode
  - Invalid `--pods` value shows helpful error
  - Missing pods.yaml shows helpful error

  **Verification:**
  - `hedge serve --help` renders correctly
  - `hedge serve --dry-run --pods all` starts, logs schedules, and exits cleanly on Ctrl-C

## System-Wide Impact

- **Interaction graph:** Daemon calls `run_pods()` (existing entry point), `execute_proposals()` (new), `PaperExecutionEngine` (existing), IBKR execution (existing). All downstream code unchanged.
- **Error propagation:** Daemon catches all exceptions from `run_pods()` / `execute_proposals()` and handles via retry or skip. Decision DB writes use passive observer pattern. Daemon process itself only exits on signal or unrecoverable error.
- **State lifecycle risks:** Phase 1 proposals in Decision DB must persist until Phase 2 reads them (~1hr later). If daemon restarts between phases, orphaned Phase 1 runs should be detectable via `daemon_runs` status (running with no completion). Phase 2 should check for this and skip gracefully.
- **API surface parity:** `hedge pods status` already reads from Decision DB -- daemon-triggered runs appear automatically with no changes needed.
- **Integration coverage:** End-to-end test: daemon starts -> Phase 1 fires for one pod -> proposals written to DB -> Phase 2 fires -> execution recorded. This crosses scheduler, pipeline, Decision DB, and paper execution layers.

## Risks & Dependencies

- **APScheduler 3.x vs 4.x**: APScheduler 4.x is a major rewrite with breaking changes. Pin to `^3.10` to avoid surprises.
- **IBKR gateway session expiry**: Gateway sessions expire after ~24hrs of inactivity. The daemon's periodic health check should detect this, but re-authentication requires manual browser interaction. Long-running daemon will need user attention daily.
- **LLM rate limits under scheduled load**: 18 pods running Phase 1 sequentially may take significant time. If total analysis exceeds the window before Phase 2, execution timing slips. Sequential execution is correct (rate limits are the bottleneck) but the daemon should log total Phase 1 duration for monitoring.
- **SQLite busy contention**: Multiple processes (daemon, FastAPI, CLI) writing to Decision DB. `busy_timeout=5000` should handle normal contention, but sustained high-frequency writes from 18 pods could cause delays. Monitor and increase timeout if needed.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-25-daemon-mode-requirements.md](docs/brainstorms/2026-03-25-daemon-mode-requirements.md)
- **Ideation:** [docs/ideation/2026-03-24-trading-pod-shop-ideation.md](docs/ideation/2026-03-24-trading-pod-shop-ideation.md) (item #5)
- Related code: `src/services/portfolio_runner.py:run_pods()`, `src/data/decision_store.py`, `src/config/pod_config.py`
- Prior plans: `docs/plans/2026-03-25-001-feat-paper-trading-virtual-execution-plan.md` (Paper Trading, predecessor milestone)
