"""PSNI Security Situation Statistics.

Provides access to PSNI's monthly Security Situation Statistics: deaths,
security-related incidents, paramilitary style attacks, firearms/explosives
finds, and Terrorism Act arrests in Northern Ireland, maintained since 1969
("throughout the Troubles and up to the present day").

Each series starts as annual-only figures and later switches to monthly
reporting at a point specific to that series (Terrorism Act arrests never
had an annual-only era; deaths never switched to monthly). A ``resolution``
column marks which applies to each row.

Data Source:
    https://www.psni.police.uk/official-statistics/security-situation-statistics

    The accompanying Excel workbook is discovered at runtime by scraping this
    page for the current edition's ``.xls`` link, since both the filename and
    its containing path change every month.

    .. note::
        The article page itself sits behind Cloudflare and can return a 403
        to requests from a low-reputation IP even though the site is not
        actually blocking automated access in general -- confirmed via a
        GitHub Actions probe getting a clean 200 on this exact page. The
        workbook's own download URL (under ``sites/default/files/...``) has
        no such issue once known. If :func:`find_latest_workbook_url` fails
        with a 403 in one environment, check whether it is an egress-
        reputation effect (retry from CI) before concluding the source is
        unreachable.

Update Frequency: Monthly, with a finalised annual edition each May
Geographic Coverage: Northern Ireland, with a current-financial-year
    breakdown by the 11 policing districts (aligned with LGDs)
Reference Period: 1969 (1973 for paramilitary style attacks; 2001 for
    Terrorism Act arrests) to present

Example:
    >>> from bolster.data_sources.psni import security_situation
    >>> df = security_situation.get_deaths()  # doctest: +SKIP
    >>> df.year.min()  # doctest: +SKIP
    1969
"""

import datetime as dt
import logging
import re
from typing import cast
from urllib.parse import urljoin

import bs4
import pandas as pd

from bolster.utils.web import session

from ._base import (
    PSNIDataNotFoundError,
    PSNIValidationError,
    download_file,
    get_lgd_code,
)

logger = logging.getLogger(__name__)

SECURITY_SITUATION_URL = "https://www.psni.police.uk/official-statistics/security-situation-statistics"

_CACHE_TTL_HOURS = 24 * 7

# Sheet name -> parsing config. `topic` names the key used in get_all_data();
# `header_rows` is 1 for a flat header, 2 for a grouped header (the group
# label spans several columns and must be forward-filled before combining
# with the sub-label row); `rename` maps the (possibly group-combined)
# header text to the column name in the returned frame -- any header not
# present in `rename` is dropped (this excludes footnote-reference columns).
_SHEET_CONFIG: dict[str, dict] = {
    "Deaths due Security Situation": {
        "topic": "deaths",
        "header_rows": 1,
        "rename": {
            "Police": "police",
            "Police Reserve": "police_reserve",
            "Army": "army",
            "Ulster Defence Regiment / Royal Irish Regiment": "udr_rir",
            "Civilian": "civilian",
            "TOTAL": "total",
        },
    },
    "Security Related Incidents": {
        "topic": "security_related_incidents",
        "header_rows": 1,
        "rename": {
            "Shooting Incidents": "shooting_incidents",
            "Bombing Incidents": "bombing_incidents",
            "Bombings - Devices Used": "bombing_devices_used",
            "Incendiaries - Incidents": "incendiary_incidents",
            "Incendiaries - Devices Used": "incendiary_devices_used",
        },
    },
    "Paramilitary Style Attacks": {
        "topic": "paramilitary_style_attacks",
        "header_rows": 2,
        "rename": {
            "Paramilitary Style Shootings ** Total": "shootings_total",
            "Paramilitary Style Shootings ** By Loyalist Groups*": "shootings_loyalist",
            "Paramilitary Style Shootings ** By Republican Groups*": "shootings_republican",
            "Paramilitary Style Assaults ** Total": "assaults_total",
            "Paramilitary Style Assaults ** By Loyalist Groups*": "assaults_loyalist",
            "Paramilitary Style Assaults ** By Republican Groups*": "assaults_republican",
            "Paramilitary Style Assaults ** Total Casualties (Shootings and Assaults)": "total_casualties",
        },
    },
    "Firearms and Explosive finds": {
        "topic": "firearms_and_explosives_finds",
        "header_rows": 1,
        "rename": {
            "Firearms": "firearms",
            "Explosives (kgs)": "explosives_kg",
            "Ammunition": "ammunition",
        },
    },
    "Terrorism Act arrests & charges": {
        "topic": "terrorism_act_arrests",
        "header_rows": 1,
        "rename": {
            "Persons Arrested": "persons_arrested",
            "Persons Charged": "persons_charged",
        },
    },
}

