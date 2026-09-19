"""Integrity tests for the DfE Higher Education Qualifications module.

Validates real data quality and structure using live downloads. All tests
use real data (no mocks) with ``scope="class"`` fixtures to minimise
network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.dfe import higher_education_qualifications as qualifications
from bolster.data_sources.dfe._base import DfEValidationError


@pytest.mark.network
class TestWorkbookDiscovery:
    """URL discovery for the current edition."""

    def test_workbook_url_is_xlsx(self):
        url = qualifications.get_workbook_url()
        assert url.endswith(".xlsx")

    def test_workbook_url_is_economy_ni_domain(self):
        from urllib.parse import urlparse

        host = urlparse(qualifications.get_workbook_url()).hostname
        assert host is not None
        assert host == "www.economy-ni.gov.uk" or host.endswith(".economy-ni.gov.uk")


@pytest.mark.network
class TestNiDomiciledQualifications:
    """Table 1: NI-domiciled students gaining qualifications at any UK HEI."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return qualifications.get_ni_domiciled_qualifications()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "mode",
            "year",
            "first_degree_ni",
            "postgraduate_total",
            "total_total",
            "ni_heis_incl_ni_ou",
        }.issubset(df.columns)

    def test_modes_are_full_part_total(self, df: pd.DataFrame):
        assert set(df["mode"]) == {"full_time", "part_time", "total"}

    def test_year_range_starts_2015_16(self, df: pd.DataFrame):
        assert "2015/16" in set(df["year"])

    def test_ten_years_per_mode(self, df: pd.DataFrame):
        assert (df.groupby("mode").size() >= 10).all()

    def test_full_and_part_time_sum_to_total(self, df: pd.DataFrame):
        full_time = df[df["mode"] == "full_time"].set_index("year")["total_total"]
        part_time = df[df["mode"] == "part_time"].set_index("year")["total_total"]
        total = df[df["mode"] == "total"].set_index("year")["total_total"]
        # Counts are rounded to the nearest 5, so a small gap is expected;
        # unlike enrolments, qualification totals independently sourced
        # per mode compound to a larger observed gap (up to 30) than a
        # single rounding step would suggest.
        assert (abs(full_time + part_time - total) <= 40).all()

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total_total"].dropna() >= 0).all()

    def test_ni_heis_qualifications_never_exceeds_total(self, df: pd.DataFrame):
        both = df.dropna(subset=["total_total", "ni_heis_incl_ni_ou"])
        assert (both["ni_heis_incl_ni_ou"] <= both["total_total"]).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert qualifications.validate_data(df) is True


@pytest.mark.network
class TestNiHeiQualifications:
    """Table 6: all students gaining qualifications at NI's own HEIs, by domicile."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return qualifications.get_ni_hei_qualifications()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "mode",
            "year",
            "first_degree_ni",
            "total_non_eu",
            "total_total",
        }.issubset(df.columns)

    def test_modes_are_full_part_total(self, df: pd.DataFrame):
        assert set(df["mode"]) == {"full_time", "part_time", "total"}

    def test_full_and_part_time_sum_to_total(self, df: pd.DataFrame):
        full_time = df[df["mode"] == "full_time"].set_index("year")["total_total"]
        part_time = df[df["mode"] == "part_time"].set_index("year")["total_total"]
        total = df[df["mode"] == "total"].set_index("year")["total_total"]
        # See the equivalent NI-domiciled test above for why this tolerance
        # is wider than a single nearest-5 rounding step would suggest.
        assert (abs(full_time + part_time - total) <= 40).all()

    def test_domicile_components_sum_to_total(self, df: pd.DataFrame):
        components = ["total_ni", "total_gb", "total_roi", "total_other_eu", "total_non_eu"]
        total_row = df.dropna(subset=[*components, "total_total"])
        component_sum = total_row[components].sum(axis=1)
        # Five independently-rounded-to-nearest-5 components summed together
        # can compound to a larger gap than a single rounding step.
        assert (abs(component_sum - total_row["total_total"]) <= 50).all()

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total_total"].dropna() >= 0).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert qualifications.validate_data(df) is True


@pytest.mark.network
class TestQualificationsMatchEnrolmentsShape:
    """Cross-check: the qualifications workbook mirrors the enrolments workbook's layout."""

    def test_ni_domiciled_and_ni_hei_share_mode_and_year_axes(self):
        domiciled = qualifications.get_ni_domiciled_qualifications()
        ni_heis = qualifications.get_ni_hei_qualifications()
        assert set(domiciled["mode"]) == set(ni_heis["mode"])
        # Table 6 uses a differently-worded row-axis label ("Level and Year")
        # but must still parse the same years as Table 1 ("Mode and Year").
        assert set(domiciled["year"]) == set(ni_heis["year"])


