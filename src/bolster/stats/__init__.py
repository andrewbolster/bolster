"""
Basic statistics and data frame helpers.

Simple functions for common data manipulation tasks:
- add_totals/drop_totals: manage row/column totals in DataFrames
- top_n: truncate DataFrames to top N rows with 'others' aggregation
- fix_datetime_tz_columns: strip timezone info from datetime columns

Plus distribution fitting in the distributions submodule.
"""

from typing import AnyStr

import pandas as pd


def add_totals(
    df: pd.DataFrame,
    column_total: AnyStr = "total",
    row_total: AnyStr = "total",
    inplace=True,
):
    """
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

    """
    if not inplace:
        df = df.copy(deep=True)
    df.loc[column_total] = df.sum(numeric_only=True, axis=0)
    df.loc[:, row_total] = df.sum(numeric_only=True, axis=1)

    return df


def drop_totals(
    df: pd.DataFrame,
    column_total: AnyStr = "total",
    row_total: AnyStr = "total",
    inplace=True,
) -> pd.DataFrame:
    """
    Remove Row and Column totals from a dataframe (in place)

    Parameters
    ----------
    df : pd.DataFrame
        The DataFrame from which to remove totals.
    column_total : AnyStr, optional
        The name of the column total, by default "total".
    row_total : AnyStr, optional
        The name of the row total, by default "total".
    inplace : bool, optional
        Whether to modify the DataFrame in place, by default True.

    Returns
    -------
    pd.DataFrame
        The DataFrame with totals removed.

    Examples
    --------
    >>> df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6], 'total': [5, 7, 9]})
    >>> df.loc['total'] = [6, 15, 21]
    >>> drop_totals(df)
       A  B
    0  1  4
    1  2  5
    2  3  6
    """
    if not inplace:
        df = df.copy(deep=True)

    if column_total in df.columns:
        df = df.drop(columns=[column_total])

    if row_total in df.index:
        df = df.drop(index=[row_total])

    return df


def fix_datetime_tz_columns(df: pd.DataFrame, inplace=True) -> pd.DataFrame:
    """
    Strip Timezone information from relevant datetime columns in a dataframe

    Parameters
    ----------
    df
    inplace (bool)


    Returns
    -------
    df

    """
    if not inplace:
        df = df.copy(deep=True)
    date_columns = df.select_dtypes(include=["datetime64[ns, UTC]", "datetimetz"]).columns
    for date_column in date_columns:
        df[date_column] = df[date_column].dt.tz_localize(None)
    return df


def top_n(df: pd.DataFrame, n: int, others: AnyStr = "others") -> pd.DataFrame:
    """
    Truncate the DataFrame to the top 'n' rows, summing all subsequent rows into an 'others' row.

    Parameters
    ----------
    df : pd.DataFrame
        The DataFrame to truncate.
    n : int
        The number of top rows to keep.

    Returns
    -------
    pd.DataFrame
        The truncated DataFrame with an 'others' row.

    Examples
    --------
    >>> df = pd.DataFrame({'A': [1, 2, 3, 4, 5], 'B': [5, 4, 3, 2, 1]})
    >>> top_n(df, 3) # doctest: +NORMALIZE_WHITESPACE
           A  B
    0      1  5
    1      2  4
    2      3  3
    others 9  3
    """
    if n >= len(df):
        return df

    top_df = df.iloc[:n]
    others_df = df.iloc[n:].sum(numeric_only=True)
    if isinstance(others_df, (pd.Series, pd.DataFrame)):
        others_df.name = others
    else:
        others_df = pd.Series(others_df, name=others)
    return pd.concat([top_df, others_df.to_frame().T])
