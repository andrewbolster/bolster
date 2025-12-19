bolster.stats
=============

.. py:module:: bolster.stats

.. autoapi-nested-parse::

   Basic statistics and data frame helpers.

   Simple functions for common data manipulation tasks:
   - add_totals/drop_totals: manage row/column totals in DataFrames
   - top_n: truncate DataFrames to top N rows with 'others' aggregation
   - fix_datetime_tz_columns: strip timezone info from datetime columns

   Plus distribution fitting in the distributions submodule.



Submodules
----------

.. toctree::
   :maxdepth: 1

   /autoapi/bolster/stats/distributions/index


Functions
---------

.. autoapisummary::

   bolster.stats.add_totals
   bolster.stats.drop_totals
   bolster.stats.fix_datetime_tz_columns
   bolster.stats.top_n


Package Contents
----------------

.. py:function:: add_totals(df, column_total = 'total', row_total = 'total', inplace=True)

   Add Row and Column totals to a dataframe (in place)

   >>> add_totals(pd.DataFrame([[0,1,2],[3,4,5]]))
          0  1  2  total
   0      0  1  2      3
   1      3  4  5     12
   total  3  5  7     15

   >>> add_totals(pd.DataFrame([[0,1,2],[3,4,5]]),'ctot', 'rtot')
         0  1  2  rtot
   0     0  1  2     3
   1     3  4  5    12
   ctot  3  5  7    15


   >>> df = pd.DataFrame([[0,1,2],[3,4,5]])
   >>> add_totals(df, inplace=False)
          0  1  2  total
   0      0  1  2      3
   1      3  4  5     12
   total  3  5  7     15

   >>> df
      0  1  2
   0  0  1  2
   1  3  4  5



.. py:function:: drop_totals(df, column_total = 'total', row_total = 'total', inplace=True)

   Remove Row and Column totals from a dataframe (in place)

   :param df: The DataFrame from which to remove totals.
   :type df: pd.DataFrame
   :param column_total: The name of the column total, by default "total".
   :type column_total: AnyStr, optional
   :param row_total: The name of the row total, by default "total".
   :type row_total: AnyStr, optional
   :param inplace: Whether to modify the DataFrame in place, by default True.
   :type inplace: bool, optional

   :returns: The DataFrame with totals removed.
   :rtype: pd.DataFrame

   .. rubric:: Examples

   >>> df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6], 'total': [5, 7, 9]})
   >>> df.loc['total'] = [6, 15, 21]
   >>> drop_totals(df)
      A  B
   0  1  4
   1  2  5
   2  3  6


.. py:function:: fix_datetime_tz_columns(df, inplace=True)

   Strip Timezone information from relevant datetime columns in a dataframe

   :param df:
   :param inplace (bool):

   :rtype: df


.. py:function:: top_n(df, n, others = 'others')

   Truncate the DataFrame to the top 'n' rows, summing all subsequent rows into an 'others' row.

   :param df: The DataFrame to truncate.
   :type df: pd.DataFrame
   :param n: The number of top rows to keep.
   :type n: int

   :returns: The truncated DataFrame with an 'others' row.
   :rtype: pd.DataFrame

   .. rubric:: Examples

   >>> df = pd.DataFrame({'A': [1, 2, 3, 4, 5], 'B': [5, 4, 3, 2, 1]})
   >>> top_n(df, 3) # doctest: +NORMALIZE_WHITESPACE
          A  B
   0      1  5
   1      2  4
   2      3  3
   others 9  3
