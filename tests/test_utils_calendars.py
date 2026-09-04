"""Unit tests for bolster.utils.calendars.

These tests use mocked HTTP responses and in-memory ICS text — no real
network calls, matching test_utils_datatables.py's convention for generic
(non-data-source) utilities.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar as ICalendar

from bolster.utils.calendars import (
    BUSY,
    FREE,
    TENTATIVE,
    Interval,
    add_free_gaps,
    collect_intervals,
    event_severity,
    fetch_ics,
    format_timeline,
    get_merged_availability,
    merge_timeline,
)

EMPTY_ICAL = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"

BUSY_ICAL = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:1\r\nDTSTART:20241202T100000Z\r\nDTEND:20241202T110000Z\r\n"
    "SUMMARY:Team Meeting\r\nEND:VEVENT\r\n"
    "END:VCALENDAR"
)


def _vevent(*extra_lines: str):
    """Parse a minimal VEVENT with the given extra property lines, for event_severity tests."""
    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:1",
            "DTSTART:20241202T100000Z",
            "DTEND:20241202T110000Z",
            "SUMMARY:Event",
            *extra_lines,
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return ICalendar.from_ical(body).walk("VEVENT")[0]


def _make_response(content: bytes = b"", status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.content = content
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    return mock


class TestEventSeverity:
    def test_transparent_is_free(self):
        assert event_severity(_vevent("TRANSP:TRANSPARENT")) == FREE

    def test_ms_busystatus_free(self):
        assert event_severity(_vevent("X-MICROSOFT-CDO-BUSYSTATUS:FREE")) == FREE

    def test_ms_busystatus_tentative(self):
        assert event_severity(_vevent("X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE")) == TENTATIVE

    def test_ms_busystatus_oof_is_busy(self):
        assert event_severity(_vevent("X-MICROSOFT-CDO-BUSYSTATUS:OOF")) == BUSY

    def test_status_tentative(self):
        assert event_severity(_vevent("STATUS:TENTATIVE")) == TENTATIVE

    def test_status_cancelled_is_free(self):
        assert event_severity(_vevent("STATUS:CANCELLED")) == FREE

    def test_partstat_declined_is_free(self):
        assert event_severity(_vevent("ATTENDEE;PARTSTAT=DECLINED:mailto:test@example.com")) == FREE

    def test_partstat_tentative(self):
        assert event_severity(_vevent("ATTENDEE;PARTSTAT=TENTATIVE:mailto:test@example.com")) == TENTATIVE

    def test_defaults_to_busy(self):
        assert event_severity(_vevent()) == BUSY


class TestFetchIcs:
    def test_fetch_success(self):
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=BUSY_ICAL.encode())
            cal = fetch_ics("work", "https://example.com/work.ics")
            assert cal is not None
            assert len(cal.walk("VEVENT")) == 1

    def test_fetch_http_error_returns_none(self):
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.side_effect = ConnectionError("network unreachable")
            assert fetch_ics("work", "https://example.com/work.ics") is None

    def test_fetch_raise_for_status_error_returns_none(self):
        response = _make_response(content=b"not found")
        response.raise_for_status.side_effect = RuntimeError("404")
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = response
            assert fetch_ics("work", "https://example.com/work.ics") is None


class TestCollectIntervals:
    def test_collects_busy_events_and_skips_free(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 1, tzinfo=tz)
        window_end = datetime(2024, 12, 8, tzinfo=tz)
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=BUSY_ICAL.encode())
            intervals = collect_intervals(
                [{"name": "work", "url": "https://example.com/work.ics"}], window_start, window_end, tz
            )
        assert len(intervals) == 1
        assert intervals[0].calendar == "work"
        assert intervals[0].summary == "Team Meeting"
        assert intervals[0].severity == BUSY

    def test_one_bad_calendar_does_not_break_the_rest(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 1, tzinfo=tz)
        window_end = datetime(2024, 12, 8, tzinfo=tz)

        def fake_get(url, **kwargs):
            if "bad" in url:
                raise ConnectionError("nope")
            return _make_response(content=BUSY_ICAL.encode())

        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.side_effect = fake_get
            intervals = collect_intervals(
                [
                    {"name": "bad", "url": "https://example.com/bad.ics"},
                    {"name": "work", "url": "https://example.com/work.ics"},
                ],
                window_start,
                window_end,
                tz,
            )
        assert len(intervals) == 1
        assert intervals[0].calendar == "work"

    def test_empty_calendar_yields_no_intervals(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 1, tzinfo=tz)
        window_end = datetime(2024, 12, 8, tzinfo=tz)
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=EMPTY_ICAL.encode())
            intervals = collect_intervals(
                [{"name": "work", "url": "https://example.com/work.ics"}], window_start, window_end, tz
            )
        assert intervals == []

    def test_free_events_are_excluded(self):
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:1\r\nDTSTART:20241202T100000Z\r\nDTEND:20241202T110000Z\r\n"
            "TRANSP:TRANSPARENT\r\nSUMMARY:Blocked-out but free\r\nEND:VEVENT\r\n"
            "END:VCALENDAR"
        )
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 1, tzinfo=tz)
        window_end = datetime(2024, 12, 8, tzinfo=tz)
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=ical.encode())
            intervals = collect_intervals(
                [{"name": "work", "url": "https://example.com/work.ics"}], window_start, window_end, tz
            )
        assert intervals == []

    def test_all_day_event(self):
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:1\r\nDTSTART;VALUE=DATE:20241202\r\nDTEND;VALUE=DATE:20241203\r\n"
            "SUMMARY:Conference Day\r\nEND:VEVENT\r\n"
            "END:VCALENDAR"
        )
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 1, tzinfo=tz)
        window_end = datetime(2024, 12, 8, tzinfo=tz)
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=ical.encode())
            intervals = collect_intervals(
                [{"name": "work", "url": "https://example.com/work.ics"}], window_start, window_end, tz
            )
        assert len(intervals) == 1
        assert intervals[0].summary == "Conference Day"


class TestMergeTimeline:
    def test_busy_wins_over_overlapping_tentative(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        window_end = datetime(2024, 12, 2, 12, 0, tzinfo=tz)
        intervals = [
            Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz),
                datetime(2024, 12, 2, 11, 0, tzinfo=tz),
                TENTATIVE,
                "personal",
                "Maybe",
            ),
            Interval(
                datetime(2024, 12, 2, 10, 30, tzinfo=tz),
                datetime(2024, 12, 2, 11, 30, tzinfo=tz),
                BUSY,
                "work",
                "Definitely",
            ),
        ]
        merged = merge_timeline(intervals, window_start, window_end)
        overlap_segments = [s for s in merged if s.start >= datetime(2024, 12, 2, 10, 30, tzinfo=tz)]
        assert all(s.severity == BUSY for s in overlap_segments if s.start < datetime(2024, 12, 2, 11, 0, tzinfo=tz))

    def test_adjacent_same_severity_segments_merge(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        window_end = datetime(2024, 12, 2, 12, 0, tzinfo=tz)
        intervals = [
            Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz), datetime(2024, 12, 2, 10, 30, tzinfo=tz), BUSY, "work", "A"
            ),
            Interval(
                datetime(2024, 12, 2, 10, 30, tzinfo=tz), datetime(2024, 12, 2, 11, 0, tzinfo=tz), BUSY, "work", "A"
            ),
        ]
        merged = merge_timeline(intervals, window_start, window_end)
        assert len(merged) == 1
        assert merged[0].start == datetime(2024, 12, 2, 10, 0, tzinfo=tz)
        assert merged[0].end == datetime(2024, 12, 2, 11, 0, tzinfo=tz)

    def test_empty_intervals_returns_empty(self):
        tz = ZoneInfo("Europe/London")
        assert merge_timeline([], datetime(2024, 12, 2, tzinfo=tz), datetime(2024, 12, 3, tzinfo=tz)) == []


class TestAddFreeGaps:
    """A small model reading a busy-only list reliably fabricates or misreads
    "free" time rather than computing the true complement (observed live —
    see calendars.py's add_free_gaps docstring). These lock in that the gap
    computation itself is actually correct.
    """

    def test_single_day_no_busy_time_fills_whole_tracked_window(self):
        tz = ZoneInfo("Europe/London")
        start = datetime(2024, 12, 2, tzinfo=tz)
        end = datetime(2024, 12, 3, tzinfo=tz)
        filled = add_free_gaps([], start, end)
        assert len(filled) == 1
        assert filled[0].severity == FREE
        assert filled[0].start == datetime(2024, 12, 2, 8, 0, tzinfo=tz)
        assert filled[0].end == datetime(2024, 12, 2, 20, 0, tzinfo=tz)

    def test_fills_gaps_either_side_of_a_busy_block(self):
        tz = ZoneInfo("Europe/London")
        start = datetime(2024, 12, 2, tzinfo=tz)
        end = datetime(2024, 12, 3, tzinfo=tz)
        busy = [
            Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz), datetime(2024, 12, 2, 10, 30, tzinfo=tz), BUSY, "work", "x"
            )
        ]
        filled = add_free_gaps(busy, start, end)
        free = sorted((f for f in filled if f.severity == FREE), key=lambda i: i.start)
        assert [(f.start, f.end) for f in free] == [
            (datetime(2024, 12, 2, 8, 0, tzinfo=tz), datetime(2024, 12, 2, 10, 0, tzinfo=tz)),
            (datetime(2024, 12, 2, 10, 30, tzinfo=tz), datetime(2024, 12, 2, 20, 0, tzinfo=tz)),
        ]

    def test_busy_block_outside_tracked_window_leaves_full_day_free(self):
        # A block entirely before day_start_hour (an early call) shouldn't
        # eat into the tracked free window at all.
        tz = ZoneInfo("Europe/London")
        start = datetime(2024, 12, 2, tzinfo=tz)
        end = datetime(2024, 12, 3, tzinfo=tz)
        busy = [
            Interval(datetime(2024, 12, 2, 6, 0, tzinfo=tz), datetime(2024, 12, 2, 7, 0, tzinfo=tz), BUSY, "work", "x")
        ]
        filled = add_free_gaps(busy, start, end)
        free = [f for f in filled if f.severity == FREE]
        assert len(free) == 1
        assert free[0].start == datetime(2024, 12, 2, 8, 0, tzinfo=tz)
        assert free[0].end == datetime(2024, 12, 2, 20, 0, tzinfo=tz)

    def test_custom_day_window(self):
        tz = ZoneInfo("Europe/London")
        start = datetime(2024, 12, 2, tzinfo=tz)
        end = datetime(2024, 12, 3, tzinfo=tz)
        filled = add_free_gaps([], start, end, day_start_hour=9, day_end_hour=17)
        assert filled[0].start == datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        assert filled[0].end == datetime(2024, 12, 2, 17, 0, tzinfo=tz)

    def test_spans_multiple_days(self):
        tz = ZoneInfo("Europe/London")
        start = datetime(2024, 12, 2, tzinfo=tz)
        end = datetime(2024, 12, 4, tzinfo=tz)
        filled = add_free_gaps([], start, end)
        days = {f.start.date() for f in filled}
        assert days == {datetime(2024, 12, 2).date(), datetime(2024, 12, 3).date()}


class TestFormatTimeline:
    def test_detailed_vs_not(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        window_end = datetime(2024, 12, 2, 12, 0, tzinfo=tz)
        merged = [
            Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz),
                datetime(2024, 12, 2, 10, 30, tzinfo=tz),
                BUSY,
                "work",
                "Secret Meeting",
            )
        ]
        detailed = format_timeline(merged, window_start, window_end, detailed=True)
        plain = format_timeline(merged, window_start, window_end, detailed=False)
        assert "Secret Meeting" in detailed
        assert "[work]" in detailed
        assert "Secret Meeting" not in plain
        assert "[work]" not in plain
        assert "free/busy only" in plain

    def test_free_all_day_only_when_nothing_scheduled_that_calendar_day(self):
        # A day free within the tracked 08:00-20:00 window but with a real
        # event outside it (e.g. an evening thing at 20:00) must NOT get
        # "free all day" printed right next to that event — tested live, a
        # small model reads that pairing as self-contradictory and starts
        # inventing a story rather than reporting the actual timeline.
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, tzinfo=tz)
        window_end = datetime(2024, 12, 3, tzinfo=tz)
        evening_event = [
            Interval(
                datetime(2024, 12, 2, 20, 0, tzinfo=tz), datetime(2024, 12, 2, 22, 0, tzinfo=tz), BUSY, "cal", "party"
            )
        ]
        result = format_timeline(evening_event, window_start, window_end, detailed=False)
        # Not a plain substring check: the footer note explaining what the
        # phrase means also contains the words "free all day" in quotes.
        assert "  free all day" not in result
        assert "08:00-20:00  FREE" in result
        assert "20:00-22:00  BUSY" in result

    def test_free_all_day_when_genuinely_nothing_scheduled(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, tzinfo=tz)
        window_end = datetime(2024, 12, 4, tzinfo=tz)
        # One busy day, one genuinely empty day.
        merged = [
            Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz), datetime(2024, 12, 2, 10, 30, tzinfo=tz), BUSY, "cal", "x"
            )
        ]
        result = format_timeline(merged, window_start, window_end, detailed=False)
        lines = result.split("\n")
        tuesday_idx = lines.index("Tuesday 03 December")
        assert lines[tuesday_idx + 1] == "  free all day"

    def test_no_busy_time_found(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, tzinfo=tz)
        window_end = datetime(2024, 12, 3, tzinfo=tz)
        result = format_timeline([], window_start, window_end, detailed=True)
        assert "free all day" in result
        assert "Monday 02 December" in result


class TestGetMergedAvailability:
    def test_empty_calendars_raises(self):
        with pytest.raises(ValueError, match="No calendars provided"):
            get_merged_availability([])

    def test_end_to_end(self):
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=BUSY_ICAL.encode())
            result = get_merged_availability(
                [{"name": "work", "url": "https://example.com/work.ics"}],
                start_date="2024-12-01",
                days_ahead=7,
                detailed=True,
            )
        assert "Team Meeting" in result
        assert "[work]" in result

    def test_default_start_date_is_now(self):
        with patch("bolster.utils.calendars.session") as mock_session:
            mock_session.get.return_value = _make_response(content=EMPTY_ICAL.encode())
            result = get_merged_availability(
                [{"name": "work", "url": "https://example.com/work.ics"}],
                detailed=False,
            )
        assert "Availability" in result
