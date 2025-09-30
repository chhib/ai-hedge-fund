from datetime import datetime, timezone
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.style import Style
from rich.text import Text
from typing import Dict, Optional, Callable, List
import sys

# Use stderr for console output to avoid stdout buffering issues
console = Console(file=sys.stderr, force_terminal=True)


class AgentProgress:
    """Manages progress tracking for multiple agents."""

    def __init__(self):
        self.agent_status: Dict[str, Dict[str, str]] = {}
        self.agent_progress: Dict[str, Dict[str, int]] = {}  # Track completed/total per agent
        self.table = Table(show_header=False, box=None, padding=(0, 1))
        self.live = Live(
            self.table,
            console=console,
            refresh_per_second=10,  # Increased refresh rate
            transient=False  # Keep the display after stopping
        )
        self.started = False
        self.update_handlers: List[Callable[[str, Optional[str], str], None]] = []

    def register_handler(self, handler: Callable[[str, Optional[str], str], None]):
        """Register a handler to be called when agent status updates."""
        self.update_handlers.append(handler)
        return handler  # Return handler to support use as decorator

    def unregister_handler(self, handler: Callable[[str, Optional[str], str], None]):
        """Unregister a previously registered handler."""
        if handler in self.update_handlers:
            self.update_handlers.remove(handler)

    def initialize_agents(self, agent_names: List[str], total_tickers: int):
        """Initialize progress tracking for all agents."""
        for agent_name in agent_names:
            self.agent_progress[agent_name] = {
                "completed": 0,
                "total": total_tickers,
                "current_ticker": None,
                "next_ticker": None
            }
            self.agent_status[agent_name] = {
                "status": "Pending",
                "ticker": None
            }

    def start(self):
        """Start the progress display."""
        if not self.started:
            self.live.start()
            self.started = True

    def stop(self):
        """Stop the progress display."""
        if self.started:
            self.live.stop()
            self.started = False

    def update_status(self, agent_name: str, ticker: Optional[str] = None, status: str = "", analysis: Optional[str] = None, next_ticker: Optional[str] = None):
        """Update the status of an agent."""
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {"status": "", "ticker": None}

        if ticker:
            self.agent_status[agent_name]["ticker"] = ticker
        if status:
            self.agent_status[agent_name]["status"] = status
        if analysis:
            self.agent_status[agent_name]["analysis"] = analysis

        # Update progress tracking
        if agent_name in self.agent_progress:
            self.agent_progress[agent_name]["current_ticker"] = ticker
            self.agent_progress[agent_name]["next_ticker"] = next_ticker
            if status == "Done":
                self.agent_progress[agent_name]["completed"] += 1

        # Set the timestamp as UTC datetime
        timestamp = datetime.now(timezone.utc).isoformat()
        self.agent_status[agent_name]["timestamp"] = timestamp

        # Notify all registered handlers
        for handler in self.update_handlers:
            handler(agent_name, ticker, status, analysis, timestamp)

        self._refresh_display()

        # Force flush to ensure immediate display
        sys.stderr.flush()

    def get_all_status(self):
        """Get the current status of all agents as a dictionary."""
        return {agent_name: {"ticker": info["ticker"], "status": info["status"], "display_name": self._get_display_name(agent_name)} for agent_name, info in self.agent_status.items()}

    def _get_display_name(self, agent_name: str) -> str:
        """Convert agent_name to a display-friendly format."""
        return agent_name.replace("_agent", "").replace("_", " ").title()

    def _refresh_display(self):
        """Refresh the progress display with per-analyst progress bars."""
        self.table.columns.clear()
        self.table.add_column(width=100)

        # Sort agents with Risk Management and Portfolio Management at the bottom
        def sort_key(item):
            agent_name = item[0]
            if "risk_management" in agent_name:
                return (2, agent_name)
            elif "portfolio_management" in agent_name:
                return (3, agent_name)
            else:
                return (1, agent_name)

        for agent_name, info in sorted(self.agent_status.items(), key=sort_key):
            status = info["status"]
            ticker = info["ticker"]
            agent_display = self._get_display_name(agent_name)

            # Get progress info if available
            progress_info = self.agent_progress.get(agent_name, {})
            completed = progress_info.get("completed", 0)
            total = progress_info.get("total", 0)
            next_ticker = progress_info.get("next_ticker")

            # Determine if this analyst is done with all tickers
            all_done = completed >= total and total > 0

            # Create the status text with appropriate styling
            if all_done:
                style = Style(color="green", bold=True)
                symbol = "✓"
            elif status.lower() == "error":
                style = Style(color="red", bold=True)
                symbol = "✗"
            else:
                style = Style(color="#FFA500")  # Orange
                symbol = "⋯"

            status_text = Text()
            status_text.append(f"{symbol} ", style=style)
            status_text.append(f"{agent_display:<22}", style=Style(bold=True))

            # Add progress bar
            if total > 0:
                bar_length = 20
                filled = int(bar_length * completed / total)
                bar = "█" * filled + "░" * (bar_length - filled)
                status_text.append(f"[{bar}] ", style=style)

            # Add current ticker with color: green if done, orange if working
            if ticker:
                ticker_done = status == "Done" or all_done
                ticker_style = Style(color="green") if ticker_done else Style(color="#FFA500")
                status_text.append(f"[{ticker}] ", style=ticker_style)

            # Add status message
            if all_done:
                status_text.append("Done", style=style)
            elif status == "Done" and next_ticker:
                status_text.append(f"Next up {next_ticker}", style=style)
            else:
                status_text.append(status, style=style)

            self.table.add_row(status_text)


# Create a global instance
progress = AgentProgress()