_DISTRICT_RENAME = {
    "Deaths": "deaths",
    "Shooting Incidents": "shooting_incidents",
    "Bombing Incidents": "bombing_incidents",
    "Incendiary Incidents": "incendiary_incidents",
    "Casualties as a result of paramilitary style assaults": "paramilitary_assault_casualties",
    "Casualties as a result of paramilitary style shootings": "paramilitary_shooting_casualties",
    "Firearms found": "firearms_found",
    "Rounds of ammunition found": "ammunition_found",
    "Explosives found (kgs)": "explosives_found_kg",
    "Persons arrested under section 41 of the Terrorism Act": "persons_arrested",
    "Persons arrested under section 41 of the Terrorism Act and subsequently charged": "persons_charged",
}

_ANNUAL_LABEL_RE = re.compile(r"TOTAL (\d{4})$")


def find_latest_workbook_url() -> str:
    """Find the URL of the current Security Situation Statistics workbook.

    Returns:
        Absolute URL of the ``.xls`` workbook.

    Raises:
        PSNIDataNotFoundError: If the page can't be fetched or has no
            ``.xls`` link.

    Example:
        >>> find_latest_workbook_url().endswith(".xls")
        True
    """
    try:
        response = session.get(SECURITY_SITUATION_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise PSNIDataNotFoundError(f"Failed to fetch {SECURITY_SITUATION_URL}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, "html.parser")
    for link in cast("list[bs4.Tag]", soup.find_all("a", href=True)):
        href = cast("str", link["href"])
        if href.lower().endswith(".xls"):
            return urljoin(SECURITY_SITUATION_URL, href)

    raise PSNIDataNotFoundError(f"No .xls workbook link found on {SECURITY_SITUATION_URL}")


def _open_workbook(force_refresh: bool = False) -> pd.ExcelFile:
    url = find_latest_workbook_url()
    path = download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    return pd.ExcelFile(path, engine="xlrd")


def _parse_numeric(value: object) -> float | None:
    """Parse a cell value, treating ``-``/blank placeholders as missing."""
    if pd.isna(value):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if text in {"-", "", ".."}:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _detect_header_start(df: pd.DataFrame) -> int:
    """Find the first row whose label column is blank but some other column isn't.

    Every sheet leads with title/description/footnote rows (which always
    carry text in column 0) and blank separator rows (blank everywhere).
    The real header row is the first row that breaks both patterns: no
    label, but real header text elsewhere.
    """
    for i in range(len(df)):
        row = df.iloc[i]
        # Require >=2 populated columns: a lone populated cell is a
        # decorative section title (e.g. "Security Related Incidents" sits
        # by itself in column 1), not a real header with several metrics.
        if pd.isna(row.iloc[0]) and row.iloc[1:].notna().sum() >= 2:
            return i
    raise PSNIDataNotFoundError("No header row found in sheet")


def _combine_headers(df: pd.DataFrame, start: int, header_rows: int) -> list[str]:
    """Build column header strings, combining a group + sub-label row if needed."""
    if header_rows == 1:
        return [str(c).strip() if pd.notna(c) else "" for c in df.iloc[start]]

    group = df.iloc[start].ffill()
    sub = df.iloc[start + 1]
    combined = []
    for g, s in zip(group, sub, strict=False):
        g_text = str(g).strip() if pd.notna(g) else ""
        s_text = str(s).strip() if pd.notna(s) else ""
        combined.append(f"{g_text} {s_text}".strip() if g_text else s_text)
    return combined


def _classify_label(label: object) -> str | None:
    """Classify a row label as 'monthly', an annual candidate, or unclassified (drop)."""
    if isinstance(label, pd.Timestamp | dt.datetime):
        return "monthly"
    if pd.isna(label):
        return None
    if _ANNUAL_LABEL_RE.fullmatch(str(label).strip()):
        return "annual_candidate"
    return None


def _parse_series_sheet(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Parse one time-series sheet into a tidy frame per the module docstring's schema."""
    header_start = _detect_header_start(df)
    headers = _combine_headers(df, header_start, config["header_rows"])
    body = df.iloc[header_start + config["header_rows"] :].reset_index(drop=True)

    labels = body.iloc[:, 0]
    kinds = labels.map(_classify_label)

    # A "TOTAL <year>" row is a genuine annual observation only if it appears
    # before this sheet's monthly era begins; once dated rows start, every
    # subsequent "TOTAL <year>" is a derived running total to drop.
    seen_monthly = False
    resolved: list[str | None] = []
    for kind in kinds:
        if kind == "monthly":
            seen_monthly = True
            resolved.append("monthly")
        elif kind == "annual_candidate":
            resolved.append(None if seen_monthly else "annual")
        else:
            resolved.append(None)

    records = []
    for label, kind, (_, row) in zip(labels, resolved, body.iterrows(), strict=False):
        if kind is None:
            continue
        if kind == "monthly":
            date = pd.Timestamp(label).replace(day=1)
        else:
            match = _ANNUAL_LABEL_RE.fullmatch(str(label).strip())
            assert match is not None  # kind == "annual" implies _classify_label already confirmed this
            year = int(match.group(1))
            date = pd.Timestamp(year=year, month=1, day=1)

        record: dict[str, object] = {"date": date, "year": date.year, "resolution": kind}
        for col_idx, header in enumerate(headers[1:], start=1):
            name = config["rename"].get(header)
            if name:
                record[name] = _parse_numeric(row.iloc[col_idx])
        records.append(record)

    result = pd.DataFrame(records)
    if result.empty:
        raise PSNIDataNotFoundError("No data rows found in sheet")

    metric_cols = [c for c in result.columns if c not in ("date", "year", "resolution")]
    return result[result[metric_cols].notna().any(axis=1)].reset_index(drop=True)


def get_deaths(force_refresh: bool = False) -> pd.DataFrame:
    """Get deaths due to the security situation, by year (annual-only series).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``date``, ``year``, ``resolution`` (always
        ``"annual"``), ``police``, ``police_reserve``, ``army``, ``udr_rir``,
        ``civilian`` and ``total`` columns, 1969 to present.
    """
    workbook = _open_workbook(force_refresh)
    return _parse_series_sheet(
        workbook.parse("Deaths due Security Situation", header=None),
        _SHEET_CONFIG["Deaths due Security Situation"],
    )


def get_security_related_incidents(force_refresh: bool = False) -> pd.DataFrame:
    """Get shooting/bombing/incendiary incidents, annual 1969-1989 then monthly.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``date``, ``year``, ``resolution``,
        ``shooting_incidents``, ``bombing_incidents``,
        ``bombing_devices_used``, ``incendiary_incidents`` and
        ``incendiary_devices_used`` columns.
    """
    workbook = _open_workbook(force_refresh)
    return _parse_series_sheet(
        workbook.parse("Security Related Incidents", header=None),
        _SHEET_CONFIG["Security Related Incidents"],
    )


def get_paramilitary_style_attacks(force_refresh: bool = False) -> pd.DataFrame:
    """Get paramilitary-style shooting/assault casualties, annual then monthly.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``date``, ``year``, ``resolution``,
        ``shootings_total``, ``shootings_loyalist``, ``shootings_republican``,
        ``assaults_total``, ``assaults_loyalist``, ``assaults_republican`` and
        ``total_casualties`` columns.

    Note:
        Attribution (loyalist/republican) is as perceived by PSNI and does
        not necessarily indicate the involvement of a paramilitary
        organisation. Casualties resulting in death are counted as security
        related deaths (:func:`get_deaths`), not here.
    """
    workbook = _open_workbook(force_refresh)
    return _parse_series_sheet(
        workbook.parse("Paramilitary Style Attacks", header=None),
        _SHEET_CONFIG["Paramilitary Style Attacks"],
    )


def get_firearms_and_explosives_finds(force_refresh: bool = False) -> pd.DataFrame:
    """Get firearms, explosives and ammunition finds, annual then monthly.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``date``, ``year``, ``resolution``, ``firearms``,
        ``explosives_kg`` and ``ammunition`` columns.
    """
    workbook = _open_workbook(force_refresh)
    return _parse_series_sheet(
        workbook.parse("Firearms and Explosive finds", header=None),
        _SHEET_CONFIG["Firearms and Explosive finds"],
    )


def get_terrorism_act_arrests(force_refresh: bool = False) -> pd.DataFrame:
    """Get Terrorism Act section 41 arrests and charges, monthly from 2001.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``date``, ``year``, ``resolution`` (always
        ``"monthly"``), ``persons_arrested`` and ``persons_charged``
        columns. Months before the power existed (pre-February 2001) are
        absent rather than zero.
    """
    workbook = _open_workbook(force_refresh)
    return _parse_series_sheet(
        workbook.parse("Terrorism Act arrests & charges", header=None),
        _SHEET_CONFIG["Terrorism Act arrests & charges"],
    )


def _latest_district_sheet(workbook: pd.ExcelFile) -> str:
    candidates = [name for name in workbook.sheet_names if name.startswith("Breakdown by District")]
    if not candidates:
        raise PSNIDataNotFoundError("No district breakdown sheet found")
    return max(candidates, key=lambda name: name.rsplit(" ", 1)[-1])


def get_district_breakdown(force_refresh: bool = False) -> pd.DataFrame:
    """Get the current financial-year-to-date breakdown by policing district.

    Unlike the other accessors, this is a single snapshot (the current
    financial year to date), not a historical time series -- BSO/PSNI only
    publish this cut for the current and immediately prior financial year,
    and the prior year's sheet is superseded once a new financial year
    starts.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``district``, ``lgd_code`` (``None`` for the
        ``NORTHERN IRELAND`` total row) and one column per metric (see
        :data:`_DISTRICT_RENAME` for the mapping from published column
        names). The ``NORTHERN IRELAND`` row is kept, not dropped, so
        district figures can be sanity-checked against it.
    """
    workbook = _open_workbook(force_refresh)
    sheet_name = _latest_district_sheet(workbook)
    df = workbook.parse(sheet_name, header=None)

    # Unlike the time-series sheets, this sheet's own label column has a
    # header too ("District"), so _detect_header_start's "blank corner cell"
    # rule doesn't apply -- find the row that starts with "District" instead.
    header_start = next(
        (i for i in range(len(df)) if pd.notna(df.iloc[i, 0]) and str(df.iloc[i, 0]).strip() == "District"),
        None,
    )
    if header_start is None:
        raise PSNIDataNotFoundError(f"No 'District' header row found in sheet {sheet_name!r}")

    headers = [str(c).strip() if pd.notna(c) else "" for c in df.iloc[header_start]]
    body = df.iloc[header_start + 1 :].reset_index(drop=True)

    records = []
    for _, row in body.iterrows():
        district = row.iloc[0]
        if pd.isna(district):
            continue
        record: dict[str, object] = {"district": str(district).strip().replace(",", "")}
        for col_idx, header in enumerate(headers[1:], start=1):
            name = _DISTRICT_RENAME.get(header)
            if name:
                record[name] = _parse_numeric(row.iloc[col_idx])
        records.append(record)

    if not records:
        raise PSNIDataNotFoundError(f"No district rows found in sheet {sheet_name!r}")

    result = pd.DataFrame(records)
    result["lgd_code"] = result["district"].map(get_lgd_code)
    columns = ["district", "lgd_code", *[c for c in result.columns if c not in ("district", "lgd_code")]]
    return result[columns]


def get_all_data(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Get every Security Situation Statistics topic in one call.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        Mapping of topic name (see each sheet's ``topic`` in
        :data:`_SHEET_CONFIG`, plus ``"district_breakdown"``) to its frame.
    """
    workbook = _open_workbook(force_refresh)
    result = {
        config["topic"]: _parse_series_sheet(workbook.parse(sheet_name, header=None), config)
        for sheet_name, config in _SHEET_CONFIG.items()
    }
    result["district_breakdown"] = get_district_breakdown(force_refresh=force_refresh)
    return result


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a Security Situation Statistics frame is structurally sound.

    Args:
        df: A frame returned by any accessor in this module.

    Returns:
        True if the frame passes every check.

    Raises:
        PSNIValidationError: If the frame is empty or values look implausible.
    """
    if df.empty:
        raise PSNIValidationError("Security situation data is empty")

    if "resolution" in df.columns and not df["resolution"].isin(["monthly", "annual"]).all():
        raise PSNIValidationError("Unexpected resolution values found")

    if "date" in df.columns and df["date"].isna().any():
        raise PSNIValidationError("Security situation data contains unparseable dates")

    excluded = {"date", "year", "resolution", "district", "lgd_code"}
    for column in [c for c in df.columns if c not in excluded]:
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if not values.empty and (values < 0).any():
            raise PSNIValidationError(f"Negative values found in {column!r}")

    return True
