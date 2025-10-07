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
            refresh_per_second=10,
            transient=False
        )
        self.started = False
        self.update_handlers: List[Callable[[str, Optional[str], str], None]] = []
        self.prefetch_progress = {"completed": 0, "total": 0, "current_ticker": None, "cached": 0, "status": "pending"}

    def register_handler(self, handler: Callable[[str, Optional[str], str], None]):
        self.update_handlers.append(handler)
        return handler

    def unregister_handler(self, handler: Callable[[str, Optional[str], str], None]):
        if handler in self.update_handlers:
            self.update_handlers.remove(handler)

    def initialize_agents(self, agent_names: List[str], total_tickers: int):
        for agent_name in agent_names:
            self.agent_progress[agent_name] = {"completed": 0, "total": total_tickers}
            self.agent_status[agent_name] = {"status": f"Pending {total_tickers} tickers.", "ticker": ""}
        self.prefetch_progress["total"] = total_tickers

    def start(self):
        if not self.started:
            self.live.start()
            self.started = True

    def stop(self):
        if self.started:
            self.live.stop()
            self.started = False

    def update_prefetch_status(self, completed: int, total: int, ticker: str, cached: int = 0, status: str = "fetching"):
        """
        Update prefetch progress.

        Args:
            completed: Number of API tasks completed
            total: Total number of API tasks
            ticker: Current ticker being processed
            cached: Number of tickers loaded from cache
            status: Status of prefetch ('pending', 'fetching', 'done')
        """
        self.prefetch_progress["completed"] = completed
        self.prefetch_progress["total"] = total
        self.prefetch_progress["current_ticker"] = ticker
        self.prefetch_progress["cached"] = cached
        self.prefetch_progress["status"] = status
        self._refresh_display()
        sys.stderr.flush()

    def update_status(self, agent_name: str, ticker: Optional[str] = None, status: str = "", analysis: Optional[str] = None, next_ticker: Optional[str] = None):
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {"status": "", "ticker": None}

        if ticker:
            self.agent_status[agent_name]["ticker"] = ticker
        if status:
            self.agent_status[agent_name]["status"] = status
        if analysis:
            self.agent_status[agent_name]["analysis"] = analysis

        if agent_name in self.agent_progress:
            self.agent_progress[agent_name]["current_ticker"] = ticker
            self.agent_progress[agent_name]["next_ticker"] = next_ticker
            if status and "Done" in status:
                # Check if we are incrementing for a ticker, not a general Done
                if ticker:
                    # Avoid double counting
                    if self.agent_progress[agent_name].get("last_completed_ticker") != ticker:
                        self.agent_progress[agent_name]["completed"] += 1
                        self.agent_progress[agent_name]["last_completed_ticker"] = ticker

        timestamp = datetime.now(timezone.utc).isoformat()
        self.agent_status[agent_name]["timestamp"] = timestamp

        for handler in self.update_handlers:
            handler(agent_name, ticker, status, analysis, timestamp)

        self._refresh_display()
        sys.stderr.flush()

    def get_all_status(self):
        return {agent_name: {"ticker": info["ticker"], "status": info["status"], "display_name": self._get_display_name(agent_name)} for agent_name, info in self.agent_status.items()}

    def _get_display_name(self, agent_name: str) -> str:
        return agent_name.replace("_agent", "").replace("_", " ").title()

    def _refresh_display(self):
        self.table.columns.clear()
        self.table.add_column(width=100)

        # Prefetching progress
        status = self.prefetch_progress.get("status", "pending")
        cached = self.prefetch_progress.get("cached", 0)
        completed = self.prefetch_progress["completed"]
        total = self.prefetch_progress["total"]
        ticker = self.prefetch_progress["current_ticker"]

        # Show prefetch status
        if status == "done" and total == 0 and cached > 0:
            # All tickers from cache
            progress_text = Text()
            progress_text.append("✓ ", style=Style(color="green", bold=True))
            progress_text.append(f"Loaded {cached} ticker(s) from cache ", style=Style(color="green"))
            progress_text.append("(today's data)", style=Style(color="white", dim=True))
            self.table.add_row(progress_text)
        elif status == "fetching" or (total > 0 and completed < total):
            # Still fetching from API
            bar_length = 20
            # If we have cached items and total represents initial ticker count (not API tasks yet),
            # show cached progress in the bar
            if cached > 0 and completed == 0 and total > 0:
                # Before API tasks start reporting, show cache progress
                filled = int(bar_length * cached / total) if total > 0 else 0
            else:
                # Normal API task progress
                filled = int(bar_length * completed / total) if total > 0 else 0
            empty = bar_length - filled
            bar = "█" * filled + "░" * empty

            progress_text = Text()
            progress_text.append("⋯ ", style=Style(color="yellow"))
            progress_text.append(f"Fetching {total} ticker KPIs", style=Style(color="yellow"))
            if cached > 0:
                progress_text.append(f" ({cached} cached) ", style=Style(color="white", dim=True))

            progress_text.append(f" [{bar}] ")
            if ticker:
                progress_text.append(f"[{ticker}] ", style=Style(color="white"))

            if cached > 0 and completed == 0 and total > 0:
                percentage = (cached / total) * 100
            else:
                percentage = (completed / total) * 100 if total > 0 else 0
            progress_text.append(f"{percentage:.0f}%")

            self.table.add_row(progress_text)
        elif status == "done" and total > 0 and completed >= total:
            # Just completed fetching
            progress_text = Text()
            progress_text.append("✓ ", style=Style(color="green", bold=True))
            if cached > 0:
                progress_text.append(f"Fetched {total} ticker(s), {cached} from cache", style=Style(color="green"))
            else:
                progress_text.append(f"Fetched {total} ticker(s)", style=Style(color="green"))
            self.table.add_row(progress_text)

        # Agent progress
        def sort_key(item):
            agent_name = item[0]
            if "risk_management" in agent_name: return (2, agent_name)
            if "portfolio_management" in agent_name: return (3, agent_name)
            return (1, agent_name)

        for agent_name, progress_info in sorted(self.agent_progress.items(), key=sort_key):
            info = self.agent_status.get(agent_name, {})
            status = info.get("status", f"Pending {progress_info.get('total', 0)} tickers.")
            ticker = info.get("ticker", "")
            agent_display = self._get_display_name(agent_name)

            completed = progress_info.get("completed", 0)
            total = progress_info.get("total", 0)
            next_ticker = progress_info.get("next_ticker")

            all_done = completed >= total and total > 0
            is_working = ticker and not all_done and "Done" not in status

            symbol, style = ("✓", Style(color="green", bold=True)) if all_done else (("⋯", Style(color="yellow", bold=True)) if is_working else ("⋯", Style(color="white")))

            status_text = Text()
            status_text.append(f"{symbol} ", style=style)
            status_text.append(f"{agent_display:<22}", style=Style(bold=True))

            if total > 0:
                bar_length = 20
                filled = int(bar_length * min(completed, total) / total)
                empty = bar_length - filled
                bar = "█" * filled + "░" * empty
                status_text.append(f"[{bar}] ", style=style)

            if ticker:
                status_text.append(f"[{ticker}] ", style=Style(color="white"))

            if all_done:
                status_text.append("Done", style=style)
            elif "Done" in status and next_ticker:
                status_text.append(f"Done. Next up {next_ticker}", style=style)
            else:
                status_text.append(status, style=style)

            self.table.add_row(status_text)


# Create a global instance
progress = AgentProgress()
