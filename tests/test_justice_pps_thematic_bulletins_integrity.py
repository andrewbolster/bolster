"""Integrity tests for the PPS thematic bulletins module.

Tests use real workbooks downloaded from ppsni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures. Parsing,
reconciliation and validation edge cases are covered by network-free unit
tests that build the worksheet grids by hand.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import pps_thematic_bulletins as pps
from bolster.data_sources.justice.pps_statistical_bulletin import (
    PPSDataError,
    PPSDataNotFoundError,
    PPSValidationError,
)


def _grid(text: str) -> list[list[str]]:
    """Build a worksheet grid from ``|``-separated lines, padded to a rectangle."""
    rows = [[cell.strip() for cell in line.split("|")] for line in text.strip().splitlines()]
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def _records(table: str, text: str) -> pd.DataFrame:
    rows = _grid(text)
    return pd.DataFrame(pps._parse_grid(table, rows[0][0], rows))


# Period rows: the year is stated once per group, rows are labelled, columns are named outcomes
PERIOD_ROWS = """
Table 5: Outcomes by motivation | | | | |
2023/24 and 2024/25 | | | | |
Number of persons (defendants) | | | | |
Year | Motivation | Convicted | Acquitted | All defendants
2024/25 | Race | 7 | 1 | 8
 | Sectarian | 8 | - | #
 | All defendants | 15 | 1 | 16
2023/24 | Race | 3 | 2 | 5
 | Sectarian | 3 | 0 | 3
 | All defendants | 6 | 2 | 8
Change | Number | 9 | -1 | 8
Source: PPS | | | |
"""

# Period columns: the years are the value columns, rows are grouped by a merged first column
PERIOD_COLUMNS = """
Table 4a: Decisions | | |
Number of persons | | |
 | Type of Decision | 2025/26 | 2024/25
For Sexual Offences | Indictable prosecution | 285 | 259
 | Summary prosecution | 208 | 176
 | All Decisions - For Sexual Offences | 493 | 435
For Other Offences | Summary prosecution | 70 | 58
 | All Decisions - For Other Offences | 70 | 58
 | No Prosecution | 1114 | 1141
All Decisions Issued | | 1677 | 1634
% Change | | 2.6% |
"""

# Matrix: the period is in the subtitle and rows are labelled in the first column
MATRIX = """
Table 2: Cases by type | |
2025/26 | |
Number | |
Offence | Defendants
Rape | 40
Other | 60
"""

# Three label columns and days stated in a stacked header: the older timeliness layout
DAYS = """
Table 4e: Days required | | | | |
 | | | Calendar days | Calendar days
Financial Year | Type of Decision | | Rape | Other
 | | | Median | Median
2019/20 | Prosecution | Indictable prosecution | 293 | 252
 | | Summary prosecution | - | 20
 | Diversion | | - | -
2018/19 | Prosecution | Indictable prosecution | 226 | 273
 | | Summary prosecution | - | 43
 | Diversion | | - | -
