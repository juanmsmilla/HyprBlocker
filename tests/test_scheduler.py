"""Tests for block schedule logic: day/time parsing and active-block evaluation."""

from datetime import datetime
from datetime import time as dt_time
from types import SimpleNamespace

import pytest

from daemon.scheduler import BlockChecker


@pytest.fixture
def checker():
    # session_factory is only used by async DB methods, not the pure logic under test
    return BlockChecker(session_factory=None)


def make_block(**overrides):
    """Build a minimal object with the Block attributes the scheduler reads."""
    defaults = {
        "id": 1,
        "name": "Test Block",
        "enabled": True,
        "block_mode": "always",
        "block_days_of_week": None,
        "block_start_time": None,
        "block_end_time": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# Monday 2026-07-06 at 12:00
MONDAY_NOON = datetime(2026, 7, 6, 12, 0)
# Saturday 2026-07-11 at 12:00
SATURDAY_NOON = datetime(2026, 7, 11, 12, 0)


class TestParseDaysOfWeek:
    def test_json_array(self, checker):
        assert checker._parse_days_of_week("[0, 1, 2]") == [0, 1, 2]

    def test_comma_separated(self, checker):
        assert checker._parse_days_of_week("0,1,2") == [0, 1, 2]

    def test_empty_string(self, checker):
        assert checker._parse_days_of_week("") == []

    def test_none(self, checker):
        assert checker._parse_days_of_week(None) == []

    def test_invalid_input_returns_empty(self, checker):
        assert checker._parse_days_of_week("monday,tuesday") == []


class TestParseTime:
    def test_parses_hour_and_minute(self, checker):
        assert checker._parse_time("09:30") == dt_time(9, 30)

    def test_parses_midnight(self, checker):
        assert checker._parse_time("00:00") == dt_time(0, 0)


class TestIsTimeInRange:
    def test_inside_range(self, checker):
        assert checker._is_time_in_range(None, "09:00", "17:00", MONDAY_NOON)

    def test_outside_range(self, checker):
        evening = MONDAY_NOON.replace(hour=20)
        assert not checker._is_time_in_range(None, "09:00", "17:00", evening)

    def test_range_boundaries_inclusive(self, checker):
        start = MONDAY_NOON.replace(hour=9, minute=0)
        end = MONDAY_NOON.replace(hour=17, minute=0)
        assert checker._is_time_in_range(None, "09:00", "17:00", start)
        assert checker._is_time_in_range(None, "09:00", "17:00", end)

    def test_overnight_range_spans_midnight(self, checker):
        late_night = MONDAY_NOON.replace(hour=23)
        early_morning = MONDAY_NOON.replace(hour=3)
        midday = MONDAY_NOON
        assert checker._is_time_in_range(None, "22:00", "06:00", late_night)
        assert checker._is_time_in_range(None, "22:00", "06:00", early_morning)
        assert not checker._is_time_in_range(None, "22:00", "06:00", midday)

    def test_day_of_week_restriction(self, checker):
        weekdays = "[0,1,2,3,4]"
        assert checker._is_time_in_range(weekdays, "09:00", "17:00", MONDAY_NOON)
        assert not checker._is_time_in_range(weekdays, "09:00", "17:00", SATURDAY_NOON)

    def test_no_time_range_means_all_day(self, checker):
        assert checker._is_time_in_range("[0]", None, None, MONDAY_NOON)
        assert not checker._is_time_in_range("[0]", None, None, SATURDAY_NOON)


class TestIsBlockActive:
    def test_disabled_block_never_active(self, checker):
        block = make_block(enabled=False, block_mode="always")
        assert not checker._is_block_active(block, MONDAY_NOON)

    def test_disabled_mode_never_active(self, checker):
        block = make_block(block_mode="disabled")
        assert not checker._is_block_active(block, MONDAY_NOON)

    def test_always_mode_active(self, checker):
        block = make_block(block_mode="always")
        assert checker._is_block_active(block, MONDAY_NOON)

    def test_time_range_mode_respects_schedule(self, checker):
        block = make_block(
            block_mode="time_range",
            block_days_of_week="[0,1,2,3,4]",
            block_start_time="09:00",
            block_end_time="17:00",
        )
        assert checker._is_block_active(block, MONDAY_NOON)
        assert not checker._is_block_active(block, SATURDAY_NOON)
        assert not checker._is_block_active(block, MONDAY_NOON.replace(hour=20))

    def test_unknown_mode_fails_closed_to_inactive(self, checker):
        block = make_block(block_mode="bogus")
        assert not checker._is_block_active(block, MONDAY_NOON)
