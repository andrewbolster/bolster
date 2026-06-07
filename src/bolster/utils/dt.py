"""Datetime rounding and timezone utilities.

Provides helpers that coerce :class:`datetime.datetime` and
:class:`datetime.date` objects to useful calendar boundaries (week, month)
and to UTC midnight, without depending on any third-party libraries.

Example:
    >>> from bolster.utils.dt import round_to_week, round_to_month
    >>> from datetime import date
    >>> round_to_week(date(2024, 3, 13))   # Wednesday → previous Monday
    datetime.date(2024, 3, 11)
    >>> round_to_month(date(2024, 3, 13))
    datetime.date(2024, 3, 1)
"""

from datetime import UTC, date, datetime, timedelta


def round_to_week(dt: datetime | date) -> date:
    """Return a date for the Monday of the week containing the given date.

    Args:
        dt: A :class:`datetime.datetime` or :class:`datetime.date` to round.

    Returns:
        The Monday on or before ``dt`` as a :class:`datetime.date`.

    Example:
        >>> round_to_week(datetime(2018,8,9,12,1))
        datetime.date(2018, 8, 6)
        >>> round_to_week(date(2018,8,9))
        datetime.date(2018, 8, 6)
    """
    return (dt.date() if isinstance(dt, datetime) else dt) - timedelta(days=dt.weekday())


def round_to_month(dt: datetime | date) -> date:
    """Return a date for the first day of the month containing the given date.

    Args:
        dt: A :class:`datetime.datetime` or :class:`datetime.date` to round.

    Returns:
        The first day of the month of ``dt`` as a :class:`datetime.date`.

    Example:
        >>> round_to_month(datetime(2018,8,9,12,1))
        datetime.date(2018, 8, 1)
        >>> round_to_month(date(2018,8,9))
        datetime.date(2018, 8, 1)
    """
    dt = dt.date() if isinstance(dt, datetime) else dt

    return date(dt.year, dt.month, 1)


def utc_midnight_on(dt: datetime) -> datetime:
    """Return UTC midnight for the calendar date of a given datetime.

    Converts any :class:`datetime.datetime` to ``00:00:00 UTC`` on the same
    calendar date, regardless of the original time or timezone offset.  This
    is useful when a downstream service requires UTC-naive timestamps or
    rejects sub-day granularity.

    Args:
        dt: A :class:`datetime.datetime` whose calendar date is used.  The
            time component and any timezone info are ignored.

    Returns:
        A timezone-aware :class:`datetime.datetime` at ``00:00:00 UTC`` on
        the same calendar date as ``dt``.

    Example:
        >>> utc_midnight_on(datetime(2018,9,1,12,12))
        datetime.datetime(2018, 9, 1, 0, 0, tzinfo=datetime.timezone.utc)

        >>> utc_midnight_on(datetime(2018,9,1,12,12, tzinfo=timezone(timedelta(hours=-13))))
        datetime.datetime(2018, 9, 1, 0, 0, tzinfo=datetime.timezone.utc)
    """
    return datetime.combine(dt.date(), datetime.min.time()).replace(tzinfo=UTC)
