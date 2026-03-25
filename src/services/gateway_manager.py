"""Non-throwing IBKR Gateway lifecycle manager for daemon mode.

Starts, monitors, and restarts the gateway. Never raises -- returns
status that the daemon uses to gate live pod execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Re-use existing helpers from portfolio_runner (import at call time to avoid
# circular imports since portfolio_runner imports many heavy modules).
MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_PORT = 5001


@dataclass(slots=True)
class GatewayStatus:
    available: bool
    authenticated: bool
    base_url: str | None
    message: str


class GatewayManager:
    """Non-throwing IBKR gateway lifecycle manager.

    All public methods return status objects rather than raising exceptions.
    This ensures the daemon never crashes due to gateway issues.
    """

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.base_url: str | None = None
        self.available = False
        self.authenticated = False
        self.consecutive_failures = 0

    def start(self) -> GatewayStatus:
        """Attempt to find or start the IBKR gateway.

        Returns current status without raising.
        """
        try:
            from src.services.portfolio_runner import _find_running_gateway, _start_ibkr_gateway

            # Check if already running
            found_url, is_authed = _find_running_gateway(timeout=3.0)
            if found_url:
                self.base_url = found_url
                self.available = True
                self.authenticated = is_authed
                self.consecutive_failures = 0
                if is_authed:
                    logger.info("IBKR gateway found and authenticated at %s", found_url)
                    return self._status("Gateway running and authenticated")
                else:
                    logger.warning("IBKR gateway found at %s but NOT authenticated. Visit %s to log in.", found_url, found_url)
                    return self._status(f"Gateway running but not authenticated. Visit {found_url} to log in.")

            # Not running -- attempt to start
            logger.info("IBKR gateway not found. Attempting to start on port %d...", self.port)
            started = _start_ibkr_gateway(self.port)
            if started:
                self.base_url = f"https://localhost:{self.port}"
                self.available = True
                self.authenticated = False
                self.consecutive_failures = 0
                logger.warning("IBKR gateway started but needs authentication. Visit %s to log in.", self.base_url)
                return self._status(f"Gateway started. Visit {self.base_url} to log in.")
            else:
                self.available = False
                self.authenticated = False
                logger.error("Failed to start IBKR gateway on port %d", self.port)
                return self._status("Failed to start gateway")

        except Exception as e:
            self.available = False
            self.authenticated = False
            logger.error("Error during gateway start: %s", e, exc_info=True)
            return self._status(f"Error: {e}")

    def check_health(self) -> GatewayStatus:
        """Check gateway health. Auto-restart after consecutive failures.

        Called periodically by the daemon scheduler.
        """
        try:
            from src.services.portfolio_runner import _check_ibkr_gateway

            if not self.base_url:
                self.available = False
                self.authenticated = False
                return self._status("No gateway URL configured")

            is_running, is_authed = _check_ibkr_gateway(self.base_url, timeout=3.0)

            if is_running:
                self.available = True
                self.authenticated = is_authed
                self.consecutive_failures = 0
                if not is_authed:
                    logger.warning("IBKR gateway running but not authenticated. Visit %s", self.base_url)
                return self._status("Healthy" if is_authed else f"Not authenticated. Visit {self.base_url}")

            # Gateway not responding
            self.consecutive_failures += 1
            logger.warning("IBKR gateway health check failed (%d/%d)", self.consecutive_failures, MAX_CONSECUTIVE_FAILURES)

            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error("IBKR gateway down for %d consecutive checks. Attempting restart...", self.consecutive_failures)
                return self._restart()

            self.available = False
            self.authenticated = False
            return self._status(f"Gateway not responding ({self.consecutive_failures}/{MAX_CONSECUTIVE_FAILURES} failures)")

        except Exception as e:
            self.available = False
            self.authenticated = False
            logger.error("Error during health check: %s", e, exc_info=True)
            return self._status(f"Health check error: {e}")

    def is_authenticated(self) -> bool:
        """Return True if gateway is available and authenticated."""
        return self.available and self.authenticated

    def get_status(self) -> GatewayStatus:
        """Return current status without performing any checks."""
        return self._status("Current state")

    def _restart(self) -> GatewayStatus:
        """Attempt to restart the gateway after consecutive failures."""
        try:
            from src.services.portfolio_runner import _start_ibkr_gateway

            logger.info("Restarting IBKR gateway on port %d...", self.port)
            started = _start_ibkr_gateway(self.port)
            if started:
                self.base_url = f"https://localhost:{self.port}"
                self.available = True
                self.authenticated = False
                self.consecutive_failures = 0
                logger.warning("Gateway restarted. Needs authentication at %s", self.base_url)
                return self._status(f"Gateway restarted. Visit {self.base_url} to authenticate.")
            else:
                self.available = False
                self.authenticated = False
                logger.error("Gateway restart failed")
                return self._status("Gateway restart failed")

        except Exception as e:
            self.available = False
            self.authenticated = False
            logger.error("Error during gateway restart: %s", e, exc_info=True)
            return self._status(f"Restart error: {e}")

    def _status(self, message: str) -> GatewayStatus:
        return GatewayStatus(
            available=self.available,
            authenticated=self.authenticated,
            base_url=self.base_url,
            message=message,
        )
