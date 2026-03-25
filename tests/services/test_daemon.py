"""Tests for the Pod Daemon core: scheduling, signal handling, retry logic."""

from __future__ import annotations

import signal
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from zoneinfo import ZoneInfo

import pytest

from src.config.pod_config import Pod
from src.data.decision_store import DecisionStore
from src.services.daemon import (
    DaemonConfig,
    GATEWAY_HEALTH_INTERVAL,
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

        # Mock market as closed (Saturday)
        saturday = datetime(2026, 3, 28, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
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
        # Check skip_reason was passed (5th positional arg)
        skip_call = [c for c in update_calls if c[0][1] == "skipped"][0]
        # Args: (daemon_run_id, status, error_message, retry_count, skip_reason)
        all_args = skip_call[0]
        assert len(all_args) >= 5
        assert "not authenticated" in (all_args[4] or "")


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
