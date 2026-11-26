"""NISRA Northern Ireland Economic Trade Statistics (NIETS) Data Source.

Published as: Northern Ireland Economic Trade Statistics. The series was published as the
Broad Economy Sales and Exports Statistics (BESES) before December 2022, and the PxStat
statistic codes still carry the old name (``BESESVALUE``, ``BESESCOUNT``).

Estimated sales by, and purchases of, Northern Ireland businesses, by trade partner, in pounds
sterling (millions), annually. Every figure is a survey estimate published with a 95% confidence
interval and a coefficient of variation.

Five PxStat matrices are read, one getter each:

====================  =========  ===================================================================
Getter                Matrix     Cut
====================  =========  ===================================================================
``get_by_partner``    NIETS01    Country of the trade partner (outside the UK)
``get_by_industry``   NIETS02    Destination, goods or services, and 17 industry sections
``get_by_sic2``       NIETS03    Destination and 88 SIC 2007 two-digit divisions
``get_by_size_band``  NIETS04    Destination, goods or services, and business employment size band
``get_by_lgd``        NIETS05    Destination and the 11 Local Government Districts
====================  =========  ===================================================================

Every getter returns a tidy frame with one row per cell, keyed by *code* columns (``flow``,
``destination``, ``industry_code``, ``lgd_code`` ...) with the published label beside each code.
Join on the codes: PxStat re-publishes labels with different letter case between matrices
(``Trade partner`` / ``Trade Partner``, ``Agriculture, Forestry And Fishing``). The statistic
columns are:

- ``value_gbp_m``: value of trade, pounds sterling (millions)
- ``ci_lower_gbp_m`` and ``ci_upper_gbp_m``: 95% confidence interval, pounds sterling (millions)
- ``cv_pct``: coefficient of variation, percent
- ``n_businesses``: estimated number of businesses (NIETS02, NIETS04 and NIETS05 only; an estimate,
  so not a whole number)

Suppressed cells are ``NaN`` in every statistic column and are never imputed. Suppression is heavy
at the finest cuts (SIC 2007 divisions, countries, and industry by destination), so check
``value_gbp_m.isna()`` before summing, and do not read a sum of non-suppressed cells as a total.

Flows and destinations
----------------------
``flow`` is ``SALES`` or ``PURCH`` (purchases). ``destination`` is the trade partner code, which for
purchases means the origin:

=========  =====================================================  ==================================
Code       Published label                                        Relationship (holds in the data)
=========  =====================================================  ==================================
``ALL``    All countries                                          ``NI + EXTERN``
``NI``     Northern Ireland
``GB``     Great Britain
``IE``     Ireland
``REU``    Rest of the Europe Union (EU excluding Ireland)
``ROW``    Rest of the World (all countries outside the UK and EU)
``EXTERN`` External Sales/Purchases (outside NI)                  ``GB + IE + REU + ROW``
``EXPORT`` Exports (outside UK); sales only                       ``IE + REU + ROW``
``IMPORT`` Imports (outside UK); purchases only                   ``IE + REU + ROW``
=========  =====================================================  ==================================

``EXTERN`` includes Great Britain. ``EXPORT`` is defined for sales only and ``IMPORT`` for purchases
only; the undefined combinations (``EXPORT`` purchases, ``IMPORT`` sales) are dropped from the
output. For purchases in 2011 and 2012 the ``NI``, ``GB`` and ``EXTERN`` values are not published.

What does not add up
--------------------
``get_by_lgd`` covers only part of the NI total: the sum of the 11 districts is well below the
all-NI figure in ``get_by_industry`` in every year (about four fifths to nine tenths, depending on
year and flow). Never present a sum over districts as the NI figure. Within one district the
destination identities above do hold.

Original data source:
    https://www.nisra.gov.uk/statistics/business-statistics/broad-economy-sales-and-exports-statistics

Update Frequency: Annual
Geographic Coverage: Northern Ireland, with a Local Government District cut

Example:
    >>> from bolster.data_sources.nisra import economic_trade_statistics as niets
    >>> df = niets.get_by_partner(year="latest")
    >>> {"year", "flow", "country_code", "country", "value_gbp_m"}.issubset(df.columns)
    True
    >>> int(df["year"].nunique())
    1
"""

import logging
from typing import Final

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

from ._base import NISRADataNotFoundError, NISRAValidationError