"""


class TestParseGrid:
    """The three layouts, nesting, markers and units, on hand-built grids."""

    def test_period_rows(self):
        df = _records("5", PERIOD_ROWS)
        race = df[(df["category"] == "Race") & (df["financial_year"] == "2024/25")]
        assert dict(zip(race["breakdown"], race["value"], strict=True)) == {
            "Convicted": 7,
            "Acquitted": 1,
            "All defendants": 8,
        }
        assert set(df["financial_year"]) == {"2023/24", "2024/25"}

    def test_derived_change_rows_are_not_data(self):
        df = _records("5", PERIOD_ROWS)
        assert not df["category"].str.lower().str.startswith("change").any()

    def test_suppression_markers_kept(self):
        df = _records("5", PERIOD_ROWS)
        suppressed = df[(df["category"] == "Sectarian") & (df["financial_year"] == "2024/25")]
        by_column = suppressed.set_index("breakdown")
        assert pd.isna(by_column.loc["Acquitted", "value"])
        assert by_column.loc["Acquitted", "marker"] == "-"
        assert by_column.loc["All defendants", "marker"] == "#"

    def test_period_columns_keep_leaf_rows(self):
        df = _records("4a", PERIOD_COLUMNS)
        leaf = df[(df["category"] == "Indictable prosecution") & (df["financial_year"] == "2025/26")]
        assert leaf["value"].tolist() == [285]
        assert leaf["breakdown"].tolist() == ["For Sexual Offences"]

    def test_period_columns_rows_after_group_subtotal_are_ungrouped(self):
        df = _records("4a", PERIOD_COLUMNS)
        no_prosecution = df[df["category"] == "No Prosecution"]
        assert no_prosecution["breakdown"].isna().all()

    def test_matrix_period_from_subtitle(self):
        df = _records("2", MATRIX)
        assert set(df["financial_year"]) == {"2025/26"}
        assert df.set_index("category")["value"].to_dict() == {"Rape": 40, "Other": 60}

    def test_days_from_stacked_header_with_three_label_columns(self):
        df = _records("4e", DAYS)
        assert set(df["unit"]) == {"days"}
        row = df[(df["financial_year"] == "2019/20") & (df["category"] == "Indictable prosecution")]
        assert dict(zip(row["breakdown"], row["value"], strict=True)) == {"Rape - Median": 293, "Other - Median": 252}
        assert "Diversion" in set(df["category"])

    def test_sheet_without_rows_raises(self):
        with pytest.raises(PPSDataError):
            pps._sheet_frame("hate_crime", "9", "Table 9", _grid("Table 9: Nothing | |\nNumber | "), strict=True)

    def test_unreadable_sheet_skipped_when_not_strict(self):
        assert (
            pps._sheet_frame("hate_crime", "9", "Table 9", _grid("Table 9: Nothing | |\nNumber | "), strict=False)
            is None
        )


class TestReconciliation:
    """A table that does not add up to its own totals is refused."""

    def test_consistent_tables_pass(self):
        for table, text in (("5", PERIOD_ROWS), ("4a", PERIOD_COLUMNS)):
            frame = pps._sheet_frame("hate_crime", table, f"Table {table}", _grid(text), strict=True)
            assert frame is not None

    def test_column_total_mismatch_raises(self):
        broken = PERIOD_ROWS.replace("2024/25 | Race | 7 | 1 | 8", "2024/25 | Race | 7 | 1 | 9")
        with pytest.raises(PPSValidationError, match="Race"):
            pps._sheet_frame("hate_crime", "5", "Table 5", _grid(broken), strict=True)

    def test_row_total_mismatch_raises(self):
        broken = PERIOD_ROWS.replace("All defendants | 15 | 1 | 16", "All defendants | 15 | 1 | 17")
        with pytest.raises(PPSValidationError):
            pps._sheet_frame("hate_crime", "5", "Table 5", _grid(broken), strict=True)

    def test_grand_total_mismatch_raises(self):
        broken = PERIOD_COLUMNS.replace("All Decisions Issued | | 1677", "All Decisions Issued | | 1700")
        with pytest.raises(PPSValidationError):
            pps._sheet_frame("hate_crime", "4a", "Table 4a", _grid(broken), strict=True)

    def test_mismatch_kept_with_warning_when_not_strict(self, caplog):
        broken = PERIOD_COLUMNS.replace("All Decisions Issued | | 1677", "All Decisions Issued | | 1700")
        frame = pps._sheet_frame("hate_crime", "4a", "Table 4a", _grid(broken), strict=False)
        assert frame is not None
        assert "does not reconcile" in caplog.text

    def test_suppressed_component_skips_check(self):
        """A row with a suppressed cell cannot be verified, so it cannot fail."""
        frame = pps._sheet_frame("hate_crime", "5", "Table 5", _grid(PERIOD_ROWS), strict=True)
        assert frame is not None

    def test_known_publisher_discrepancies_are_named(self):
        """Every tolerated discrepancy names the cell and says what the table shows."""
        assert pps._KNOWN_DISCREPANCIES
        for (series, table, year, label), reason in pps._KNOWN_DISCREPANCIES.items():
            assert series in pps.SERIES
            assert table and label and pps._FY_RE.search(year)
            assert len(reason) > 40


class TestValidation:
    """Unit tests for validate_data edge cases - no network calls needed."""

    @staticmethod
    def _frame(**overrides) -> pd.DataFrame:
        row = {
            "series": "hate_crime",
            "table": "hate_crime:1a",
            "title": "t",
            "financial_year": "2024/25",
            "year": 2024,
            "dimension": None,
            "category": "c",
            "breakdown": "b",
            "parent": None,
            "unit": "count",
            "value": 5.0,
            "marker": None,
        }
        row.update(overrides)
        return pd.DataFrame([row] * 3)

    def test_valid(self):
        assert pps.validate_data(self._frame(), min_records=3)

    def test_empty(self):
        with pytest.raises(PPSValidationError, match="empty"):
            pps.validate_data(pd.DataFrame())

    def test_missing_columns(self):
        with pytest.raises(PPSValidationError, match="Missing"):
            pps.validate_data(self._frame().drop(columns=["unit"]), min_records=1)

    def test_too_few_records(self):
        with pytest.raises(PPSValidationError, match="Too few"):
            pps.validate_data(self._frame(), min_records=10)

    def test_unknown_series(self):
        with pytest.raises(PPSValidationError, match="series"):
            pps.validate_data(self._frame(series="other"), min_records=1)

    def test_unknown_unit(self):
        with pytest.raises(PPSValidationError, match="units"):
            pps.validate_data(self._frame(unit="furlongs"), min_records=1)

    def test_malformed_year(self):
        with pytest.raises(PPSValidationError, match="Malformed"):
            pps.validate_data(self._frame(financial_year="2024"), min_records=1)

    def test_negative_value(self):
        with pytest.raises(PPSValidationError, match="Negative"):
            pps.validate_data(self._frame(value=-1.0), min_records=1)

    def test_proportion_out_of_range(self):
        with pytest.raises(PPSValidationError, match="Proportions"):
            pps.validate_data(self._frame(unit="proportion", value=1.5), min_records=1)


class TestDiscovery:
    """Hub scraping and workbook classification."""

    @pytest.fixture(scope="class", params=list(pps.SERIES))
    def series(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def publications(self, series):
        return pps.list_publications(series)

    def test_unknown_series(self):
        with pytest.raises(PPSDataNotFoundError):
            pps.list_publications("burglary")

    def test_publications_found(self, series, publications):
        assert len(publications) >= (9 if series == "sexual_offences" else 8)

    def test_required_keys(self, publications):
        expected = {"series", "title", "url", "financial_year", "financial_years", "year", "kind"}
        assert all(expected.issubset(p) for p in publications)

    def test_sorted_newest_first(self, publications):
        years = [p["year"] for p in publications]
        assert years == sorted(years, reverse=True)

    def test_latest_is_recent(self, publications):
        assert publications[0]["year"] >= 2024

    def test_latest_has_one_tables_workbook(self, publications):
        workbooks = pps.find_workbooks(publications[0]["url"])
        assert [w["kind"] for w in workbooks].count("tables") == 1
        assert pps.find_tables_workbook(publications[0]["url"]).endswith(".xlsx")

    def test_trends_only_for_sexual_offences(self, series, publications):
        if series == "sexual_offences":
            assert pps.find_trends_workbook(publications[0]["url"]).endswith(".xlsx")
        else:
            with pytest.raises(PPSDataNotFoundError):
                pps.find_trends_workbook(publications[0]["url"])


class TestEveryPublishedWorkbook:
    """Every workbook PPS has published must parse strictly and reconcile."""

    @pytest.fixture(scope="class", params=list(pps.SERIES))
    def parsed(self, request):
        series = request.param
        frames = {}
        for publication in pps.list_publications(series):
            workbooks = pps.find_workbooks(publication["url"])
            if not any(w["kind"] == "tables" for w in workbooks):
                continue  # PDF only
            url = pps.find_tables_workbook(publication["url"])
            frames[publication["financial_year"]] = pps.parse_tables_workbook(pps.download_file(url), series)
        return series, frames

    def test_all_parse(self, parsed):
        series, frames = parsed
        assert len(frames) >= (9 if series == "sexual_offences" else 8)
        assert all(pps.validate_data(frame, min_records=100) for frame in frames.values())

    def test_each_bulletin_states_two_years(self, parsed):
        _, frames = parsed
        for year, frame in frames.items():
            assert year in set(frame["financial_year"]), year
            assert frame["financial_year"].nunique() <= 2, year

    def test_no_sheet_lost(self, parsed):
        """A bulletin never loses a table the one before it had, beyond renumbering."""
        series, frames = parsed
        newest = max(frames)
        assert frames[newest]["table"].nunique() >= (14 if series == "sexual_offences" else 22)


class TestLatestData:
    @pytest.fixture(scope="class", params=list(pps.SERIES))
    def latest(self, request):
        return request.param, pps.get_latest_data(request.param)

    def test_columns(self, latest):
        _, df = latest
        assert list(df.columns) == pps._COLUMNS

    def test_series_column(self, latest):
        series, df = latest
        assert set(df["series"]) == {series}
        assert df["table"].str.startswith(f"{series}:").all()

    def test_valid(self, latest):
        _, df = latest
        assert pps.validate_data(df)

    def test_suppressed_values_carry_markers(self, latest):
        _, df = latest
        suppressed = df[df["value"].isna()]
        assert suppressed["marker"].notna().all()

    def test_table_filter_accepts_either_spelling(self, latest):
        series, df = latest
        key = df["table"].iloc[0].split(":")[-1]
        for spelling in (key, key.upper(), f"{series}:{key}"):
            assert set(pps.get_latest_data(series, table=spelling)["table"]) == {f"{series}:{key}"}

    def test_unknown_table_raises(self, latest):
        series, _ = latest
        with pytest.raises(PPSDataNotFoundError, match="Unknown table"):
            pps.get_latest_data(series, table="99z")

    def test_list_tables(self, latest):
        series, df = latest
        assert pps.list_tables(series) == sorted(df["table"].unique())


class TestKnownValues:
    """Figures from bulletins already published, which PPS does not change."""

    @pytest.fixture(scope="class")
    def so_2019(self):
        publication = next(p for p in pps.list_publications("sexual_offences") if p["financial_year"] == "2019/20")
        url = pps.find_tables_workbook(publication["url"])
        return pps.parse_tables_workbook(pps.download_file(url), "sexual_offences")

    @pytest.fixture(scope="class")
    def hc_2021(self):
        publication = next(p for p in pps.list_publications("hate_crime") if p["financial_year"] == "2021/22")
        url = pps.find_tables_workbook(publication["url"])
        return pps.parse_tables_workbook(pps.download_file(url), "hate_crime")

    def test_days_median(self, so_2019):
        row = so_2019[
            (so_2019["table"] == "sexual_offences:4e")
            & (so_2019["financial_year"] == "2019/20")
            & (so_2019["category"] == "Indictable prosecution")
            & (so_2019["breakdown"] == "Rape - Median")
        ]
        assert row["value"].tolist() == [293]
        assert row["unit"].tolist() == ["days"]

    def test_suppressed_cell(self, so_2019):
        row = so_2019[
            (so_2019["table"] == "sexual_offences:4a")
            & (so_2019["financial_year"] == "2018/19")
            & (so_2019["category"] == "Indictable prosecution")
            & (so_2019["breakdown"] == "For Other Offences")
        ]
        assert row["marker"].tolist() == ["-"]

    def test_decisions_leaf_rows(self, so_2019):
        rows = so_2019[(so_2019["table"] == "sexual_offences:4a") & (so_2019["financial_year"] == "2019/20")]
        leaves = rows[(rows["breakdown"] == "For Sexual Offences") & (rows["unit"] == "count")]
        values = dict(zip(leaves["category"], leaves["value"], strict=True))
        assert values["Indictable prosecution"] == 235
        assert values["Summary prosecution"] == 178
        assert values["Total Diversion"] == 21
        assert sum(v for k, v in values.items() if not k.lower().startswith("all")) == 434

    def test_published_total_error_is_tolerated_and_kept(self, hc_2021):
        """PPS's 2021/22 Table 5 states 0 defendants for Multiple Motivations; the cell is kept as published."""
        rows = hc_2021[
            (hc_2021["table"] == "hate_crime:5")
            & (hc_2021["financial_year"] == "2021/22")
            & (hc_2021["category"] == "Multiple Motivations")
        ]
        by_column = dict(zip(rows["breakdown"], rows["value"], strict=True))
        assert by_column["All defendants"] == 0
        assert by_column["Convicted of at least one offence"] == 1


