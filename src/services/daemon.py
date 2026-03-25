"""Pod Daemon: always-on scheduler with two-phase pod execution.

Phase 1 (Analysis): Run signals + generate proposals via run_pods(analysis_only=True)
Phase 2 (Execution): Price-drift validation + execute trades via execute_proposals()

Uses APScheduler BackgroundScheduler for cron-triggered pod runs.
All state persisted to Decision DB. Graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config.pod_config import Pod, load_lifecycle_config, resolve_pods
from src.data.decision_store import get_decision_store
from src.services.gateway_manager import GatewayManager
from src.services.pod_lifecycle import evaluate_pod_lifecycle, resolve_effective_tier
from src.utils.market_hours import is_market_open, resolve_schedule

if TYPE_CHECKING:
    from src.services.portfolio_runner import RebalanceConfig

logger = logging.getLogger(__name__)

# Retry delays in seconds: 5min, 15min, 30min
RETRY_DELAYS = [300, 900, 1800]
MAX_RETRIES = len(RETRY_DELAYS)

# Gateway health check interval in seconds
GATEWAY_HEALTH_INTERVAL = 60
LIFECYCLE_EVALUATION_HOUR = 6


@dataclass
class DaemonConfig:
    """Configuration for the pod daemon."""
    pods: str = "all"
    model: str = "gpt-4o"
    model_provider: Optional[str] = None
    dry_run: bool = False
    drift_threshold: float = 0.05
    home_currency: str = "SEK"
    portfolio_source: str = "csv"
    portfolio_path: Optional[Path] = None
    universe_path: Optional[Path] = None
    universe_tickers: Optional[str] = None
    ibkr_port: int = 5001
    ibkr_account: Optional[str] = None
    ibkr_host: str = "https://localhost"
    max_workers: int = 50
    max_holdings: int = 8
    max_position: float = 0.25
    min_position: float = 0.05
    min_trade: float = 500.0
    use_governor: bool = False
    governor_profile: str = "preservation"
    no_cache: bool = False
    verbose: bool = False


class PodDaemon:
    """Always-on pod scheduler with two-phase execution."""

    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self.shutdown_requested = threading.Event()
        self.gateway_manager = GatewayManager(port=config.ibkr_port)
        self.scheduler = BackgroundScheduler(
            job_defaults={"max_instances": 1, "coalesce": True},
        )
        self._pods: List[Pod] = []
        self._store = get_decision_store()
        self._lifecycle_config = load_lifecycle_config()

    def start(self) -> None:
        """Start the daemon: resolve pods, schedule jobs, enter main loop."""
        self._install_signal_handlers()

        # Resolve pods
        self._pods = resolve_pods(self.config.pods)
        enabled = [p for p in self._pods if p.enabled]
        if not enabled:
            logger.error("No enabled pods found. Exiting.")
            return

        logger.info("Daemon starting with %d pods", len(enabled))

        # Start IBKR gateway
        gw_status = self.gateway_manager.start()
        logger.info("IBKR gateway: %s", gw_status.message)

        # Schedule Phase 1 jobs for each pod
        for pod in enabled:
            self._schedule_phase1(pod)

        # Schedule gateway health check
        self.scheduler.add_job(
            self._check_gateway_health,
            trigger=IntervalTrigger(seconds=GATEWAY_HEALTH_INTERVAL),
            id="gateway_health_check",
            name="IBKR gateway health check",
        )

        # Schedule weekly lifecycle evaluation
        self.scheduler.add_job(
            self._run_weekly_lifecycle_evaluation,
            trigger=CronTrigger(day_of_week="mon", hour=LIFECYCLE_EVALUATION_HOUR, minute=0, timezone="Europe/Stockholm"),
            id="weekly_lifecycle_evaluation",
            name="Weekly lifecycle evaluation",
            replace_existing=True,
        )

        # Listen for job events
        self.scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

        # Start scheduler and block
        self.scheduler.start()
        self._print_schedule_summary(enabled)

        logger.info("Daemon running. Press Ctrl-C to stop.")
        try:
            self.shutdown_requested.wait()
        finally:
            logger.info("Shutting down scheduler...")
            self.scheduler.shutdown(wait=True)
            logger.info("Daemon stopped.")

    def _schedule_phase1(self, pod: Pod) -> None:
        """Register a cron-triggered Phase 1 job for a pod."""
        schedule = resolve_schedule(pod.schedule)
        tz = schedule["timezone"]
        analysis_kwargs = schedule["analysis"]

        trigger = CronTrigger(timezone=tz, **analysis_kwargs)
        job_id = f"{pod.name}_phase1"

        self.scheduler.add_job(
            self._run_phase1,
            trigger=trigger,
            args=[pod, schedule],
            id=job_id,
            name=f"Phase 1: {pod.name}",
            replace_existing=True,
        )

        logger.info("Scheduled %s Phase 1: %s (%s)", pod.name, schedule["description"], tz)

    def _run_phase1(self, pod: Pod, schedule: Dict[str, Any], attempt: int = 0) -> None:
        """Execute Phase 1 (analysis) for a pod."""
        if self.shutdown_requested.is_set():
            logger.info("Shutdown requested. Skipping Phase 1 for %s", pod.name)
            return

        # Market-hours gate
        exchanges = schedule.get("exchanges", [])
        if exchanges and not any(is_market_open(ex) for ex in exchanges):
            daemon_run_id = str(uuid.uuid4())
            self._store.record_daemon_run(daemon_run_id, pod.name, "analysis", "skipped")
            self._store.update_daemon_run_status(daemon_run_id, "skipped", skip_reason="Market closed")
            logger.info("Phase 1 %s: skipped (market closed)", pod.name)
            return

        daemon_run_id = str(uuid.uuid4())
        self._store.record_daemon_run(daemon_run_id, pod.name, "analysis", "running")

        if self.config.dry_run:
            logger.info("Phase 1 %s: DRY RUN (would run analysis)", pod.name)
            self._store.update_daemon_run_status(daemon_run_id, "completed")
            return

        try:
            from src.services.portfolio_runner import run_pods

            runtime_pod = self._resolve_runtime_pod(pod)
            config = self._build_rebalance_config(runtime_pod, analysis_only=True)
            outcome = run_pods(config)

            self._store.update_daemon_run_status(daemon_run_id, "completed")
            logger.info("Phase 1 %s: completed (session=%s)", pod.name, outcome.session_id)

            # Schedule Phase 2
            self._schedule_phase2(runtime_pod, schedule, daemon_run_id)

        except Exception as e:
            logger.error("Phase 1 %s: failed (%s)", pod.name, e, exc_info=True)
            self._store.update_daemon_run_status(daemon_run_id, "failed", error_message=str(e), retry_count=attempt)
            self._maybe_retry(pod, schedule, "phase1", attempt, e)

    def _schedule_phase2(self, pod: Pod, schedule: Dict[str, Any], phase1_daemon_run_id: str) -> None:
        """Schedule a one-shot Phase 2 job for today's execution time."""
        from datetime import date, time as dt_time
        from zoneinfo import ZoneInfo

        tz_name = schedule["timezone"]
        tz = ZoneInfo(tz_name)
        execution_kwargs = schedule["execution"]

        # Compute today's execution time as a one-shot DateTrigger
        exec_hour = int(execution_kwargs.get("hour", 10))
        exec_minute = int(execution_kwargs.get("minute", 0))
        today = date.today()
        run_date = datetime.combine(today, dt_time(exec_hour, exec_minute), tzinfo=tz)

        # If execution time has already passed today, run in 5 minutes
        now = datetime.now(tz)
        if run_date <= now:
            from datetime import timedelta
            run_date = now + timedelta(minutes=5)

        trigger = DateTrigger(run_date=run_date)
        job_id = f"{pod.name}_phase2"  # Deterministic: replaces any prior Phase 2

        self.scheduler.add_job(
            self._run_phase2,
            trigger=trigger,
            args=[pod, schedule, phase1_daemon_run_id],
            id=job_id,
            name=f"Phase 2: {pod.name}",
            replace_existing=True,
        )

        logger.info("Scheduled Phase 2 for %s at %s", pod.name, run_date.strftime("%H:%M %Z"))

    def _run_phase2(self, pod: Pod, schedule: Dict[str, Any], phase1_daemon_run_id: str, attempt: int = 0) -> None:
        """Execute Phase 2 (price-drift validation + execution) for a pod."""
        if self.shutdown_requested.is_set():
            logger.info("Shutdown requested. Skipping Phase 2 for %s", pod.name)
            return

        # Market-hours gate
        exchanges = schedule.get("exchanges", [])
        if exchanges and not any(is_market_open(ex) for ex in exchanges):
            daemon_run_id = str(uuid.uuid4())
            self._store.record_daemon_run(daemon_run_id, pod.name, "execution", "skipped", phase1_run_id=phase1_daemon_run_id)
            self._store.update_daemon_run_status(daemon_run_id, "skipped", skip_reason="Market closed")
            logger.info("Phase 2 %s: skipped (market closed)", pod.name)
            return

        # For live pods, check gateway auth
        if pod.tier == "live" and not self.gateway_manager.is_authenticated():
            daemon_run_id = str(uuid.uuid4())
            self._store.record_daemon_run(daemon_run_id, pod.name, "execution", "skipped", phase1_run_id=phase1_daemon_run_id)
            self._store.update_daemon_run_status(daemon_run_id, "skipped", skip_reason="IBKR gateway not authenticated")
            logger.warning("Phase 2 %s: skipped (IBKR not authenticated)", pod.name)
            return

        daemon_run_id = str(uuid.uuid4())
        self._store.record_daemon_run(daemon_run_id, pod.name, "execution", "running", phase1_run_id=phase1_daemon_run_id)

        if self.config.dry_run:
            logger.info("Phase 2 %s: DRY RUN (would execute trades)", pod.name)
            self._store.update_daemon_run_status(daemon_run_id, "completed")
            return

        try:
            from src.services.portfolio_runner import execute_proposals

            # Find the Phase 1 pipeline run_ids (from Decision DB runs table, linked via daemon_runs)
            phase1_db_run = self._store.get_daemon_run(phase1_daemon_run_id)
            if not phase1_db_run:
                raise RuntimeError(f"Phase 1 daemon run {phase1_daemon_run_id} not found")

            # Get the actual pipeline run_ids for this pod from the runs table
            recent_runs = self._store.get_runs(pod_id=pod.name)
            phase1_run_ids = [r["run_id"] for r in recent_runs[:1]] if recent_runs else []

            if not phase1_run_ids:
                raise RuntimeError(f"No pipeline runs found for pod {pod.name}")

            config = self._build_rebalance_config(pod)
            execute_proposals(
                phase1_run_ids=phase1_run_ids,
                config=config,
                drift_threshold=self.config.drift_threshold,
            )

            if pod.tier == "live":
                self._apply_drawdown_guard(pod, daemon_run_id)

            self._store.update_daemon_run_status(daemon_run_id, "completed")
            logger.info("Phase 2 %s: completed", pod.name)

        except Exception as e:
            logger.error("Phase 2 %s: failed (%s)", pod.name, e, exc_info=True)
            self._store.update_daemon_run_status(daemon_run_id, "failed", error_message=str(e), retry_count=attempt)
            self._maybe_retry(pod, schedule, "phase2", attempt, e, phase1_daemon_run_id=phase1_daemon_run_id)

    def _maybe_retry(
        self,
        pod: Pod,
        schedule: Dict[str, Any],
        phase: str,
        attempt: int,
        error: Exception,
        phase1_daemon_run_id: str | None = None,
    ) -> None:
        """Schedule a retry with escalating backoff if attempts remain."""
        if attempt >= MAX_RETRIES:
            logger.error("%s %s: all %d retries exhausted. Giving up.", phase, pod.name, MAX_RETRIES)
            return

        delay = RETRY_DELAYS[attempt]
        next_attempt = attempt + 1
        logger.warning("%s %s: scheduling retry %d/%d in %ds", phase, pod.name, next_attempt, MAX_RETRIES, delay)

        from datetime import timedelta
        run_time = datetime.now() + timedelta(seconds=delay)
        retry_id = f"{pod.name}_{phase}_retry_{next_attempt}"

        if phase == "phase1":
            self.scheduler.add_job(
                self._run_phase1,
                trigger=DateTrigger(run_date=run_time),
                args=[pod, schedule, next_attempt],
                id=retry_id,
                name=f"Retry {next_attempt}: Phase 1 {pod.name}",
                replace_existing=True,
            )
        else:
            self.scheduler.add_job(
                self._run_phase2,
                trigger=DateTrigger(run_date=run_time),
                args=[pod, schedule, phase1_daemon_run_id, next_attempt],
                id=retry_id,
                name=f"Retry {next_attempt}: Phase 2 {pod.name}",
                replace_existing=True,
            )

    def _check_gateway_health(self) -> None:
        """Periodic IBKR gateway health check."""
        status = self.gateway_manager.check_health()
        if not status.available:
            logger.warning("Gateway health: %s", status.message)

    def _build_rebalance_config(self, pod: Pod, analysis_only: bool = False) -> "RebalanceConfig":
        """Build a RebalanceConfig for a single pod run."""
        from src.services.portfolio_runner import RebalanceConfig

        return RebalanceConfig(
            portfolio_path=self.config.portfolio_path,
            universe_path=self.config.universe_path,
            universe_tickers=self.config.universe_tickers,
            pods=pod.name,
            model=self.config.model,
            model_provider=self.config.model_provider,
            max_workers=self.config.max_workers,
            max_holdings=self.config.max_holdings,
            max_position=self.config.max_position,
            min_position=self.config.min_position,
            min_trade=self.config.min_trade,
            home_currency=self.config.home_currency,
            dry_run=self.config.dry_run,
            portfolio_source=self.config.portfolio_source,
            ibkr_account=self.config.ibkr_account,
            ibkr_host=self.config.ibkr_host,
            ibkr_port=self.config.ibkr_port,
            use_governor=self.config.use_governor,
            governor_profile=self.config.governor_profile,
            no_cache=self.config.no_cache,
            verbose=self.config.verbose,
            analysis_only=analysis_only,
        )

    def _resolve_runtime_pod(self, pod: Pod) -> Pod:
        """Resolve and freeze the effective tier for a cycle."""
        effective_tier = resolve_effective_tier(pod.name, pod.tier, store=self._store)
        return Pod(
            name=pod.name,
            analyst=pod.analyst,
            enabled=pod.enabled,
            max_picks=pod.max_picks,
            tier=effective_tier,
            starting_capital=pod.starting_capital,
            schedule=pod.schedule,
        )

    def _run_weekly_lifecycle_evaluation(self) -> None:
        """Promote/demote pods based on lifecycle policy."""
        for pod in self._pods:
            evaluation = evaluate_pod_lifecycle(pod.name, resolve_effective_tier(pod.name, pod.tier, store=self._store), self._lifecycle_config, store=self._store)
            current_tier = resolve_effective_tier(pod.name, pod.tier, store=self._store)

            if current_tier == "paper" and evaluation.eligible_for_promotion:
                self._store.record_pod_lifecycle_event(
                    pod_id=pod.name,
                    event_type="promotion",
                    old_tier="paper",
                    new_tier="live",
                    reason=evaluation.promotion_reason,
                    source="weekly_evaluation",
                    metrics=evaluation.metrics,
                )
            elif current_tier == "live" and not evaluation.passes_maintenance:
                self._store.record_pod_lifecycle_event(
                    pod_id=pod.name,
                    event_type="weekly_maintenance",
                    old_tier="live",
                    new_tier="paper",
                    reason=evaluation.maintenance_reason,
                    source="weekly_evaluation",
                    metrics=evaluation.metrics,
                )

    def _apply_drawdown_guard(self, pod: Pod, daemon_run_id: str) -> None:
        """Demote live pods that breach the hard-stop drawdown threshold."""
        evaluation = evaluate_pod_lifecycle(pod.name, "live", self._lifecycle_config, store=self._store)
        if evaluation.should_drawdown_stop:
            self._store.record_pod_lifecycle_event(
                pod_id=pod.name,
                event_type="drawdown_stop",
                old_tier="live",
                new_tier="paper",
                reason=evaluation.drawdown_reason,
                source="drawdown_guard",
                metrics=evaluation.metrics,
                daemon_run_id=daemon_run_id,
            )

    def _install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers for graceful shutdown.

        Only works from the main thread; silently skips otherwise (e.g., in tests).
        """
        import threading as _threading
        if _threading.current_thread() is not _threading.main_thread():
            return

        def _handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info("Received %s. Initiating graceful shutdown...", sig_name)
            self.shutdown_requested.set()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _on_job_event(self, event) -> None:
        """Log APScheduler job execution events."""
        if event.exception:
            logger.error("Job %s raised: %s", event.job_id, event.exception)

    def _print_schedule_summary(self, pods: List[Pod]) -> None:
        """Print a startup banner with scheduled pods."""
        logger.info("=" * 60)
        logger.info("Pod Daemon Schedule")
        logger.info("-" * 60)
        for pod in pods:
            schedule = resolve_schedule(pod.schedule)
            logger.info("  %-25s %s", pod.name, schedule["description"])
        logger.info("-" * 60)
        logger.info("Drift threshold: %.1f%%", self.config.drift_threshold * 100)
        logger.info("Dry run: %s", self.config.dry_run)
        logger.info("IBKR gateway: %s", "authenticated" if self.gateway_manager.is_authenticated() else "not authenticated")
        logger.info("=" * 60)