logger = logging.getLogger(__name__)

MATRICES: Final[dict[str, str]] = {
    "partner": "NIETS01",
    "industry": "NIETS02",
    "sic2": "NIETS03",
    "size_band": "NIETS04",
    "lgd": "NIETS05",
}

FLOWS: Final[dict[str, str]] = {"SALES": "Sales", "PURCH": "Purchases"}

TRANSACTIONS: Final[dict[str, str]] = {"GOODS": "Goods", "SERVICES": "Services", "ALL": "All Transactions"}

DESTINATIONS: Final[dict[str, str]] = {
    "ALL": "All countries",
    "NI": "Northern Ireland",
    "GB": "Great Britain",
    "IE": "Ireland",
    "REU": "Rest of the Europe Union (EU excluding Ireland)",
    "ROW": "Rest of the World (all countries outside the UK and EU)",
    "EXTERN": "External Sales/Purchases (outside NI)",
    "EXPORT": "Exports (outside UK)",
    "IMPORT": "Imports (outside UK)",
}

# Flow and destination combinations the source leaves empty because they are undefined, not suppressed.
_UNDEFINED_COMBINATIONS: Final[tuple[tuple[str, str], ...]] = (("PURCH", "EXPORT"), ("SALES", "IMPORT"))

# PxStat STATISTIC code -> output column, in output order.
_STATISTICS: Final[dict[str, str]] = {
    "BESESVALUE": "value_gbp_m",
    "LOWER_CONF_INTERVAL": "ci_lower_gbp_m",
    "UPPER_CONF_INTERVAL": "ci_upper_gbp_m",
    "CV": "cv_pct",
    "BESESCOUNT": "n_businesses",
}

_YEAR_COLUMN: Final = "TLIST(A1)"

# Per matrix: (output code column, output label column, raw code column, raw label column), in output order.
_DIMENSIONS: Final[dict[str, tuple[tuple[str, str, str, str], ...]]] = {
    "partner": (
        ("flow", "flow_label", "FLOW", "Flow Label"),
        ("country_code", "country", "REU_ROW_COUNTRY", "Trade Partner"),
    ),
    "industry": (
        ("flow", "flow_label", "FLOW", "Flow Label"),
        ("transaction", "transaction_label", "TRANSACTION", "Transaction Label"),
        ("destination", "destination_label", "BROADDEST", "Trade partner"),
        ("industry_code", "industry", "RUSECTION", "Industry sector"),
    ),
    "sic2": (
        ("flow", "flow_label", "FLOW", "Flow Label"),
        ("destination", "destination_label", "BROADDEST", "Trade Partner"),
        ("sic2_code", "sic2", "SIC2", "SIC2 Label"),
    ),
    "size_band": (
        ("flow", "flow_label", "FLOW", "Flow Label"),
        ("transaction", "transaction_label", "TRANSACTION", "Transaction Label"),
        ("destination", "destination_label", "BROADDEST", "Trade partner"),
        ("size_band", "size_band_label", "SIZEBAND", "Business employment size"),
    ),
    "lgd": (
        ("flow", "flow_label", "FLOW", "Flow Label"),
        ("destination", "destination_label", "BROADDEST", "Trade partner"),
        ("lgd_code", "lgd", "LGD", "Local Government District"),
    ),
}

# The larger matrices are 15-20 MB of CSV.
_TIMEOUT_SECONDS = 180


def _resolve_column(raw: pd.DataFrame, name: str) -> str:
    """Return the actual column of ``raw`` that matches ``name`` ignoring letter case.

    PxStat re-publishes dimension labels with different case between matrices and releases, so
    columns are matched case-insensitively.

    Args:
        raw: Frame as returned by :func:`~bolster.data_sources.nisra.pxstat.read_dataset`.
        name: Expected column name.

    Returns:
        The column name as it appears in ``raw``.

    Raises:
        NISRAValidationError: If no column matches.

    Example:
        >>> _resolve_column(pd.DataFrame({"Trade partner": []}), "Trade Partner")
        'Trade partner'
    """
    wanted = name.casefold()
    matches = [c for c in raw.columns if str(c).casefold() == wanted]
    if not matches:
        raise NISRAValidationError(f"Expected a column named {name!r} (any letter case); found {list(raw.columns)}")
    return str(matches[0])


