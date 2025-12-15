bolster.utils.dt
================

.. py:module:: bolster.utils.dt


Functions
---------

.. autoapisummary::

   bolster.utils.dt.round_to_week
   bolster.utils.dt.round_to_month
   bolster.utils.dt.utc_midnight_on


Module Contents
---------------

.. py:function:: round_to_week(dt)

   Return a date for the Monday before the given date

   :param dt: return:
   :param dt: datetime:

   Returns:

   >>> round_to_week(datetime(2018,8,9,12,1))
   datetime.date(2018, 8, 6)
   >>> round_to_week(date(2018,8,9))
   datetime.date(2018, 8, 6)


.. py:function:: round_to_month(dt)

   Return a date for the first day of the month of a given date

   :param dt: return:
   :param dt: datetime:

   Returns:

   >>> round_to_month(datetime(2018,8,9,12,1))
   datetime.date(2018, 8, 1)
   >>> round_to_month(date(2018,8,9))
   datetime.date(2018, 8, 1)


.. py:function:: utc_midnight_on(dt)

   Some services don't like timezones, so this helper function converts `datetime.date` and
   `datetime.datetime` objects to a `datetime.datetime` object corresponding to UTC Midnight
   on that date.


   Pays primary attention to the actual Date of the input, regardless of if the combination
   of given-time and timezone would roll over into another date.

   :param dt: return:
   :param dt: datetime:

   >>> utc_midnight_on(datetime(2018,9,1,12,12))
   datetime.datetime(2018, 9, 1, 0, 0, tzinfo=datetime.timezone.utc)

   >>> utc_midnight_on(datetime(2018,9,1,12,12, tzinfo=timezone(timedelta(hours=-13))))
   datetime.datetime(2018, 9, 1, 0, 0, tzinfo=datetime.timezone.utc)
