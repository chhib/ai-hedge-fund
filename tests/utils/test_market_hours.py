"""Tests for market hours utilities and schedule presets."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.utils.market_hours import (
    EXCHANGE_SESSIONS,
    SCHEDULE_PRESETS,
    is_market_open,
    market_status_label,
    resolve_schedule,
)


class TestIsMarketOpen:
    """Test market open/close detection."""

    def test_sfb_open_weekday_midday(self):
        # Wednesday 12:00 Stockholm time -> SFB open (09:00-17:30)
        dt = datetime(2026, 3, 25, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is True

    def test_sfb_closed_weekend(self):
        # Saturday 12:00 -> closed
        dt = datetime(2026, 3, 28, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is False

    def test_sfb_closed_before_open(self):
        dt = datetime(2026, 3, 25, 8, 30, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is False

    def test_sfb_closed_after_close(self):
        dt = datetime(2026, 3, 25, 18, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is False

    def test_nyse_open_weekday(self):
        dt = datetime(2026, 3, 25, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        assert is_market_open("NYSE", dt) is True

    def test_nyse_closed_early_morning(self):
        dt = datetime(2026, 3, 25, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert is_market_open("NYSE", dt) is False

    def test_smart_always_open(self):
        assert is_market_open("SMART") is True

    def test_none_always_open(self):
        assert is_market_open(None) is True

    def test_unknown_exchange_assumes_open(self):
        assert is_market_open("UNKNOWN_EXCHANGE") is True

    def test_all_18_exchanges_defined(self):
        assert len(EXCHANGE_SESSIONS) == 18

    def test_dot_format_exchange(self):
        dt = datetime(2026, 3, 25, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB.SE", dt) is True

    def test_sfb_open_at_exact_open_time(self):
        dt = datetime(2026, 3, 25, 9, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is True

    def test_sfb_open_at_exact_close_time(self):
        dt = datetime(2026, 3, 25, 17, 30, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is True

    def test_sunday_closed(self):
        dt = datetime(2026, 3, 29, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        assert is_market_open("SFB", dt) is False


class TestMarketStatusLabel:
    def test_open_label(self):
        dt = datetime(2026, 3, 25, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        # We can't easily inject time into label, but we can test format
        label = market_status_label("SFB")
        assert label.startswith("SFB")
        assert "OPEN" in label or "CLOSED" in label


class TestSchedulePresets:
    def test_all_presets_have_required_keys(self):
        for name, preset in SCHEDULE_PRESETS.items():
            assert "analysis" in preset, f"Preset '{name}' missing 'analysis'"
            assert "execution" in preset, f"Preset '{name}' missing 'execution'"
            assert "timezone" in preset, f"Preset '{name}' missing 'timezone'"
            assert "exchanges" in preset, f"Preset '{name}' missing 'exchanges'"

    def test_nordic_morning_preset(self):
        preset = SCHEDULE_PRESETS["nordic-morning"]
        assert preset["analysis"]["hour"] == 8
        assert preset["execution"]["hour"] == 10
        assert preset["timezone"] == "Europe/Stockholm"
        assert "SFB" in preset["exchanges"]

    def test_us_morning_preset(self):
        preset = SCHEDULE_PRESETS["us-morning"]
        assert preset["analysis"]["hour"] == 9
        assert preset["execution"]["hour"] == 10
        assert preset["execution"]["minute"] == 30
        assert preset["timezone"] == "America/New_York"
        assert "NYSE" in preset["exchanges"]


class TestResolveSchedule:
    def test_resolve_known_preset(self):
        result = resolve_schedule("nordic-morning")
        assert result["timezone"] == "Europe/Stockholm"
        assert result["analysis"]["hour"] == 8

    def test_resolve_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown schedule preset"):
            resolve_schedule("nonexistent-preset")

    def test_resolve_raw_cron_expression(self):
        result = resolve_schedule("0 8 * * 1-5")
        assert result["analysis"]["minute"] == "0"
        assert result["analysis"]["hour"] == "8"
        assert result["analysis"]["day_of_week"] == "1-5"

    def test_resolve_raw_cron_execution_offset(self):
        result = resolve_schedule("0 8 * * 1-5")
        assert result["execution"]["hour"] == "9"  # 8 + 1

    def test_resolve_raw_cron_invalid_fields(self):
        with pytest.raises(ValueError, match="expected 5 fields"):
            resolve_schedule("0 8 *")

    def test_resolve_raw_cron_with_asterisks(self):
        result = resolve_schedule("30 * * * *")
        assert result["analysis"]["minute"] == "30"
        assert "hour" not in result["analysis"]
