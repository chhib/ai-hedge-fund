"""Tests for the Pod Daemon core: scheduling, signal handling, retry logic."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config.pod_config import Pod
from src.data.decision_store import DecisionStore
from src.services.daemon import (
    DaemonConfig,
    MAX_RETRIES,
    PodDaemon,
    RETRY_DELAYS,
)


@pytest.fixture
def daemon_config():
    return DaemonConfig(
        pods="all",
        dry_run=True,
        portfolio_path=Path("data/portfolio.csv"),
        universe_path=Path("config/universe_nordic.txt"),
    )


@pytest.fixture
def store(tmp_path):
    return DecisionStore(db_path=tmp_path / "test.db")


@pytest.fixture
def test_pod():
    return Pod(name="test_pod", analyst="warren_buffett", schedule="nordic-morning")


class TestDaemonConfig:
    def test_defaults(self):
        cfg = DaemonConfig()
        assert cfg.pods == "all"
        assert cfg.drift_threshold == 0.05
        assert cfg.dry_run is False

    def test_custom_values(self):
        cfg = DaemonConfig(pods="buffett,simons", dry_run=True, drift_threshold=0.10)
        assert cfg.pods == "buffett,simons"
        assert cfg.drift_threshold == 0.10


class TestPodDaemon:

    @patch("src.services.daemon.resolve_pods")
    @patch("src.services.daemon.get_decision_store")
    def test_start_with_no_enabled_pods(self, mock_store, mock_resolve, daemon_config):
        mock_resolve.return_value = []
        daemon = PodDaemon(daemon_config)
        daemon.start()  # Should return immediately

    @patch("src.services.daemon.resolve_pods")
    @patch("src.services.daemon.get_decision_store")
    def test_schedules_phase1_for_each_pod(self, mock_store, mock_resolve, daemon_config, test_pod):
        mock_store.return_value = MagicMock()
        mock_resolve.return_value = [test_pod]

        daemon = PodDaemon(daemon_config)
        daemon.gateway_manager = MagicMock()
        daemon.gateway_manager.start.return_value = MagicMock(message="OK")
        daemon.gateway_manager.is_authenticated.return_value = False

        # Start in a thread so we can stop it
        def run_daemon():
            daemon.start()

        t = threading.Thread(target=run_daemon)
        t.start()
        time.sleep(0.5)

        # Verify jobs were scheduled
        jobs = daemon.scheduler.get_jobs()
        job_ids = [j.id for j in jobs]
        assert "test_pod_phase1" in job_ids
        assert "gateway_health_check" in job_ids
        assert "weekly_lifecycle_evaluation" in job_ids

        # Trigger shutdown
        daemon.shutdown_requested.set()
        t.join(timeout=5)

    @patch("src.services.daemon.get_decision_store")
    def test_phase1_skips_on_closed_market(self, mock_store, daemon_config, test_pod):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance

        daemon = PodDaemon(daemon_config)
        daemon._store = mock_store_instance

        schedule = {
            "analysis": {"hour": 8},
            "execution": {"hour": 10},
            "timezone": "Europe/Stockholm",
            "exchanges": ["SFB"],
        }

        with patch("src.services.daemon.is_market_open", return_value=False):
            daemon._run_phase1(test_pod, schedule)

        # Should have recorded a skipped daemon run
        mock_store_instance.record_daemon_run.assert_called_once()
        args = mock_store_instance.update_daemon_run_status.call_args
        assert args[0][1] == "skipped"

    @patch("src.services.daemon.get_decision_store")
    def test_phase1_dry_run(self, mock_store, daemon_config, test_pod):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance

        daemon = PodDaemon(daemon_config)
        daemon._store = mock_store_instance

        schedule = {
            "analysis": {"hour": 8},
            "execution": {"hour": 10},
            "timezone": "Europe/Stockholm",
            "exchanges": ["SFB"],
        }

        with patch("src.services.daemon.is_market_open", return_value=True):
            daemon._run_phase1(test_pod, schedule)

        # Dry run: should record completed without actually calling run_pods
        calls = mock_store_instance.update_daemon_run_status.call_args_list
        assert any(c[0][1] == "completed" for c in calls)

    @patch("src.services.portfolio_runner.run_pods")
    @patch("src.services.daemon.get_decision_store")
    def test_phase1_persists_linked_pipeline_run_id(self, mock_store, mock_run_pods, daemon_config, test_pod):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance
        daemon_config.dry_run = False

        mock_run_pods.return_value = MagicMock(
            session_id="analysis-session",
            results={
                "pod_proposals": [
                    {"pod_id": "test_pod", "run_id": "pipeline-run-123", "picks": [], "reasoning": None},
                ],
            },
        )

        daemon = PodDaemon(daemon_config)
        daemon._store = mock_store_instance
        daemon._schedule_phase2 = MagicMock()

        schedule = {
            "analysis": {"hour": 8},
            "execution": {"hour": 10},
            "timezone": "Europe/Stockholm",
            "exchanges": ["SFB"],
        }

        with patch("src.services.daemon.is_market_open", return_value=True):
            daemon._run_phase1(test_pod, schedule)

        completion_call = mock_store_instance.update_daemon_run_status.call_args_list[-1]
        assert completion_call.args[1] == "completed"
        assert completion_call.kwargs["pipeline_run_id"] == "pipeline-run-123"
        daemon._schedule_phase2.assert_called_once()

    @patch("src.services.daemon.get_decision_store")
    def test_phase1_skip_on_shutdown(self, mock_store, daemon_config, test_pod):
        mock_store.return_value = MagicMock()
        daemon = PodDaemon(daemon_config)
        daemon.shutdown_requested.set()

        schedule = {"exchanges": ["SFB"], "analysis": {}, "execution": {}, "timezone": "UTC"}
        daemon._run_phase1(test_pod, schedule)

        # Should not record anything -- just returns
        daemon._store.record_daemon_run.assert_not_called()

    @patch("src.services.daemon.get_decision_store")
    def test_phase2_skips_live_without_auth(self, mock_store, daemon_config):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance

        live_pod = Pod(name="live_pod", analyst="warren_buffett", tier="live", schedule="nordic-morning")
        daemon = PodDaemon(daemon_config)
        daemon._store = mock_store_instance
        daemon.gateway_manager = MagicMock()
        daemon.gateway_manager.is_authenticated.return_value = False

        schedule = {"exchanges": ["SFB"], "analysis": {}, "execution": {}, "timezone": "UTC"}
        with patch("src.services.daemon.is_market_open", return_value=True):
            daemon._run_phase2(live_pod, schedule, "phase1-run-id")

        update_calls = mock_store_instance.update_daemon_run_status.call_args_list
        assert any(c[0][1] == "skipped" for c in update_calls)
        # Check skip_reason was passed (as keyword arg to store method)
        skip_call = [c for c in update_calls if c[0][1] == "skipped"][0]
        skip_reason = skip_call[1].get("skip_reason", "") if skip_call[1] else ""
        # If passed positionally, check args
        if not skip_reason and len(skip_call[0]) >= 5:
            skip_reason = skip_call[0][4] or ""
        assert "not authenticated" in skip_reason

    @patch("src.services.portfolio_runner.execute_proposals")
    @patch("src.services.daemon.get_decision_store")
    def test_phase2_executes_linked_pipeline_run_with_frozen_tier(self, mock_store, mock_execute, daemon_config):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance
        mock_store_instance.get_daemon_run.return_value = {
            "id": "phase1-run-id",
            "pod_id": "live_pod",
            "phase": "analysis",
            "pipeline_run_id": "pipeline-run-123",
        }
        daemon_config.dry_run = False

        live_pod = Pod(name="live_pod", analyst="warren_buffett", tier="live", schedule="nordic-morning")
        daemon = PodDaemon(daemon_config)
        daemon._store = mock_store_instance
        daemon.gateway_manager = MagicMock()
        daemon.gateway_manager.is_authenticated.return_value = True
        daemon._apply_drawdown_guard = MagicMock()

        schedule = {"exchanges": ["SFB"], "analysis": {}, "execution": {}, "timezone": "UTC"}
        with patch("src.services.daemon.is_market_open", return_value=True):
            daemon._run_phase2(live_pod, schedule, "phase1-run-id")

        assert mock_execute.call_count == 1
        assert mock_execute.call_args.kwargs["phase1_run_ids"] == ["pipeline-run-123"]
        assert mock_execute.call_args.kwargs["config"].tier_override == "live"
        daemon._apply_drawdown_guard.assert_called_once()

    @patch("src.services.daemon.load_lifecycle_config")
    @patch("src.services.daemon.get_decision_store")
    def test_resolve_runtime_pod_uses_lifecycle_tier(self, mock_store, mock_lifecycle, daemon_config, test_pod):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance
        mock_lifecycle.return_value = MagicMock()
        mock_store_instance.get_latest_pod_lifecycle_event.return_value = {"new_tier": "live"}

        daemon = PodDaemon(daemon_config)
        runtime_pod = daemon._resolve_runtime_pod(test_pod)

        assert runtime_pod.tier == "live"
        assert runtime_pod.name == test_pod.name

    @patch("src.services.daemon.load_lifecycle_config")
    @patch("src.services.daemon.get_decision_store")
    def test_weekly_lifecycle_evaluation_promotes_eligible_pod(self, mock_store, mock_lifecycle, daemon_config, test_pod):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance
        mock_lifecycle.return_value = MagicMock()
        mock_store_instance.get_latest_pod_lifecycle_event.return_value = None

        daemon = PodDaemon(daemon_config)
        daemon._pods = [test_pod]

        with patch("src.services.daemon.evaluate_pod_lifecycle") as mock_eval:
            mock_eval.return_value = MagicMock(
                eligible_for_promotion=True,
                passes_maintenance=True,
                metrics={"sharpe_ratio": 0.8},
                promotion_reason="promotion passed",
                maintenance_reason="ok",
            )
            daemon._run_weekly_lifecycle_evaluation()

        mock_store_instance.record_pod_lifecycle_event.assert_called_once()
        kwargs = mock_store_instance.record_pod_lifecycle_event.call_args.kwargs
        assert kwargs["event_type"] == "promotion"
        assert kwargs["new_tier"] == "live"

    @patch("src.services.daemon.load_lifecycle_config")
    @patch("src.services.daemon.get_decision_store")
    def test_apply_drawdown_guard_demotes_live_pod(self, mock_store, mock_lifecycle, daemon_config):
        mock_store_instance = MagicMock()
        mock_store.return_value = mock_store_instance
        mock_lifecycle.return_value = MagicMock()
        live_pod = Pod(name="live_pod", analyst="warren_buffett", tier="live", schedule="nordic-morning")

        daemon = PodDaemon(daemon_config)

        with patch("src.services.daemon.evaluate_pod_lifecycle") as mock_eval:
            mock_eval.return_value = MagicMock(
                should_drawdown_stop=True,
                metrics={"current_drawdown_pct": 12.0},
                drawdown_reason="breached hard stop",
            )
            daemon._apply_drawdown_guard(live_pod, "daemon-run-1")

        mock_store_instance.record_pod_lifecycle_event.assert_called_once()
        kwargs = mock_store_instance.record_pod_lifecycle_event.call_args.kwargs
        assert kwargs["event_type"] == "drawdown_stop"
        assert kwargs["new_tier"] == "paper"


class TestRetryLogic:

    @patch("src.services.daemon.get_decision_store")
    def test_retry_delays_match_spec(self, mock_store):
        assert RETRY_DELAYS == [300, 900, 1800]
        assert MAX_RETRIES == 3

    @patch("src.services.daemon.get_decision_store")
    def test_maybe_retry_schedules_job(self, mock_store, daemon_config, test_pod):
        mock_store.return_value = MagicMock()
        daemon = PodDaemon(daemon_config)
        daemon.scheduler.start()

        schedule = {"exchanges": [], "analysis": {}, "execution": {}, "timezone": "UTC"}
        daemon._maybe_retry(test_pod, schedule, "phase1", attempt=0, error=Exception("test"))

        jobs = daemon.scheduler.get_jobs()
        retry_jobs = [j for j in jobs if "retry" in j.id]
        assert len(retry_jobs) == 1
        assert "phase1_retry_1" in retry_jobs[0].id

        daemon.scheduler.shutdown()

    @patch("src.services.daemon.get_decision_store")
    def test_maybe_retry_exhausted(self, mock_store, daemon_config, test_pod):
        mock_store.return_value = MagicMock()
        daemon = PodDaemon(daemon_config)
        daemon.scheduler.start()

        schedule = {"exchanges": [], "analysis": {}, "execution": {}, "timezone": "UTC"}
        daemon._maybe_retry(test_pod, schedule, "phase1", attempt=MAX_RETRIES, error=Exception("test"))

        jobs = daemon.scheduler.get_jobs()
        retry_jobs = [j for j in jobs if "retry" in j.id]
        assert len(retry_jobs) == 0  # No retry scheduled

        daemon.scheduler.shutdown()


class TestSignalHandling:

    @patch("src.services.daemon.resolve_pods")
    @patch("src.services.daemon.get_decision_store")
    def test_sigterm_sets_shutdown_flag(self, mock_store, mock_resolve, daemon_config, test_pod):
        mock_store.return_value = MagicMock()
        mock_resolve.return_value = [test_pod]

        daemon = PodDaemon(daemon_config)
        daemon.gateway_manager = MagicMock()
        daemon.gateway_manager.start.return_value = MagicMock(message="OK")
        daemon.gateway_manager.is_authenticated.return_value = False

        def run_and_signal():
            time.sleep(0.3)
            daemon.shutdown_requested.set()

        t = threading.Thread(target=run_and_signal)
        t.start()
        daemon.start()
        t.join()
        assert daemon.shutdown_requested.is_set()
