"""Tests for IBKR Gateway lifecycle manager."""

from unittest.mock import patch

import pytest

from src.services.gateway_manager import GatewayManager, GatewayStatus, MAX_CONSECUTIVE_FAILURES


class TestGatewayManager:

    def test_start_finds_running_authenticated(self):
        with patch("src.services.portfolio_runner._find_running_gateway", return_value=("https://localhost:5001", True)):
            gm = GatewayManager()
            status = gm.start()
            assert status.available is True
            assert status.authenticated is True
            assert gm.base_url == "https://localhost:5001"

    def test_start_finds_running_not_authenticated(self):
        with patch("src.services.portfolio_runner._find_running_gateway", return_value=("https://localhost:5001", False)):
            gm = GatewayManager()
            status = gm.start()
            assert status.available is True
            assert status.authenticated is False
            assert "not authenticated" in status.message.lower()

    def test_start_not_running_starts_gateway(self):
        with (
            patch("src.services.portfolio_runner._find_running_gateway", return_value=(None, False)),
            patch("src.services.portfolio_runner._start_ibkr_gateway", return_value=True),
        ):
            gm = GatewayManager(port=5001)
            status = gm.start()
            assert status.available is True
            assert status.authenticated is False
            assert gm.base_url == "https://localhost:5001"

    def test_start_not_running_start_fails(self):
        with (
            patch("src.services.portfolio_runner._find_running_gateway", return_value=(None, False)),
            patch("src.services.portfolio_runner._start_ibkr_gateway", return_value=False),
        ):
            gm = GatewayManager()
            status = gm.start()
            assert status.available is False

    def test_start_exception_does_not_raise(self):
        with patch("src.services.portfolio_runner._find_running_gateway", side_effect=Exception("boom")):
            gm = GatewayManager()
            status = gm.start()  # Should not raise
            assert status.available is False

    def test_health_check_healthy(self):
        with patch("src.services.portfolio_runner._check_ibkr_gateway", return_value=(True, True)):
            gm = GatewayManager()
            gm.base_url = "https://localhost:5001"
            status = gm.check_health()
            assert status.available is True
            assert status.authenticated is True
            assert gm.consecutive_failures == 0

    def test_health_check_running_not_authed(self):
        with patch("src.services.portfolio_runner._check_ibkr_gateway", return_value=(True, False)):
            gm = GatewayManager()
            gm.base_url = "https://localhost:5001"
            status = gm.check_health()
            assert status.available is True
            assert status.authenticated is False

    def test_health_check_failure_increments_counter(self):
        with patch("src.services.portfolio_runner._check_ibkr_gateway", return_value=(False, False)):
            gm = GatewayManager()
            gm.base_url = "https://localhost:5001"
            status = gm.check_health()
            assert gm.consecutive_failures == 1
            assert status.available is False

    def test_health_check_triggers_restart_after_max_failures(self):
        with (
            patch("src.services.portfolio_runner._check_ibkr_gateway", return_value=(False, False)),
            patch("src.services.portfolio_runner._start_ibkr_gateway", return_value=True),
        ):
            gm = GatewayManager()
            gm.base_url = "https://localhost:5001"
            gm.consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1

            status = gm.check_health()
            # Should have triggered restart
            assert gm.consecutive_failures == 0
            assert status.available is True

    def test_health_check_restart_fails(self):
        with (
            patch("src.services.portfolio_runner._check_ibkr_gateway", return_value=(False, False)),
            patch("src.services.portfolio_runner._start_ibkr_gateway", return_value=False),
        ):
            gm = GatewayManager()
            gm.base_url = "https://localhost:5001"
            gm.consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1

            status = gm.check_health()
            assert status.available is False

    def test_health_check_no_base_url(self):
        gm = GatewayManager()
        status = gm.check_health()
        assert status.available is False
        assert "No gateway URL" in status.message

    def test_health_check_exception_does_not_raise(self):
        with patch("src.services.portfolio_runner._check_ibkr_gateway", side_effect=Exception("network error")):
            gm = GatewayManager()
            gm.base_url = "https://localhost:5001"
            status = gm.check_health()  # Should not raise
            assert status.available is False

    def test_is_authenticated(self):
        gm = GatewayManager()
        assert gm.is_authenticated() is False

        gm.available = True
        gm.authenticated = True
        assert gm.is_authenticated() is True

        gm.authenticated = False
        assert gm.is_authenticated() is False

    def test_get_status(self):
        gm = GatewayManager()
        status = gm.get_status()
        assert isinstance(status, GatewayStatus)
        assert status.available is False
