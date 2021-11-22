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
    date_columns = df.select_dtypes(
        include=["datetime64[ns, UTC]", "datetimetz"]
    ).columns
    for date_column in date_columns:
        df[date_column] = df[date_column].dt.tz_localize(None)
    return df
