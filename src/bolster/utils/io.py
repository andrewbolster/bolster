"""File I/O helpers.

Provides thin wrappers around :mod:`pandas` I/O for common tasks, such as
writing multiple DataFrames to separate sheets of a single Excel workbook.

Example:
    >>> import pandas as pd
    >>> from bolster.utils.io import save_xls
    >>> import tempfile, os
    >>> df1 = pd.DataFrame({"a": [1, 2]})
    >>> df2 = pd.DataFrame({"b": [3, 4]})
    >>> with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
    ...     tmp = f.name
    >>> save_xls({"Sheet1": df1, "Sheet2": df2}, tmp)
    >>> os.remove(tmp)
"""

from typing import AnyStr, BinaryIO

import pandas as pd


def save_xls(dict_df: dict[AnyStr, pd.DataFrame], path: str | BinaryIO) -> None:
    """Write a mapping of sheet-name → DataFrame to a multi-sheet Excel file.

    Args:
        dict_df: Mapping of sheet names to DataFrames.  Each key becomes a
            worksheet name; each value is written to that sheet.
        path: File path (``str``) or writable binary file-like object for the
            output ``.xlsx`` workbook.

    Example:
        >>> import pandas as pd, tempfile, os
        >>> df = pd.DataFrame({"x": [10, 20]})
        >>> with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        ...     tmp = f.name
        >>> save_xls({"Results": df}, tmp)
        >>> os.remove(tmp)
    """
    with pd.ExcelWriter(path) as writer:
        for key in dict_df:
            dict_df[key].to_excel(writer, sheet_name=key)
