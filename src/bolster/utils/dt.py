from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Union


def round_to_week(dt: Union[datetime, date]) -> date:
    """Return a date for the Monday before the given date

    Args:
      dt: return:
      dt: datetime:

    Returns:

    >>> round_to_week(datetime(2018,8,9,12,1))
    datetime.date(2018, 8, 6)
    >>> round_to_week(date(2018,8,9))
    datetime.date(2018, 8, 6)
    """
    return (dt.date() if isinstance(dt, datetime) else dt) - timedelta(
        days=dt.weekday()
    )


def round_to_month(dt: Union[datetime, date]) -> date:
    """Return a date for the first day of the month of a given date

    Args:
      dt: return:
      dt: datetime:

    Returns:

    >>> round_to_month(datetime(2018,8,9,12,1))
    datetime.date(2018, 8, 1)
    >>> round_to_month(date(2018,8,9))
    datetime.date(2018, 8, 1)
    """
    dt = dt.date() if isinstance(dt, datetime) else dt

    return date(dt.year, dt.month, 1)


def utc_midnight_on(dt: datetime) -> datetime:
    """Some services don't like timezones, so this helper function converts `datetime.date` and
    `datetime.datetime` objects to a `datetime.datetime` object corresponding to UTC Midnight
    on that date.


    Pays primary attention to the actual Date of the input, regardless of if the combination
    of given-time and timezone would roll over into another date.

    Args:
      dt: return:
      dt: datetime:

    >>> utc_midnight_on(datetime(2018,9,1,12,12))
    datetime.datetime(2018, 9, 1, 0, 0, tzinfo=datetime.timezone.utc)

    >>> utc_midnight_on(datetime(2018,9,1,12,12, tzinfo=timezone(timedelta(hours=-13))))
    datetime.datetime(2018, 9, 1, 0, 0, tzinfo=datetime.timezone.utc)
    """
    return datetime.combine(dt.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