def _tidy(raw: pd.DataFrame, table: str) -> pd.DataFrame:
    """Pivot a raw NIETS matrix into one row per cell with the statistics as columns.

    Args:
        raw: Raw frame for the matrix of ``table``.
        table: Key of :data:`MATRICES`.

    Returns:
        Frame with ``year``, the code and label columns of the cut, and the statistic columns the
        matrix publishes. Undefined flow and destination combinations are removed.

    Raises:
        NISRAValidationError: If an expected column is missing, an unknown statistic appears, or
            a cell is duplicated.

    Example:
        >>> raw = pd.DataFrame({
        ...     "STATISTIC": ["BESESVALUE", "CV"], "TLIST(A1)": [2025, 2025],
        ...     "FLOW": ["SALES", "SALES"], "Flow Label": ["Sales", "Sales"],
        ...     "REU_ROW_COUNTRY": ["USA", "USA"], "Trade Partner": ["USA", "USA"], "VALUE": [1.5, 9.0],
        ... })
        >>> tidy = _tidy(raw, "partner")
        >>> tidy[["year", "country_code", "value_gbp_m", "cv_pct"]].to_dict("records")
        [{'year': 2025, 'country_code': 'USA', 'value_gbp_m': 1.5, 'cv_pct': 9.0}]
    """
    dimensions = _DIMENSIONS[table]
    year_col = _resolve_column(raw, _YEAR_COLUMN)
    stat_col = _resolve_column(raw, "STATISTIC")
    value_col = _resolve_column(raw, "VALUE")

    unknown = set(raw[stat_col].dropna().unique()) - set(_STATISTICS)
    if unknown:
        raise NISRAValidationError(f"{MATRICES[table]} has unexpected statistics {sorted(unknown)}")

    columns: dict[str, pd.Series] = {"year": pd.to_numeric(raw[year_col], errors="raise").astype(int)}
    index_columns = ["year"]
    for code_out, label_out, code_raw, label_raw in dimensions:
        columns[code_out] = raw[_resolve_column(raw, code_raw)].astype(str)
        columns[label_out] = raw[_resolve_column(raw, label_raw)].astype(str)
        index_columns += [code_out, label_out]
    columns["statistic"] = raw[stat_col]
    columns["value"] = raw[value_col]
    long = pd.DataFrame(columns)

    if long.duplicated(index_columns + ["statistic"]).any():
        raise NISRAValidationError(f"{MATRICES[table]} has more than one row for the same cell and statistic")

    wide = long.set_index(index_columns + ["statistic"])["value"].unstack("statistic")
    wide.columns.name = None
    present = [code for code in _STATISTICS if code in wide.columns]
    wide = wide[present].rename(columns=_STATISTICS).reset_index()

    if "destination" in wide.columns:
        undefined = pd.Series(False, index=wide.index)
        for flow, destination in _UNDEFINED_COMBINATIONS:
            undefined |= (wide["flow"] == flow) & (wide["destination"] == destination)
        wide = wide[~undefined]

    sort_columns = ["year"] + [code_out for code_out, _, _, _ in dimensions]
    return wide.sort_values(sort_columns).reset_index(drop=True)


def _normalise_flow(flow: str | None) -> str | None:
    """Return the ``FLOW`` code for ``flow``, or ``None`` for no filter.

    Args:
        flow: ``"SALES"``, ``"PURCH"``, or the words ``"sales"`` and ``"purchases"``, in any case.

    Raises:
        ValueError: If ``flow`` is not recognised.

    Example:
        >>> _normalise_flow("purchases")
        'PURCH'
    """
    if flow is None:
        return None
    word = flow.strip().casefold()
    if word in ("sales", "sale"):
        return "SALES"
    if word in ("purch", "purchases", "purchase"):
        return "PURCH"
    raise ValueError(f"flow must be 'sales' or 'purchases' (codes {list(FLOWS)}), got {flow!r}")


def _normalise_destination(destination: str | None) -> str | None:
    """Return the ``BROADDEST`` code for ``destination``, or ``None`` for no filter.

    Raises:
        ValueError: If ``destination`` is not one of :data:`DESTINATIONS`.

    Example:
        >>> _normalise_destination("ie")
        'IE'
    """
    if destination is None:
        return None
    code = destination.strip().upper()
    if code not in DESTINATIONS:
        raise ValueError(f"destination must be one of {list(DESTINATIONS)}, got {destination!r}")
    return code


