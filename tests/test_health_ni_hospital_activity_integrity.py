"""Integrity tests for the Inpatient and Day Case Activity (hospital_activity) module.

Validates real data quality and structure using live downloads. All tests
use real data (no mocks) with ``scope="class"`` fixtures to minimise
network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.health_ni import hospital_activity as ha
from bolster.data_sources.health_ni._base import NISRADataNotFoundError, NISRAValidationError

EXPECTED_TRUSTS = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}


@pytest.mark.network
class TestWorkbookDiscovery:
    """URL discovery for the current edition's five workbooks."""

    @pytest.fixture(scope="class")
    def urls(self) -> dict[str, str]:
        return ha.get_workbook_urls()

    def test_all_four_keys_present(self, urls: dict[str, str]):
        assert set(urls) == {"specialty", "treatment_function", "independent", "theatres"}

    def test_all_urls_are_xlsx(self, urls: dict[str, str]):
        assert all(url.endswith(".xlsx") for url in urls.values())

    def test_all_urls_are_health_ni_domain(self, urls: dict[str, str]):
        from urllib.parse import urlparse

        for url in urls.values():
            host = urlparse(url).hostname
            assert host is not None
            assert host == "www.health-ni.gov.uk" or host.endswith(".health-ni.gov.uk")

    def test_urls_are_distinct(self, urls: dict[str, str]):
        assert len(set(urls.values())) == len(urls)


@pytest.mark.network
class TestBedActivityBySpecialty:
    """The long-run pre-encompass series."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return ha.get_bed_activity_by_specialty()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "financial_year",
            "quarter_ending",
            "hsc_trust",
            "hospital",
            "programme_of_care",
            "specialty",
            "total_available_beds",
            "total_occupied_beds",
            "total_inpatients",
            "total_day_case",
        }.issubset(df.columns)

    def test_known_trusts_present(self, df: pd.DataFrame):
        assert EXPECTED_TRUSTS.issubset(set(df["hsc_trust"]))

    def test_historical_coverage_back_to_2016(self, df: pd.DataFrame):
        assert "2016-2017" in set(df["financial_year"])

    def test_quarter_ending_is_datetime(self, df: pd.DataFrame):
        assert pd.api.types.is_datetime64_any_dtype(df["quarter_ending"])

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total_occupied_beds"].dropna() >= 0).all()

    def test_occupied_not_wildly_disproportionate_to_available(self, df: pd.DataFrame):
        both = df.dropna(subset=["total_available_beds", "total_occupied_beds"])
        nonzero = both[both["total_available_beds"] > 0]
        # The workbook's own "Data Warning" sheet documents that, for a
        # quarter during which a trust transitions onto encompass, both
        # available and occupied beds are each averaged over only their own
        # partial-period day counts -- so occupied can legitimately exceed
        # available for a given row (observed up to ~1.7x in practice, for
        # ~2% of rows). This is a loose sanity bound against a parsing bug
        # (e.g. a column shift), not a strict occupancy invariant.
        assert (nonzero["total_occupied_beds"] <= nonzero["total_available_beds"] * 3).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert ha.validate_data(df) is True


@pytest.mark.network
class TestBedActivityByTreatmentFunction:
    """The encompass-era TFC series."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return ha.get_bed_activity_by_treatment_function()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "financial_year",
            "quarter_ending",
            "hsc_trust",
            "hospital",
            "programme_of_care",
            "specialty",
            "total_occupied_beds",
            "total_inpatients",
        }.issubset(df.columns)

    def test_coverage_starts_2023_24(self, df: pd.DataFrame):
        assert df["financial_year"].min() >= "2023-2024"

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total_occupied_beds"].dropna() >= 0).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert ha.validate_data(df) is True


@pytest.mark.network
class TestIndependentSectorActivity:
    """NI HSC-funded activity delivered in independent hospitals."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return ha.get_independent_sector_activity()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "financial_year",
            "hsc_trust",
            "source",
            "programme_of_care",
            "specialty",
            "inpatient",
            "day_case",
        }.issubset(df.columns)

    def test_inpatient_and_day_case_are_numeric(self, df: pd.DataFrame):
        assert pd.api.types.is_numeric_dtype(df["inpatient"])
        assert pd.api.types.is_numeric_dtype(df["day_case"])

    def test_historical_coverage_back_to_2016(self, df: pd.DataFrame):
        assert "2016-2017" in set(df["financial_year"])

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["inpatient"].dropna() >= 0).all()
        assert (df["day_case"].dropna() >= 0).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert ha.validate_data(df) is True


@pytest.mark.network
class TestTheatreUsage:
    """Operating theatre case throughput."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return ha.get_theatre_usage()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "financial_year",
            "programme_of_care",
            "hsc_trust",
            "hospital",
            "immediate",
            "urgent",
            "expedited",
            "elective",
            "total",
        }.issubset(df.columns)

    def test_urgency_components_sum_close_to_total(self, df: pd.DataFrame):
        components = df[["immediate", "urgent", "expedited", "elective"]].sum(axis=1)
        # Matches exactly for all but a handful of rows (observed: Royal
        # Victoria, Antrim, Craigavon), which have a small residual gap
        # (up to ~4% of total) against the published Total column, most
        # likely an unclassified-urgency case type not broken out in these
        # four columns. Tolerance is proportional since absolute gaps scale
        # with hospital size.
        assert (components - df["total"]).abs().le(df["total"] * 0.05).all()

    def test_historical_coverage_back_to_2016(self, df: pd.DataFrame):
        assert "2016/17" in set(df["financial_year"])

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total"].dropna() >= 0).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert ha.validate_data(df) is True


