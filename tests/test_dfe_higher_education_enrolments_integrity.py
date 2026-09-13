"""Integrity tests for the DfE Higher Education Enrolments module.

Validates real data quality and structure using live downloads. All tests
use real data (no mocks) with ``scope="class"`` fixtures to minimise
network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.dfe import higher_education_enrolments as enrolments
from bolster.data_sources.dfe._base import DfEValidationError

_MODE_COLUMNS = {"mode", "year"}


@pytest.mark.network
class TestWorkbookDiscovery:
    """URL discovery for the current edition."""

    def test_workbook_url_is_xlsx(self):
        url = enrolments.get_workbook_url()
        assert url.endswith(".xlsx")

    def test_workbook_url_is_economy_ni_domain(self):
        from urllib.parse import urlparse

        host = urlparse(enrolments.get_workbook_url()).hostname
        assert host is not None
        assert host == "www.economy-ni.gov.uk" or host.endswith(".economy-ni.gov.uk")


@pytest.mark.network
class TestNiDomiciledEnrolments:
    """Table 1: NI-domiciled students enrolled at any UK HEI."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return enrolments.get_ni_domiciled_enrolments()

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
        # Counts are rounded to the nearest 5, so allow a small tolerance.
        assert (abs(full_time + part_time - total) <= 10).all()

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total_total"].dropna() >= 0).all()

    def test_ni_heis_enrolment_never_exceeds_total(self, df: pd.DataFrame):
        both = df.dropna(subset=["total_total", "ni_heis_incl_ni_ou"])
        assert (both["ni_heis_incl_ni_ou"] <= both["total_total"]).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert enrolments.validate_data(df) is True


@pytest.mark.network
class TestNiHeiEnrolments:
    """Table 8: all enrolments at NI's own HEIs, by domicile."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return enrolments.get_ni_hei_enrolments()

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
        assert (abs(full_time + part_time - total) <= 10).all()

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
        assert enrolments.validate_data(df) is True


class TestParseWideTable:
    """Behaviour of the generic cross-tab parser (no network required)."""

    def _make_sheet(self) -> pd.DataFrame:
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
            ["Mode and Year", "X", "Y", "X", None, "Extra"],
            ["Full-time", None, None, None, None, None],
            ["2020/21", 10, 20, 30, None, 5],
            ["2021/22", 11, 21, 31, None, 6],
            ["Total", None, None, None, None, None],
            ["2020/21", 10, 20, 30, None, 5],
            ["2021/22", 11, 21, 31, None, 6],
            ["Source: Example", None, None, None, None, None],
        ]
        return pd.DataFrame(rows)

    def test_group_labels_combine_with_sub_labels(self, tmp_path):
        sheet = self._make_sheet()
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            sheet.to_excel(writer, sheet_name="Sheet1", header=False, index=False)

        from bolster.data_sources.dfe.higher_education_enrolments import _parse_wide_table

        table = _parse_wide_table(path, "Sheet1")
        assert "group_a_x" in table.columns
        assert "group_b_x" in table.columns

    def test_ungrouped_trailing_column_keeps_own_label(self, tmp_path):
        sheet = self._make_sheet()
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            sheet.to_excel(writer, sheet_name="Sheet1", header=False, index=False)

        from bolster.data_sources.dfe.higher_education_enrolments import _parse_wide_table

        table = _parse_wide_table(path, "Sheet1")
        # "Extra" follows a blank-sub-label gap, so it must not inherit "Group B".
        assert "extra" in table.columns
        assert "group_b_extra" not in table.columns

    def test_modes_and_years_parsed(self, tmp_path):
        sheet = self._make_sheet()
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            sheet.to_excel(writer, sheet_name="Sheet1", header=False, index=False)

        from bolster.data_sources.dfe.higher_education_enrolments import _parse_wide_table

        table = _parse_wide_table(path, "Sheet1")
        assert set(table["mode"]) == {"full_time", "total"}
        assert set(table["year"]) == {"2020/21", "2021/22"}
        assert len(table) == 4

    def test_footer_text_stops_parsing(self, tmp_path):
        sheet = self._make_sheet()
        path = tmp_path / "test.xlsx"
        with pd.ExcelWriter(path) as writer:
            sheet.to_excel(writer, sheet_name="Sheet1", header=False, index=False)

        from bolster.data_sources.dfe.higher_education_enrolments import _parse_wide_table

        table = _parse_wide_table(path, "Sheet1")
        assert not table.isin(["Source: Example"]).any().any()


class TestCleanColumn:
    """Behaviour of the column-name normaliser (no network required)."""

    def test_simple_combination(self):
        from bolster.data_sources.dfe.higher_education_enrolments import _clean_column

        assert _clean_column("First degree NI") == "first_degree_ni"

    def test_parens_and_digits(self):
        from bolster.data_sources.dfe.higher_education_enrolments import _clean_column

        assert _clean_column("OU(1)") == "ou_1"

    def test_trailing_whitespace(self):
        from bolster.data_sources.dfe.higher_education_enrolments import _clean_column

        assert _clean_column("Postgraduate  Total") == "postgraduate_total"


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(DfEValidationError):
            enrolments.validate_data(pd.DataFrame())

    def test_rejects_missing_mode_year_columns(self):
        with pytest.raises(DfEValidationError):
            enrolments.validate_data(pd.DataFrame({"total_total": [100]}))

    def test_rejects_no_data_columns(self):
        df = pd.DataFrame({"mode": ["total"], "year": ["2024/25"]})
        with pytest.raises(DfEValidationError):
            enrolments.validate_data(df)

    def test_rejects_all_null_data(self):
        df = pd.DataFrame({"mode": ["total"], "year": ["2024/25"], "total_total": [None]})
        with pytest.raises(DfEValidationError):
            enrolments.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"mode": ["total"], "year": ["2024/25"], "total_total": [65695]})
        assert enrolments.validate_data(df) is True