def _normalise_transaction(transaction: str | None) -> str | None:
    """Return the ``TRANSACTION`` code for ``transaction``, or ``None`` for no filter.

    Raises:
        ValueError: If ``transaction`` is not one of :data:`TRANSACTIONS`.

    Example:
        >>> _normalise_transaction("goods")
        'GOODS'
    """
    if transaction is None:
        return None
    code = transaction.strip().upper()
    if code not in TRANSACTIONS:
        raise ValueError(f"transaction must be one of {list(TRANSACTIONS)}, got {transaction!r}")
    return code


def latest_year(df: pd.DataFrame) -> int:
    """Return the most recent ``year`` in a frame returned by one of the getters.

    Args:
        df: A frame with a ``year`` column.

    Raises:
        NISRADataNotFoundError: If the frame has no rows.

    Example:
        >>> latest_year(pd.DataFrame({"year": [2023, 2025, 2024]}))
        2025
    """
    if df.empty:
        raise NISRADataNotFoundError("No NIETS rows to take a latest year from")
    return int(df["year"].max())


def _select_year(df: pd.DataFrame, year: int | str | None, matrix: str) -> pd.DataFrame:
    """Restrict ``df`` to ``year``; ``"latest"`` means the newest year in the matrix.

    Raises:
        NISRADataNotFoundError: If the requested year is not in the matrix. No other year is served.
        ValueError: If ``year`` is a string other than ``"latest"``.

    Example:
        >>> frame = pd.DataFrame({"year": [2024, 2025]})
        >>> _select_year(frame, "latest", "NIETS01")["year"].tolist()
        [2025]
    """
    if year is None:
        return df
    available = sorted(int(y) for y in df["year"].unique())
    if isinstance(year, str):
        if year.strip().casefold() != "latest":
            raise ValueError(f"year must be an integer, 'latest' or None, got {year!r}")
        wanted = available[-1]
    else:
        wanted = int(year)
    if wanted not in available:
        raise NISRADataNotFoundError(
            f"{matrix} has no data for {wanted}; it covers {available[0]} to {available[-1]}. No other year is substituted."
        )
    logger.info("%s: serving %d", matrix, wanted)
    return df[df["year"] == wanted]


def _get(
    table: str,
    year: int | str | None,
    flow: str | None,
    destination: str | None = None,
    transaction: str | None = None,
) -> pd.DataFrame:
    """Read, pivot and filter one matrix.

    Raises:
        ValueError: On an unrecognised filter value, or a flow that the destination does not exist for.
        NISRADataNotFoundError: If ``year`` is not in the matrix.
        NISRAValidationError: If the matrix does not have the expected shape.
    """
    flow_code = _normalise_flow(flow)
    destination_code = _normalise_destination(destination)
    transaction_code = _normalise_transaction(transaction)
    for undefined_flow, undefined_destination in _UNDEFINED_COMBINATIONS:
        if destination_code == undefined_destination and flow_code == undefined_flow:
            defined_for = "sales" if undefined_destination == "EXPORT" else "purchases"
            raise ValueError(f"destination {undefined_destination} is defined for {defined_for} only")

    matrix = MATRICES[table]
    df = _tidy(read_dataset(matrix, timeout=_TIMEOUT_SECONDS), table)
    df = _select_year(df, year, matrix)
    if flow_code is not None:
        df = df[df["flow"] == flow_code]
    if destination_code is not None:
        df = df[df["destination"] == destination_code]
    if transaction_code is not None:
        df = df[df["transaction"] == transaction_code]
    return df.reset_index(drop=True)


def get_by_partner(year: int | str | None = None, flow: str | None = None) -> pd.DataFrame:
    """Sales and purchases by country of the trade partner outside the UK (NIETS01).

    Args:
        year: A year, ``"latest"`` for the newest year, or ``None`` for every year (2011 onwards).
        flow: ``"sales"``, ``"purchases"`` or ``None`` for both.

    Returns:
        One row per year, flow and country: ``year``, ``flow``, ``flow_label``, ``country_code``
        (ISO 3166 alpha-3), ``country``, ``value_gbp_m``, ``ci_lower_gbp_m``, ``ci_upper_gbp_m``,
        ``cv_pct``. About 75 countries are published and many are suppressed in a given year.

    Raises:
        NISRADataNotFoundError: If ``year`` is not published; no other year is served.
        ValueError: If ``flow`` or ``year`` is not recognised.

    Example:
        >>> df = get_by_partner(year="latest", flow="sales")
        >>> set(df["flow"])
        {'SALES'}
    """
    return _get("partner", year, flow)


