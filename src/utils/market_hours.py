"""Market hours utilities: exchange sessions, open/close checks, schedule presets."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo


# (timezone, open_hour, open_min, close_hour, close_min)
EXCHANGE_SESSIONS: Dict[str, Tuple[str, int, int, int, int]] = {
    "SFB": ("Europe/Stockholm", 9, 0, 17, 30),
    "CPH": ("Europe/Copenhagen", 9, 0, 17, 0),
    "OSE": ("Europe/Oslo", 9, 0, 16, 20),
    "HEL": ("Europe/Helsinki", 10, 0, 18, 30),
    "HEX": ("Europe/Helsinki", 10, 0, 18, 30),
    "XETRA": ("Europe/Berlin", 9, 0, 17, 30),
    "FWB": ("Europe/Berlin", 8, 0, 22, 0),
    "FWB2": ("Europe/Berlin", 8, 0, 22, 0),
    "LSE": ("Europe/London", 8, 0, 16, 30),
    "AEB": ("Europe/Amsterdam", 9, 0, 17, 30),
    "NASDAQ": ("America/New_York", 9, 30, 16, 0),
    "NYSE": ("America/New_York", 9, 30, 16, 0),
    "AMEX": ("America/New_York", 9, 30, 16, 0),
    "ARCA": ("America/New_York", 9, 30, 16, 0),
    "TSX": ("America/Toronto", 9, 30, 16, 0),
    "TSXV": ("America/Toronto", 9, 30, 16, 0),
    "PINK": ("America/New_York", 9, 30, 16, 0),
    "BATS": ("America/New_York", 9, 30, 16, 0),
}


def is_market_open(exchange: str | None, now: datetime | None = None) -> bool:
    """Check if an exchange is currently open for regular trading."""
    if not exchange or exchange.upper() == "SMART":
        return True  # SMART routing -- assume open, let IBKR decide
    key = exchange.upper().split(".")[0]
    session = EXCHANGE_SESSIONS.get(key)
    if session is None:
        return True  # Unknown exchange -- assume open
    tz_name, oh, om, ch, cm = session
    tz = ZoneInfo(tz_name)
    local_now = (now or datetime.now(tz)).astimezone(tz)
    if local_now.weekday() >= 5:
        return False
    open_time = local_now.replace(hour=oh, minute=om, second=0, microsecond=0)
    close_time = local_now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return open_time <= local_now <= close_time


def market_status_label(exchange: str | None) -> str:
    """Return a human-readable market status string like 'OSE OPEN' or 'NYSE CLOSED'."""
    name = (exchange or "SMART").upper().split(".")[0]
    if is_market_open(exchange):
        return f"{name} OPEN"
    return f"{name} CLOSED"


def any_market_open(exchanges: list[str], now: datetime | None = None) -> bool:
    """Return True if at least one of the given exchanges is open."""
    return any(is_market_open(ex, now) for ex in exchanges)


# ── Schedule Presets ──
# Each preset maps to (analysis_cron_kwargs, execution_cron_kwargs, timezone).
# Cron kwargs are passed to APScheduler's CronTrigger.
# Analysis runs ~1hr before market open; execution runs ~1hr after open.

SCHEDULE_PRESETS: Dict[str, Dict] = {
    "nordic-morning": {
        "analysis": {"hour": 8, "minute": 0, "day_of_week": "mon-fri"},
        "execution": {"hour": 10, "minute": 0, "day_of_week": "mon-fri"},
        "timezone": "Europe/Stockholm",
        "description": "Nordic markets: analyze 08:00, execute 10:00 CET",
        "exchanges": ["SFB", "CPH", "OSE", "HEL"],
    },
    "us-morning": {
        "analysis": {"hour": 9, "minute": 0, "day_of_week": "mon-fri"},
        "execution": {"hour": 10, "minute": 30, "day_of_week": "mon-fri"},
        "timezone": "America/New_York",
        "description": "US markets: analyze 09:00, execute 10:30 ET",
        "exchanges": ["NYSE", "NASDAQ", "AMEX", "ARCA"],
    },
    "europe-morning": {
        "analysis": {"hour": 8, "minute": 0, "day_of_week": "mon-fri"},
        "execution": {"hour": 10, "minute": 0, "day_of_week": "mon-fri"},
        "timezone": "Europe/Berlin",
        "description": "European markets: analyze 08:00, execute 10:00 CET",
        "exchanges": ["XETRA", "FWB", "LSE", "AEB"],
    },
    "weekly-nordic": {
        "analysis": {"hour": 8, "minute": 0, "day_of_week": "mon"},
        "execution": {"hour": 10, "minute": 0, "day_of_week": "mon"},
        "timezone": "Europe/Stockholm",
        "description": "Nordic markets: Monday only, analyze 08:00, execute 10:00 CET",
        "exchanges": ["SFB", "CPH", "OSE", "HEL"],
    },
}

VALID_PRESETS = set(SCHEDULE_PRESETS.keys())


def resolve_schedule(schedule: str) -> Dict:
    """Resolve a schedule string to a preset dict or parse a raw cron expression.

    Returns a dict with 'analysis', 'execution', 'timezone', and 'exchanges' keys.
    For raw cron: analysis = cron as-is, execution = 1hr later (best effort).
    """
    if schedule in SCHEDULE_PRESETS:
        return SCHEDULE_PRESETS[schedule]

    # Detect raw cron expression (contains spaces or asterisks)
    if " " in schedule or "*" in schedule:
        return _parse_raw_cron(schedule)

    raise ValueError(f"Unknown schedule preset '{schedule}'. Available: {sorted(VALID_PRESETS)}")


def _parse_raw_cron(cron_expr: str) -> Dict:
    """Parse a raw 5-field cron expression into APScheduler-compatible kwargs.

    Format: minute hour day_of_month month day_of_week
    Example: '0 8 * * 1-5' -> weekdays at 08:00
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression '{cron_expr}': expected 5 fields (minute hour dom month dow)")

    minute, hour, dom, month, dow = parts
    analysis_kwargs = {}
    if minute != "*":
        analysis_kwargs["minute"] = minute
    if hour != "*":
        analysis_kwargs["hour"] = hour
    if dom != "*":
        analysis_kwargs["day"] = dom
    if month != "*":
        analysis_kwargs["month"] = month
    if dow != "*":
        analysis_kwargs["day_of_week"] = dow

    # Execution: 1hr after analysis (best effort -- shift hour by 1)
    execution_kwargs = dict(analysis_kwargs)
    if "hour" in execution_kwargs:
        try:
            h = int(execution_kwargs["hour"])
            execution_kwargs["hour"] = str(h + 1)
        except ValueError:
            pass  # Complex hour spec (e.g., "8,14") -- keep as-is

    return {
        "analysis": analysis_kwargs,
        "execution": execution_kwargs,
        "timezone": "Europe/Stockholm",  # Default for raw cron
        "description": f"Custom cron: {cron_expr}",
        "exchanges": list(EXCHANGE_SESSIONS.keys()),  # Check all exchanges
    }