class TestParseSingleTableSheet:
    """Behaviour of the generic single-table sheet parser (no network required)."""

    def _write(self, rows: list[list], tmp_path) -> str:
        sheet = pd.DataFrame(rows)
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            sheet.to_excel(writer, sheet_name="Data", header=False, index=False)
        return path

    def test_reads_header_and_data_after_marker(self, tmp_path):
        rows = [
            ["Example Table Title", None, None],
            ["This worksheet contains one table.", None, None],
            [None, None, None],
            ["Category", "Count", None],
            ["A", 10, None],
            ["B", 20, None],
        ]
        path = self._write(rows, tmp_path)
        table = ha._parse_single_table_sheet(path)
        assert table.columns.tolist() == ["category", "count"]
        assert len(table) == 2
        assert table["count"].tolist() == [10, 20]

    def test_drops_trailing_blank_column(self, tmp_path):
        rows = [
            ["Example Table Title", None, None],
            ["This worksheet contains one table.", None, None],
            [None, None, None],
            ["Category", "Count", None],
            ["A", 10, None],
        ]
        path = self._write(rows, tmp_path)
        table = ha._parse_single_table_sheet(path)
        assert "unnamed" not in " ".join(table.columns).lower()
        assert len(table.columns) == 2

    def test_tolerates_multiple_blank_rows_before_header(self, tmp_path):
        rows = [
            ["Example Table Title", None],
            ["This worksheet contains one table.", None],
            [None, None],
            [None, None],
            ["Category", "Count"],
            ["A", 10],
        ]
        path = self._write(rows, tmp_path)
        table = ha._parse_single_table_sheet(path)
        assert table.columns.tolist() == ["category", "count"]

    def test_missing_marker_raises(self, tmp_path):
        rows = [["Nothing to see here", None], ["Category", "Count"], ["A", 10]]
        path = self._write(rows, tmp_path)
        with pytest.raises(NISRADataNotFoundError):
            ha._parse_single_table_sheet(path)

    def test_no_header_row_after_marker_raises(self, tmp_path):
        rows = [
            ["Example Table Title"],
            ["This worksheet contains one table."],
            [None],
            [None],
        ]
        path = self._write(rows, tmp_path)
        with pytest.raises(NISRADataNotFoundError, match="header row"):
            ha._parse_single_table_sheet(path)


class TestDataSheetName:
    """Behaviour of the "Data Warning" cover-sheet filter (no network required)."""

    def test_skips_data_warning_sheet(self, tmp_path):
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="Data Warning", index=False)
            pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="hs-tables-25-26", index=False)
        assert ha._data_sheet_name(path) == "hs-tables-25-26"

    def test_raises_when_only_data_warning_sheet_present(self, tmp_path):
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="Data Warning", index=False)
        with pytest.raises(NISRADataNotFoundError, match="No data sheet"):
            ha._data_sheet_name(path)


class TestCleanColumn:
    """Behaviour of the column-name normaliser (no network required)."""

    def test_simple_combination(self):
        assert ha._clean_column("HSC Trust") == "hsc_trust"

    def test_strips_trailing_footnote_marker(self):
        assert ha._clean_column("Quarter Ending*") == "quarter_ending"

    def test_lowercases_and_underscores(self):
        assert ha._clean_column("Total Available Beds") == "total_available_beds"


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(NISRAValidationError):
            ha.validate_data(pd.DataFrame())

    def test_rejects_no_numeric_columns(self):
        df = pd.DataFrame({"hsc_trust": ["Belfast"]})
        with pytest.raises(NISRAValidationError):
            ha.validate_data(df)

    def test_rejects_all_null_numeric_data(self):
        # dtype=float64 explicitly, so the column is still detected as
        # numeric (a bare [None] column infers as object dtype, which would
        # instead hit "No numeric data columns found").
        df = pd.DataFrame({"hsc_trust": ["Belfast"], "total_occupied_beds": pd.array([None], dtype="float64")})
        with pytest.raises(NISRAValidationError, match="entirely null"):
            ha.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"hsc_trust": ["Belfast"], "total_occupied_beds": [1200]})
        assert ha.validate_data(df) is True