def get_by_industry(
    year: int | str | None = None,
    flow: str | None = None,
    destination: str | None = None,
    transaction: str | None = None,
) -> pd.DataFrame:
    """Sales and purchases by destination, goods or services, and industry section (NIETS02).

    Downloads about 15 MB.

    Args:
        year: A year, ``"latest"`` for the newest year, or ``None`` for every year (2011 onwards).
        flow: ``"sales"``, ``"purchases"`` or ``None`` for both.
        destination: A code from :data:`DESTINATIONS`, or ``None`` for all of them.
        transaction: ``"GOODS"``, ``"SERVICES"``, ``"ALL"`` or ``None`` for all three.

    Returns:
        ``year``, ``flow``, ``flow_label``, ``transaction``, ``transaction_label``, ``destination``,
        ``destination_label``, ``industry_code`` (``ALL`` or ``A`` to ``S``; there is no K or O),
        ``industry`` and the five statistic columns (including ``n_businesses``).

    Raises:
        NISRADataNotFoundError: If ``year`` is not published; no other year is served.
        ValueError: If a filter is not recognised, or ``destination`` is undefined for ``flow``.

    Example:
        >>> df = get_by_industry(year="latest", flow="sales", destination="ALL", transaction="ALL")  # doctest: +SKIP
        >>> bool(df["value_gbp_m"].notna().any())  # doctest: +SKIP
        True
    """
    return _get("industry", year, flow, destination, transaction)


def get_by_sic2(
    year: int | str | None = None,
    flow: str | None = None,
    destination: str | None = None,
) -> pd.DataFrame:
    """Sales and purchases by destination and SIC 2007 two-digit division (NIETS03).

    Downloads about 19 MB. Close to half of the values are suppressed.

    Args:
        year: A year, ``"latest"`` for the newest year, or ``None`` for every year (2011 onwards).
        flow: ``"sales"``, ``"purchases"`` or ``None`` for both.
        destination: A code from :data:`DESTINATIONS`, or ``None`` for all of them.

    Returns:
        ``year``, ``flow``, ``flow_label``, ``destination``, ``destination_label``, ``sic2_code``
        (``ALL`` or a two-digit division), ``sic2`` and ``value_gbp_m``, ``ci_lower_gbp_m``,
        ``ci_upper_gbp_m``, ``cv_pct``. There is no ``n_businesses`` in this matrix.

    Raises:
        NISRADataNotFoundError: If ``year`` is not published; no other year is served.
        ValueError: If a filter is not recognised, or ``destination`` is undefined for ``flow``.

    Example:
        >>> df = get_by_sic2(year="latest", flow="sales", destination="ALL")  # doctest: +SKIP
        >>> "sic2_code" in df.columns  # doctest: +SKIP
        True
    """
    return _get("sic2", year, flow, destination)


def get_by_size_band(
    year: int | str | None = None,
    flow: str | None = None,
    destination: str | None = None,
    transaction: str | None = None,
) -> pd.DataFrame:
    """Sales and purchases by destination, goods or services, and business employment size band (NIETS04).

    Args:
        year: A year, ``"latest"`` for the newest year, or ``None`` for every year (2011 onwards).
        flow: ``"sales"``, ``"purchases"`` or ``None`` for both.
        destination: A code from :data:`DESTINATIONS`, or ``None`` for all of them.
        transaction: ``"GOODS"``, ``"SERVICES"``, ``"ALL"`` or ``None`` for all three.

    Returns:
        ``year``, ``flow``, ``flow_label``, ``transaction``, ``transaction_label``, ``destination``,
        ``destination_label``, ``size_band`` (``0_9``, ``10_49``, ``50_249``, ``250+`` or ``ALL``),
        ``size_band_label`` and the five statistic columns. The four bands add up to ``ALL``.

    Raises:
        NISRADataNotFoundError: If ``year`` is not published; no other year is served.
        ValueError: If a filter is not recognised, or ``destination`` is undefined for ``flow``.

    Example:
        >>> df = get_by_size_band(year="latest", flow="sales", destination="ALL", transaction="ALL")  # doctest: +SKIP
        >>> sorted(df["size_band"])  # doctest: +SKIP
        ['0_9', '10_49', '250+', '50_249', 'ALL']
    """
    return _get("size_band", year, flow, destination, transaction)


