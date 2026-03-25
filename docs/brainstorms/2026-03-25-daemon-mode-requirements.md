---
date: 2026-03-25
topic: daemon-mode
---

# Daemon Mode -- Always-On Pod Scheduler

## Problem Frame

The trading pod shop (18 pods, Decision DB, paper trading) requires manual `hedge rebalance --pods all` for every cycle. A pod shop that depends on a human remembering to run the CLI is not a pod shop -- it's a checklist. Without an always-on daemon, paper pods can't accumulate meaningful P&L history for promotion evaluation, and live pods can't execute on market-appropriate schedules.

## Requirements

- R1. **Daemon process**: `hedge serve` starts a long-running foreground process that schedules and executes pod runs autonomously. Ctrl-C for graceful shutdown.
- R2. **Two-phase daily cycle**: Each pod run has two phases:
  - **Phase 1 (Analysis)**: Run signals + generate portfolio proposals. Scheduled before or around market open.
  - **Phase 2 (Execution)**: Price-drift check against Phase 1 proposals, then execute trades. Scheduled ~1 hour after market open when price discovery has settled.
- R3. **Per-pod scheduling**: Each pod has a schedule in `pods.yaml`. Support named presets (e.g., `daily-nordic-open`, `daily-us-open`) with raw cron expression as override.
- R4. **Market-hours gating**: When a scheduled run fires but the pod's relevant markets are closed (weekend, off-hours), skip silently and log a skip entry to Decision DB. Applies uniformly to both paper and live tiers.
- R5. **Price-drift revalidation (Phase 2)**: Before executing Phase 2 trades, compare current prices against Phase 1 proposal prices. If drift exceeds a configurable threshold, adjust position sizes or skip the trade. No re-running of LLM analysts -- Phase 2 is cheap.
- R6. **Failure handling with escalating backoff**: When a pod run fails (LLM timeout, rate limit, network error), retry up to 3 times with escalating delays (5min, 15min, 30min). If all retries fail, log the failure to Decision DB and skip to next scheduled time.
- R7. **IBKR gateway lifecycle management**: Daemon starts the IBKR Client Portal gateway on boot. If not authenticated, log a warning prompting the user to visit the auth URL. Periodically check auth status. Live execution is paused until authenticated. Paper pods run regardless.
- R8. **Decision DB as shared state**: All daemon state (run status, skip reasons, phase transitions, failures, retries) is written to Decision DB. No daemon HTTP endpoints. The existing FastAPI app and `hedge pods status` CLI read from Decision DB for dashboards and monitoring.
- R9. **Standalone process**: The daemon is a separate process from the FastAPI web backend. They share data only through Decision DB (already WAL-mode for concurrent access).
- R10. **Structured logging**: Daemon logs to stdout with structured format (timestamp, pod, phase, event). Foreground process -- user sees output directly.
- R11. **Graceful shutdown**: On SIGINT/SIGTERM, finish the currently running pod phase (don't interrupt mid-run), cancel pending scheduled runs, and exit cleanly.

## Success Criteria

- 18 pods run autonomously on schedule for a full trading week without manual intervention (beyond initial IBKR auth).
- Phase 1 proposals are available in Decision DB before market open; Phase 2 trades execute ~1hr post-open.
- Failed runs are retried and ultimately logged; no silent failures.
- `hedge pods status` shows daemon-driven run history indistinguishable from manual runs (same Decision DB schema).
- Daemon restart picks up where it left off (schedule state derived from config, not daemon memory).

## Scope Boundaries

- NOT web UI integration (that's milestone #7)
- NOT governor-driven pod promotion/demotion (that's milestone #6)
- NOT multi-machine deployment or distributed scheduling
- NOT notifications (Slack, email) -- future enhancement
- NOT holiday calendars -- skip weekends only; holiday awareness deferred
- NOT intraday trading or sub-hourly scheduling -- daily rhythm only
- NOT changes to the existing `hedge rebalance` CLI -- daemon calls the same `run_pods()` internally

## Key Decisions

- **Standalone daemon over merged FastAPI process**: Cleaner separation of concerns. Scheduler and web UI have different lifecycle and failure modes. They share data through Decision DB.
- **Decision DB as sole communication channel**: No inter-process HTTP or IPC. Daemon writes, others read. WAL mode already supports concurrent access.
- **Two-phase daily cycle over single run**: Separates expensive LLM work (Phase 1) from time-sensitive execution (Phase 2). Analysis can run during quiet hours; execution waits for price stability.
- **Price-drift check over full re-run**: Phase 2 is cheap (price comparison only). Re-running 18 pods of LLM calls would be expensive and slow, defeating the purpose of the two-phase split.
- **Uniform market-hours skip**: Both paper and live pods skip on closed markets. Uniform behavior, simpler mental model. Paper pods don't benefit from generating signals when markets are closed since prices haven't changed.
- **Presets with cron override**: Named presets cover the common case (Nordic open, US open). Raw cron expressions as escape hatch for unusual schedules. Prevents YAML full of opaque cron strings.
- **Foreground process (`hedge serve`)**: No PID file management, no backgrounding complexity. User runs it in a terminal or wraps it in systemd/launchd themselves.
- **Escalating backoff retries**: Handles transient failures (rate limits, network blips) without retry storms. 3 retries with 5/15/30 min delays. Overlap with next scheduled run is acceptable -- daemon skips if previous run is still in progress.

## Dependencies / Assumptions

- Decision DB schema may need new tables or columns for daemon-specific state (phase tracking, retry counts, skip reasons). Planning should determine exact schema changes.
- `run_pods()` in `portfolio_runner.py` is the execution entry point. Daemon wraps it with scheduling, not reimplements it.
- IBKR gateway start/stop uses existing `_start_ibkr_gateway()` and `_find_running_gateway()` helpers.
- `EXCHANGE_SESSIONS` in `ibkr_execution.py` provides market hours for schedule gating.
- APScheduler (or similar) will be the scheduling library. Planning should confirm the choice.
- Pod config (`config/pods.yaml`) will gain `schedule` and optionally `timezone` fields. Existing fields unchanged.

## Outstanding Questions

### Resolve Before Planning

(none -- all product decisions resolved)

### Deferred to Planning

- [Affects R3][Needs research] What schedule presets should be defined, and what are the exact cron expressions for "1 hour after Nordic open" vs "1 hour after US open"?
- [Affects R2][Technical] How does the daemon track Phase 1 -> Phase 2 handoff state? New Decision DB table, or new columns on existing `runs` table?
- [Affects R5][Technical] What price-drift threshold should be the default? How is drift calculated (absolute %, relative to average volume)?
- [Affects R6][Technical] How does the daemon prevent a retry from overlapping with the next scheduled run?
- [Affects R7][Technical] How to detect IBKR gateway crash vs intentional shutdown? Health check polling interval?
- [Affects R3][Technical] Should APScheduler use the `AsyncIOScheduler` or `BackgroundScheduler`? Depends on whether `run_pods()` is sync or async.
- [Affects R11][Technical] What "finish the current phase" means concretely -- is it per-analyst within a pod, or per-pod?

## Next Steps

→ `/ce:plan` for structured implementation planning