class TestParseWideTable:
    """Behaviour of the generic cross-tab parser (no network required)."""

    def _make_sheet(self, row_axis_label: str = "Mode and Year") -> pd.DataFrame:
        # A minimal 2-level-group, 2-sub-column, 2-mode, 2-year sheet
        # mirroring Table 1's shape, including a genuinely blank separator
        # column (index 4) before the trailing ungrouped "Extra" column --
        # matching Table 1's real "NI HEIs (incl. NI OU)" column, which
        # follows a blank column rather than sitting directly against the
        # last group.
        rows = [
            ["Table 1: Example", None, None, None, None, None],
            [None, None, None, None, None, None],
            [None, "Group A", None, "Group B", None, None],
            [None, "Location", None, "Location", None, None],
            [row_axis_label, "X", "Y", "X", None, "Extra"],
            ["Full-time", None, None, None, None, None],
            ["2020/21", 10, 20, 30, None, 5],
            ["2021/22", 11, 21, 31, None, 6],
            ["Total", None, None, None, None, None],
            ["2020/21", 10, 20, 30, None, 5],
            ["2021/22", 11, 21, 31, None, 6],
            ["Source: Example", None, None, None, None, None],
        ]
        return pd.DataFrame(rows)

    def _write(self, sheet: pd.DataFrame, tmp_path) -> str:
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            sheet.to_excel(writer, sheet_name="Sheet1", header=False, index=False)
        return path

    def test_group_labels_combine_with_sub_labels(self, tmp_path):
        path = self._write(self._make_sheet(), tmp_path)

        table = qualifications._parse_wide_table(path, "Sheet1")
        assert "group_a_x" in table.columns
        assert "group_b_x" in table.columns

    def test_ungrouped_trailing_column_keeps_own_label(self, tmp_path):
        path = self._write(self._make_sheet(), tmp_path)

        table = qualifications._parse_wide_table(path, "Sheet1")
        # "Extra" follows a blank-sub-label gap, so it must not inherit "Group B".
        assert "extra" in table.columns
        assert "group_b_extra" not in table.columns

    def test_modes_and_years_parsed(self, tmp_path):
        path = self._write(self._make_sheet(), tmp_path)

        table = qualifications._parse_wide_table(path, "Sheet1")
        assert set(table["mode"]) == {"full_time", "total"}
        assert set(table["year"]) == {"2020/21", "2021/22"}
        assert len(table) == 4

    def test_footer_text_stops_parsing(self, tmp_path):
        path = self._write(self._make_sheet(), tmp_path)

        table = qualifications._parse_wide_table(path, "Sheet1")
        assert not table.isin(["Source: Example"]).any().any()

    def test_level_and_year_label_also_recognised(self, tmp_path):
        # Table 6 in the real workbook labels this row axis "Level and Year"
        # rather than "Mode and Year" -- same shape, different wording.
        path = self._write(self._make_sheet(row_axis_label="Level and Year"), tmp_path)

        table = qualifications._parse_wide_table(path, "Sheet1")
        assert set(table["mode"]) == {"full_time", "total"}

    def test_missing_row_axis_header_raises(self, tmp_path):
        sheet = self._make_sheet()
        sheet.iloc[4, 0] = "Something else entirely"
        path = self._write(sheet, tmp_path)

        from bolster.data_sources.dfe._base import DfEDataNotFoundError

        with pytest.raises(DfEDataNotFoundError):
            qualifications._parse_wide_table(path, "Sheet1")


class TestCleanColumn:
    """Behaviour of the column-name normaliser (no network required)."""

    def test_simple_combination(self):
        assert qualifications._clean_column("First degree NI") == "first_degree_ni"

    def test_parens_and_digits(self):
        assert qualifications._clean_column("OU(1)") == "ou_1"

    def test_trailing_whitespace(self):
        assert qualifications._clean_column("Postgraduate  Total") == "postgraduate_total"


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(DfEValidationError):
            qualifications.validate_data(pd.DataFrame())

    def test_rejects_missing_mode_year_columns(self):
        with pytest.raises(DfEValidationError):
            qualifications.validate_data(pd.DataFrame({"total_total": [100]}))

    def test_rejects_no_data_columns(self):
        df = pd.DataFrame({"mode": ["total"], "year": ["2024/25"]})
        with pytest.raises(DfEValidationError):
            qualifications.validate_data(df)

    def test_rejects_all_null_data(self):
        df = pd.DataFrame({"mode": ["total"], "year": ["2024/25"], "total_total": [None]})
        with pytest.raises(DfEValidationError):
            qualifications.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"mode": ["total"], "year": ["2024/25"], "total_total": [21720]})
        assert qualifications.validate_data(df) is True
