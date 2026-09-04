"""Merged free/busy availability across multiple ICS calendar feeds.

Fetches one or more ICS calendar feeds, expands recurring events (RRULE,
including per-occurrence overrides), classifies each event as busy /
tentative / free, and merges overlapping calendars into a single timeline
with busy-beats-tentative-beats-free severity.

This module knows nothing about where calendar URLs come from — callers
pass a list of ``{"name": ..., "url": ...}`` dicts. It's deliberately not
wired into ``bolster.cli``: URLs for private calendars are secrets, and a
CLI command would encourage passing them on a command line (shell history,
process listings) rather than through whatever secret-management a caller
already has.

Example:
    >>> from bolster.utils.calendars import event_severity, FREE
    >>> from icalendar import Calendar
    >>> cal = Calendar.from_ical('''BEGIN:VCALENDAR
    ... VERSION:2.0
    ... BEGIN:VEVENT
    ... UID:1
    ... DTSTART:20250101T100000Z
    ... DTEND:20250101T110000Z
    ... TRANSP:TRANSPARENT
    ... END:VEVENT
    ... END:VCALENDAR''')
    >>> event_severity(cal.walk("VEVENT")[0]) == FREE
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import recurring_ical_events
from icalendar import Calendar

from .web import session

# Severity order: higher wins when calendars overlap for the same time slot.
FREE, TENTATIVE, BUSY = 0, 1, 2
SEVERITY_LABEL = {FREE: "free", TENTATIVE: "tentative", BUSY: "busy"}


@dataclass
class Interval:
    """A single busy/tentative block, tagged with its source calendar and title."""

    start: datetime
    end: datetime
    severity: int
    calendar: str
    summary: str


def fetch_ics(name: str, url: str) -> Calendar | None:
    """Download and parse one ICS feed.

    Returns None (rather than raising) on any fetch or parse failure, so
    one bad calendar doesn't take down a multi-calendar merge — the caller
    sees that calendar simply contribute no intervals.

    Args:
        name: Label for this calendar, used only in error logging by callers.
        url: The ICS feed URL.

    Returns:
        Parsed Calendar, or None if it couldn't be fetched/parsed.
    """
    try:
        resp = session.get(url)
        resp.raise_for_status()
        return Calendar.from_ical(resp.content)
    except Exception:  # noqa: BLE001 — one calendar failing shouldn't sink the whole merge
        return None


def event_severity(component: Any) -> int:
    """Classify a VEVENT as busy / tentative / free.

    Checks, in order: TRANSP (TRANSPARENT events never block time),
    Outlook/Exchange's X-MICROSOFT-CDO-BUSYSTATUS (most authoritative when
    present), STATUS (TENTATIVE/CANCELLED), then the calendar owner's own
    PARTSTAT among attendees. Defaults to BUSY for anything else — an
    untransparent, unconfirmed-otherwise event blocks time.

    Args:
        component: A VEVENT component (from icalendar or recurring_ical_events).

    Returns:
        One of FREE, TENTATIVE, BUSY.

    Example:
        >>> from icalendar import Calendar
        >>> cal = Calendar.from_ical('''BEGIN:VCALENDAR
        ... VERSION:2.0
        ... BEGIN:VEVENT
        ... UID:1
        ... DTSTART:20250101T100000Z
        ... DTEND:20250101T110000Z
        ... STATUS:TENTATIVE
        ... END:VEVENT
        ... END:VCALENDAR''')
        >>> event_severity(cal.walk("VEVENT")[0]) == TENTATIVE
        True
    """
    transp = str(component.get("TRANSP", "")).upper()
    if transp == "TRANSPARENT":
        return FREE

    ms_status = str(component.get("X-MICROSOFT-CDO-BUSYSTATUS", "")).upper()
    if ms_status == "FREE":
        return FREE
    if ms_status == "TENTATIVE":
        return TENTATIVE
    if ms_status in ("BUSY", "OOF"):
        return BUSY

    status = str(component.get("STATUS", "")).upper()
    if status == "CANCELLED":
        return FREE
    if status == "TENTATIVE":
        return TENTATIVE

    attendees = component.get("ATTENDEE")
    if attendees:
        if not isinstance(attendees, list):
            attendees = [attendees]
        for att in attendees:
            partstat = str(att.params.get("PARTSTAT", "")).upper()
            if partstat == "TENTATIVE":
                return TENTATIVE
            if partstat == "DECLINED":
                return FREE

    return BUSY


def _to_aware(dt: date | datetime, tz: ZoneInfo) -> datetime:
    """Normalise a date/datetime (icalendar gives naive dates for all-day events) to aware datetime."""
    if isinstance(dt, datetime):
        return dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    return datetime.combine(dt, time.min, tzinfo=tz)


def collect_intervals(
    calendars: list[dict[str, str]],
    window_start: datetime,
    window_end: datetime,
    tz: ZoneInfo,
) -> list[Interval]:
    """Fetch every calendar and expand recurring events into busy/tentative Intervals within a window.

    Args:
        calendars: List of {"name": ..., "url": ...} dicts.
        window_start: Start of the query window (inclusive).
        window_end: End of the query window (exclusive).
        tz: Timezone to normalise all event times to.

    Returns:
        Unmerged list of Interval, one per busy/tentative occurrence
        across all calendars (FREE events are dropped — they never block
        time, so there's nothing for the merge step to do with them).
    """
    intervals: list[Interval] = []
    for cal in calendars:
        name, url = cal["name"], cal["url"]
        ical = fetch_ics(name, url)
        if ical is None:
            continue
        for component in recurring_ical_events.of(ical).between(window_start, window_end):
            severity = event_severity(component)
            if severity == FREE:
                continue
            start = _to_aware(component["DTSTART"].dt, tz)
            end_prop = component.get("DTEND")
            end = _to_aware(end_prop.dt, tz) if end_prop else start + timedelta(hours=1)
            summary = str(component.get("SUMMARY", "(no title)"))
            intervals.append(Interval(start, end, severity, name, summary))
    return intervals


def merge_timeline(intervals: list[Interval], window_start: datetime, window_end: datetime) -> list[Interval]:
    """Sweep-line merge: at every point, keep the highest severity active, tag with contributing calendars.

    Where calendars overlap for the same time slot, busy wins over
    tentative wins over free (segments with no active interval at all are
    dropped — the caller treats gaps as free).

    Args:
        intervals: Unmerged intervals, e.g. from collect_intervals.
        window_start: Start of the query window.
        window_end: End of the query window.

    Returns:
        Merged, non-overlapping, time-ordered list of Interval.
    """
    if not intervals:
        return []

    boundaries = sorted({i.start for i in intervals} | {i.end for i in intervals} | {window_start, window_end})
    boundaries = [b for b in boundaries if window_start <= b <= window_end]

    segments: list[Interval] = []
    for seg_start, seg_end in zip(boundaries, boundaries[1:], strict=False):
        if seg_start >= seg_end:
            continue
        mid = seg_start + (seg_end - seg_start) / 2
        active = [i for i in intervals if i.start <= mid < i.end]
        if not active:
            continue
        top_severity = max(i.severity for i in active)
        contributors = sorted({i.calendar for i in active if i.severity == top_severity})
        summaries = sorted({i.summary for i in active if i.severity == top_severity})
        segments.append(Interval(seg_start, seg_end, top_severity, "+".join(contributors), "; ".join(summaries)))

    merged: list[Interval] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if prev and prev.end == seg.start and prev.severity == seg.severity and prev.calendar == seg.calendar:
            merged[-1] = Interval(prev.start, seg.end, seg.severity, seg.calendar, prev.summary)
        else:
            merged.append(seg)
    return merged


def _day_bounds(day: date, tz: ZoneInfo, day_start_hour: int, day_end_hour: int) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, time(hour=day_start_hour), tzinfo=tz),
        datetime.combine(day, time(hour=day_end_hour), tzinfo=tz),
    )


def add_free_gaps(
    merged: list[Interval],
    window_start: datetime,
    window_end: datetime,
    *,
    day_start_hour: int = 8,
    day_end_hour: int = 20,
) -> list[Interval]:
    """Fill the gaps between busy/tentative segments with explicit FREE ones.

    Asked to read a busy-only list, a small model reliably fabricates or
    mislabels "free" time rather than correctly computing the complement —
    observed live, it repeatedly invented specific free hours nowhere in the
    data, and in one run reused a listed BUSY block as if it were free. This
    computes the complement instead of leaving a caller (human or model) to.

    Bounded to [day_start_hour, day_end_hour) each day rather than the full
    24 hours: stating every night as "free" would swamp the real signal for
    no benefit, and it keeps every synthesised segment within a single
    calendar day, which format_timeline's one-segment-per-line rendering
    assumes.

    Args:
        merged: Output of merge_timeline (busy/tentative only).
        window_start: Start of the query window.
        window_end: End of the query window.
        day_start_hour: Start of the free-gap tracking window each day.
        day_end_hour: End of the free-gap tracking window each day.

    Returns:
        merged, plus one FREE Interval per gap within the tracked window on
        every day in range — including a single day-spanning FREE Interval
        for a day with no busy/tentative activity at all.

    Example:
        >>> from datetime import datetime
        >>> from zoneinfo import ZoneInfo
        >>> tz = ZoneInfo("Europe/London")
        >>> start = datetime(2025, 1, 6, tzinfo=tz)  # Monday
        >>> end = datetime(2025, 1, 7, tzinfo=tz)
        >>> filled = add_free_gaps([], start, end)
        >>> len(filled)
        1
        >>> filled[0].severity == FREE
        True
    """
    tz = window_start.tzinfo
    result = list(merged)

    day = window_start.date()
    last_day = window_end.date()
    while day <= last_day:
        day_start, day_end = _day_bounds(day, tz, day_start_hour, day_end_hour)
        day_start = max(day_start, window_start)
        day_end = min(day_end, window_end)
        if day_start >= day_end:
            day += timedelta(days=1)
            continue

        busy_today = sorted(
            (m for m in merged if m.start < day_end and m.end > day_start),
            key=lambda m: m.start,
        )

        cursor = day_start
        for seg in busy_today:
            seg_start = max(seg.start, day_start)
            if seg_start > cursor:
                result.append(Interval(cursor, seg_start, FREE, "", ""))
            cursor = max(cursor, min(seg.end, day_end))
        if cursor < day_end:
            result.append(Interval(cursor, day_end, FREE, "", ""))

        day += timedelta(days=1)

    return sorted(result, key=lambda i: i.start)


def format_timeline(
    merged: list[Interval],
    window_start: datetime,
    window_end: datetime,
    *,
    detailed: bool,
    day_start_hour: int = 8,
    day_end_hour: int = 20,
) -> str:
    """Render a merged timeline as text, with explicit free gaps filled in.

    Args:
        merged: Output of merge_timeline.
        window_start: Start of the query window.
        window_end: End of the query window.
        detailed: If True, include which calendar and the event title
            behind each block — for a caller who owns the calendars. If
            False, show only plain free/busy/tentative time ranges with
            no calendar source or event content — safe to show to anyone.
        day_start_hour: Start of the free-gap tracking window each day —
            see add_free_gaps.
        day_end_hour: End of the free-gap tracking window each day.

    Returns:
        Multi-line text report.
    """
    header = f"Availability {window_start:%Y-%m-%d %H:%M} to {window_end:%Y-%m-%d %H:%M} ({window_start.tzname()}):"
    filled = add_free_gaps(merged, window_start, window_end, day_start_hour=day_start_hour, day_end_hour=day_end_hour)

    # "free all day" only when *nothing* — including outside the tracked
    # window — is scheduled that calendar date. Tried gating this on the
    # tracked window alone first: a day free 08:00-20:00 but with a real
    # event at 21:00 (outside it) got "free all day" printed right next to
    # that event, which a small model read as self-contradictory and
    # resolved by inventing a story. Tried dropping the phrase entirely
    # instead: a small model reading a long list of explicit HH:MM-HH:MM
    # FREE lines reliably undercounted which days were actually free,
    # including once concluding a fully-free weekend was "fully booked"
    # since neither day got its own summary line. This is the version that
    # tested clean on both counts.
    scheduled_dates = {d for m in merged for d in (m.start.date(), m.end.date())}

    lines = [header, ""]
    current_day = None
    for seg in filled:
        day = seg.start.date()
        if day != current_day:
            current_day = day
            lines.append(f"{day.strftime('%A %d %B')}")

        day_start, day_end = _day_bounds(day, seg.start.tzinfo, day_start_hour, day_end_hour)
        spans_tracked_window = seg.start <= max(day_start, window_start) and seg.end >= min(day_end, window_end)
        if seg.severity == FREE and spans_tracked_window and day not in scheduled_dates:
            lines.append("  free all day")
            continue

        label = SEVERITY_LABEL[seg.severity].upper()
        line = f"  {seg.start.strftime('%H:%M')}-{seg.end.strftime('%H:%M')}  {label}"
        if detailed and seg.calendar:
            line += f"  [{seg.calendar}] {seg.summary}"
        lines.append(line)

    lines.append("")
    lines.append(
        f"Free time is shown for {day_start_hour:02d}:00-{day_end_hour:02d}:00 each day; "
        'outside that window is not tracked. "free all day" means nothing at all is scheduled that day.'
    )
    if not detailed:
        lines.append("Note: showing free/busy only. Calendar source and event details are private.")

    return "\n".join(lines)


def get_merged_availability(
    calendars: list[dict[str, str]],
    *,
    start_date: str | None = None,
    days_ahead: int = 7,
    detailed: bool = True,
    tz_name: str = "Europe/London",
    day_start_hour: int = 8,
    day_end_hour: int = 20,
) -> str:
    """Fetch, merge, and render availability across several ICS calendars.

    Top-level convenience wrapping fetch + expand + merge + format.

    Args:
        calendars: List of {"name": ..., "url": ...} dicts. Raises
            ValueError if empty.
        start_date: Start of the query window as "YYYY-MM-DD". Defaults
            to now.
        days_ahead: How many days ahead of start_date to check.
        detailed: If True, include calendar name and event title per
            block. If False, plain free/busy/tentative only.
        tz_name: IANA timezone name for the query window and output.
        day_start_hour: Start of the free-gap tracking window each day —
            see add_free_gaps.
        day_end_hour: End of the free-gap tracking window each day.

    Returns:
        Multi-line text report (see format_timeline).

    Raises:
        ValueError: If calendars is empty.

    Example:
        >>> get_merged_availability([])
        Traceback (most recent call last):
            ...
        ValueError: No calendars provided
    """
    if not calendars:
        raise ValueError("No calendars provided")

    tz = ZoneInfo(tz_name)
    window_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz) if start_date else datetime.now(tz)
    window_end = window_start + timedelta(days=days_ahead)

    intervals = collect_intervals(calendars, window_start, window_end, tz)
    merged = merge_timeline(intervals, window_start, window_end)
    return format_timeline(
        merged,
        window_start,
        window_end,
        detailed=detailed,
        day_start_hour=day_start_hour,
        day_end_hour=day_end_hour,
    )