class TestOverallTrends:
    @pytest.fixture(scope="class")
    def trends(self):
        return pps.get_overall_trends()

    def test_five_series(self, trends):
        assert sorted(trends["table"].unique()) == [
            "sexual_offences:trends/decisions_issued",
            "sexual_offences:trends/files_received",
            "sexual_offences:trends/outcomes_crown",
            "sexual_offences:trends/outcomes_magistrates",
            "sexual_offences:trends/timeliness",
        ]

    def test_runs_from_2015(self, trends):
        assert trends["financial_year"].min() == "2015/16"
        assert trends["year"].max() >= 2024

    def test_matches_latest_tables(self, trends):
        """The trends workbook and the bulletin's own Table 4a state the same decisions for the latest year."""
        latest = pps.get_latest_data("sexual_offences", "4a")
        year = latest["financial_year"].max()
        in_table = latest[(latest["financial_year"] == year) & (latest["category"] == "All Decisions Issued")]
        in_trends = trends[
            (trends["table"] == "sexual_offences:trends/decisions_issued")
            & (trends["financial_year"] == year)
            & (trends["category"] == "All Sexual Decisions")
        ]
        assert in_table["value"].tolist() == in_trends["value"].tolist()

    def test_valid(self, trends):
        assert pps.validate_data(trends)


class TestHistoricalData:
    @pytest.fixture(scope="class", params=list(pps.SERIES))
    def history(self, request):
        return request.param, pps.get_historical_data(request.param, max_publications=20)

    def test_no_duplicate_observations(self, history):
        _, df = history
        key = ["table", "financial_year", "dimension", "category", "breakdown", "parent"]
        assert not df.duplicated(key).any()

    def test_years_contiguous(self, history):
        _, df = history
        years = sorted(df["year"].unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_depth(self, history):
        series, df = history
        assert df["year"].min() <= (2015 if series == "sexual_offences" else 2017)

    def test_valid(self, history):
        _, df = history
        assert pps.validate_data(df)
