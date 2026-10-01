"""Generic local persistence for repeated live-data snapshots.

Some live feeds (vehicle positions, real-time status boards) have no historical API —
the only way to build a time series is to poll the feed yourself and keep what you get.
This module is the shared "append one more DataFrame to a local sqlite store" primitive
for that: it has no knowledge of what's in the DataFrame, so any poller can reuse it.

Stores live under ``~/.cache/bolster/snapshots/<name>.db`` — one sqlite file per named
store, one table per kind of snapshot within it. Despite living under the cache
directory, data written here is not safely re-derivable the way a downloaded-file cache
is (there's no "download it again" for a point-in-time snapshot); callers that care
about preserving it should copy the db file out from under the cache directory.

Example:
    >>> import pandas as pd
    >>> from bolster.utils.snapshots import append_snapshot, read_snapshots, snapshot_db_path
    >>> db = snapshot_db_path("doctest_example")
    >>> _ = append_snapshot(db, "widgets", pd.DataFrame({"id": [1, 2], "value": [10, 20]}))
    >>> sorted(read_snapshots(db, "widgets").columns)
    ['id', 'polled_at', 'value']
    >>> db.unlink()
"""

import os
import sqlite3
from pathlib import Path

import pandas as pd

from .cache import CACHE_BASE

_SNAPSHOT_DIR = CACHE_BASE / "snapshots"


def snapshot_db_path(name: str) -> Path:
    """Return the path to a named snapshot store, creating its parent directory.

    Args:
        name: Store name, e.g. ``"translink_vmi"``.

    Returns:
        ``~/.cache/bolster/snapshots/<name>.db``.

    Example:
        >>> snapshot_db_path("example").parent.name
        'snapshots'
    """
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SNAPSHOT_DIR / f"{name}.db"


def append_snapshot(
    db_path: str | os.PathLike[str], table: str, df: pd.DataFrame, polled_at: pd.Timestamp | None = None
) -> int:
    """Append ``df``'s rows to ``table`` in the sqlite db at ``db_path``.

    Creates the database file, directory, and table on first use (schema inferred from
    ``df`` by :meth:`pandas.DataFrame.to_sql`). A ``polled_at`` column (UTC, ISO 8601)
    is stamped onto a copy of ``df`` first unless it already has one, so every row
    written through this function carries a consistent capture time.

    Args:
        db_path: Path to the sqlite file (see :func:`snapshot_db_path`).
        table: Table name to append to.
        df: Rows to write. An empty DataFrame is a no-op, not an error.
        polled_at: Capture time to stamp; defaults to now (UTC). Ignored if ``df``
            already has a ``polled_at`` column.

    Returns:
        Number of rows written (``0`` for an empty ``df``).

    Example:
        >>> import pandas as pd
        >>> db = snapshot_db_path("doctest_append")
        >>> append_snapshot(db, "t", pd.DataFrame({"x": [1, 2, 3]}))
        3
        >>> append_snapshot(db, "t", pd.DataFrame())
        0
        >>> db.unlink()
    """
    if df.empty:
        return 0

    out = df.copy()
    if "polled_at" not in out.columns:
        out.insert(0, "polled_at", (polled_at or pd.Timestamp.now(tz="UTC")).isoformat())

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        out.to_sql(table, con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()
    return len(out)


def read_snapshots(
    db_path: str | os.PathLike[str], table: str, since: str | pd.Timestamp | None = None
) -> pd.DataFrame:
    """Read rows previously written by :func:`append_snapshot`.

    Args:
        db_path: Path to the sqlite file.
        table: Table name to read.
        since: If given, only rows with ``polled_at >= since`` (compared as ISO 8601
            strings, so any value accepted by :class:`pandas.Timestamp` works).

    Returns:
        All matching rows, oldest first. An empty DataFrame (not an error) if the
        database file or table doesn't exist yet.

    Example:
        >>> import pandas as pd
        >>> db = snapshot_db_path("doctest_read")
        >>> read_snapshots(db, "t").empty
        True
        >>> _ = append_snapshot(db, "t", pd.DataFrame({"x": [1]}))
        >>> len(read_snapshots(db, "t"))
        1
        >>> db.unlink()
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame()

    con = sqlite3.connect(db_path)
    try:
        tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table' AND name=?", con, params=(table,))
        if tables.empty:
            return pd.DataFrame()

        query = f"SELECT * FROM {table}"  # noqa: S608 - table name is this module's own, never user input
        params: tuple = ()
        if since is not None:
            query += " WHERE polled_at >= ?"
            params = (pd.Timestamp(since).isoformat(),)
        query += " ORDER BY polled_at"
        return pd.read_sql(query, con, params=params)
    finally:
        con.close()