def get_by_lgd(
    year: int | str | None = None,
    flow: str | None = None,
    destination: str | None = None,
) -> pd.DataFrame:
    """Sales and purchases by destination and Local Government District (NIETS05).

    The 11 districts do not add up to the NI total (see the module docstring); do not present
    their sum as the NI figure.

    Args:
        year: A year, ``"latest"`` for the newest year, or ``None`` for every year (2011 onwards).
        flow: ``"sales"``, ``"purchases"`` or ``None`` for both.
        destination: A code from :data:`DESTINATIONS`, or ``None`` for all of them.

    Returns:
        ``year``, ``flow``, ``flow_label``, ``destination``, ``destination_label``, ``lgd_code``
        (``N09000001`` to ``N09000011``), ``lgd`` and the five statistic columns.

    Raises:
        NISRADataNotFoundError: If ``year`` is not published; no other year is served.
        ValueError: If a filter is not recognised, or ``destination`` is undefined for ``flow``.

    Example:
        >>> df = get_by_lgd(year="latest", flow="sales", destination="ALL")  # doctest: +SKIP
        >>> int(df["lgd_code"].nunique())  # doctest: +SKIP
        11
    """
    return _get("lgd", year, flow, destination)


def get_latest_data(table: str = "industry", force_refresh: bool = False) -> pd.DataFrame:
    """Return the newest year of one NIETS cut.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored: PxStat is called
        directly with no local cache layer.

    Args:
        table: One of ``"partner"``, ``"industry"``, ``"sic2"``, ``"size_band"`` or ``"lgd"``.
        force_refresh: Ignored.

    Returns:
        The frame of the chosen getter for its newest year; read ``year`` to see which year it is.

    Raises:
        ValueError: If ``table`` is not one of the supported values.

    Example:
        >>> latest_year(get_latest_data("partner")) >= 2025
        True
    """
    getters = {
        "partner": get_by_partner,
        "industry": get_by_industry,
        "sic2": get_by_sic2,
        "size_band": get_by_size_band,
        "lgd": get_by_lgd,
    }
    if table not in getters:
        raise ValueError(f"table must be one of {list(getters)}, got {table!r}")
    return getters[table](year="latest")


def validate_data(df: pd.DataFrame, table: str) -> bool:
    """Validate the integrity of a frame returned by one of the getters.

    Checks that the frame is not empty, has the columns of ``table``, that no value or coefficient of
    variation is negative, and that each non-suppressed confidence interval brackets its value. The
    lower confidence bound itself can be negative and is not checked.

    Args:
        df: Frame returned by a getter.
        table: The key of :data:`MATRICES` that produced it.

    Returns:
        ``True`` if validation passes, ``False`` otherwise (the reason is logged).

    Example:
        >>> validate_data(pd.DataFrame(), "partner")
        False
    """
    if table not in MATRICES:
        logger.warning("Unknown NIETS table: %s", table)
        return False
    if df is None or df.empty:
        logger.warning("NIETS %s frame is empty", table)
        return False

    required = ["year", *(c for code_out, label_out, _, _ in _DIMENSIONS[table] for c in (code_out, label_out))]
    required += ["value_gbp_m", "ci_lower_gbp_m", "ci_upper_gbp_m", "cv_pct"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("NIETS %s frame is missing columns: %s", table, missing)
        return False

    # The lower confidence bound is not checked: it is negative whenever the interval is wide relative to the value.
    for column in ("value_gbp_m", "cv_pct"):
        if (df[column] < 0).any():
            logger.warning("NIETS %s has negative values in %s", table, column)
            return False
    published = df.dropna(subset=["value_gbp_m", "ci_lower_gbp_m", "ci_upper_gbp_m"])
    if (
        (published["ci_lower_gbp_m"] > published["value_gbp_m"])
        | (published["ci_upper_gbp_m"] < published["value_gbp_m"])
    ).any():
        logger.warning("NIETS %s has a confidence interval that does not bracket its value", table)
        return False
    return True
