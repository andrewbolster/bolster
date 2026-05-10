"""Tests for bolster.utils.dt datetime rounding utilities."""

from datetime import date, datetime, timezone

import pytest

from bolster.utils.dt import round_to_month, round_to_week, utc_midnight_on


class TestRoundToWeek:
    def test_midweek_datetime(self):
        assert round_to_week(datetime(2018, 8, 9, 12, 1)) == date(2018, 8, 6)

    def test_midweek_date(self):
        assert round_to_week(date(2018, 8, 9)) == date(2018, 8, 6)

    def test_monday_is_unchanged(self):
        assert round_to_week(date(2024, 3, 11)) == date(2024, 3, 11)

    def test_sunday_rounds_back(self):
        assert round_to_week(date(2024, 3, 17)) == date(2024, 3, 11)


class TestRoundToMonth:
    def test_midmonth_datetime(self):
        assert round_to_month(datetime(2018, 8, 9, 12, 1)) == date(2018, 8, 1)

    def test_midmonth_date(self):
        assert round_to_month(date(2018, 8, 9)) == date(2018, 8, 1)

    def test_first_of_month_is_unchanged(self):
        assert round_to_month(date(2024, 3, 1)) == date(2024, 3, 1)

    def test_last_day_of_month(self):
        assert round_to_month(date(2024, 3, 31)) == date(2024, 3, 1)


class TestUtcMidnightOn:
    def test_naive_datetime(self):
        result = utc_midnight_on(datetime(2018, 9, 1, 12, 12))
        assert result == datetime(2018, 9, 1, 0, 0, tzinfo=timezone.utc)

    def test_strips_time_component(self):
        result = utc_midnight_on(datetime(2024, 6, 15, 23, 59, 59))
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0

    def test_result_is_utc_aware(self):
        result = utc_midnight_on(datetime(2024, 1, 1))
        assert result.tzinfo == timezone.utc

    def test_preserves_date(self):
        result = utc_midnight_on(datetime(2024, 6, 15, 23, 59))
        assert result.date() == date(2024, 6, 15)
