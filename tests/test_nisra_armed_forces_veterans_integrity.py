"""Integrity tests for the NISRA Census 2021 Armed Forces Veterans module.

Validates real data quality and structure using live downloads. All tests
use real data (no mocks) with ``scope="class"`` fixtures to minimise
network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import armed_forces_veterans as afv
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError


@pytest.mark.network
class TestListTables:
    """The full table catalogue."""

    @pytest.fixture(scope="class")
    def tables(self) -> pd.DataFrame:
        return afv.list_tables()

    def test_expected_columns(self, tables: pd.DataFrame):
        assert {"file_name", "table_number", "table_title", "geographies", "suppression"}.issubset(tables.columns)

    def test_has_many_tables(self, tables: pd.DataFrame):
        assert len(tables) > 100

    def test_table_numbers_follow_afv_pattern(self, tables: pd.DataFrame):
        assert tables["table_number"].str.fullmatch(r"AFV\d{3}[a-z]?", case=False).all()

    def test_afv001_present(self, tables: pd.DataFrame):
        assert "AFV001" in set(tables["table_number"])

    def test_table_numbers_unique(self, tables: pd.DataFrame):
        assert not tables["table_number"].duplicated().any()


@pytest.mark.network
class TestGetTablePopulation:
    """AFV001: the headline usual-resident-population table."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return afv.get_table("AFV001")

    def test_expected_columns(self, df: pd.DataFrame):
        assert {"geography_level", "geography", "geography_code", "Non-veteran", "Veteran"}.issubset(df.columns)

    def test_all_three_geography_levels(self, df: pd.DataFrame):
        assert set(df["geography_level"]) == {"NI", "LGD", "HSCT"}

    def test_ni_row_present(self, df: pd.DataFrame):
        ni = df[(df["geography_level"] == "NI") & (df["geography"] == "Northern Ireland")]
        assert len(ni) == 1

    def test_ni_veteran_headline_figure(self, df: pd.DataFrame):
        ni = df[df["geography_level"] == "NI"]
        assert int(ni["Veteran"].iloc[0]) == 37697

    def test_lgd_rows_sum_to_ni_total(self, df: pd.DataFrame):
        # Census 2021 disclosure control (cell-key perturbation) can introduce
        # a small discrepancy between geography-level aggregations of the
        # same underlying total, so this is a tolerance check, not exact.
        lgd_total = df[df["geography_level"] == "LGD"]["Veteran"].sum()
        ni_total = df[df["geography_level"] == "NI"]["Veteran"].iloc[0]
        assert abs(lgd_total - ni_total) <= 2

    def test_hsct_rows_sum_to_ni_total(self, df: pd.DataFrame):
        hsct_total = df[df["geography_level"] == "HSCT"]["Veteran"].sum()
        ni_total = df[df["geography_level"] == "NI"]["Veteran"].iloc[0]
        assert abs(hsct_total - ni_total) <= 2

    def test_eleven_lgds(self, df: pd.DataFrame):
        assert (df["geography_level"] == "LGD").sum() == 11

    def test_five_hscts(self, df: pd.DataFrame):
        assert (df["geography_level"] == "HSCT").sum() == 5

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["Veteran"].dropna() >= 0).all()
        assert (df["Non-veteran"].dropna() >= 0).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert afv.validate_data(df) is True


@pytest.mark.network
class TestGetTableGeographyFilter:
    """Filtering get_table() to a single geography level."""

    def test_ni_only(self):
        df = afv.get_table("AFV001", geography="NI")
        assert list(df["geography"]) == ["Northern Ireland"]
        assert "geography_level" not in df.columns

    def test_case_insensitive_table_number(self):
        upper = afv.get_table("AFV001", geography="NI")
        lower = afv.get_table("afv001", geography="NI")
        pd.testing.assert_frame_equal(upper, lower)

    def test_case_insensitive_geography(self):
        upper = afv.get_table("AFV001", geography="NI")
        lower = afv.get_table("AFV001", geography="ni")
        pd.testing.assert_frame_equal(upper, lower)

    def test_unavailable_geography_raises(self):
        # AFV002 ("Age - five year age bands") is NI-only per the catalogue.
        with pytest.raises(NISRADataNotFoundError):
            afv.get_table("AFV002", geography="LGD")


@pytest.mark.network
class TestGetTableSuppression:
    """A table with disclosure-control suppression (AFV009)."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return afv.get_table("AFV009", geography="LGD")

    def test_some_values_suppressed(self, df: pd.DataFrame):
        category_columns = [c for c in df.columns if c not in {"geography", "geography_code"}]
        assert df[category_columns].isna().sum().sum() > 0

    def test_geography_columns_never_suppressed(self, df: pd.DataFrame):
        assert df["geography"].notna().all()
        assert df["geography_code"].notna().all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert afv.validate_data(df) is True


@pytest.mark.network
class TestGetPopulation:
    """The get_population() convenience wrapper."""

    def test_matches_get_table_afv001(self):
        via_population = afv.get_population()
        via_table = afv.get_table("AFV001")
        pd.testing.assert_frame_equal(via_population, via_table)


@pytest.mark.network
class TestErrorHandling:
    """Invalid inputs."""

    def test_unknown_table_number_raises(self):
        with pytest.raises(NISRADataNotFoundError):
            afv.get_table("AFV999")

    def test_malformed_table_number_raises(self):
        with pytest.raises(NISRADataNotFoundError):
            afv.get_table("not-a-table")


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(NISRAValidationError):
            afv.validate_data(pd.DataFrame())

    def test_rejects_missing_geography_columns(self):
        with pytest.raises(NISRAValidationError):
            afv.validate_data(pd.DataFrame({"Veteran": [1]}))

    def test_rejects_no_category_columns(self):
        df = pd.DataFrame({"geography": ["NI"], "geography_code": ["N92000002"]})
        with pytest.raises(NISRAValidationError):
            afv.validate_data(df)

    def test_rejects_all_null_categories(self):
        df = pd.DataFrame({"geography": ["NI"], "geography_code": ["N92000002"], "Veteran": [None]})
        with pytest.raises(NISRAValidationError):
            afv.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"geography": ["NI"], "geography_code": ["N92000002"], "Veteran": [37697]})
        assert afv.validate_data(df) is True
