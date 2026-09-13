"""Integrity tests for the DfE Higher Level Apprenticeships module.

Validates real data quality and structure using live downloads. All tests
use real data (no mocks) with ``scope="class"`` fixtures to minimise
network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.dfe import higher_level_apprenticeships as hla
from bolster.data_sources.dfe._base import DfEDataNotFoundError, DfEValidationError


@pytest.mark.network
class TestWorkbookDiscovery:
    """URL discovery for the current edition."""

    def test_workbook_url_is_xlsx(self):
        url = hla.get_workbook_url()
        assert url.endswith(".xlsx")

    def test_workbook_url_is_economy_ni_domain(self):
        from urllib.parse import urlparse

        host = urlparse(hla.get_workbook_url()).hostname
        assert host is not None
        assert host == "www.economy-ni.gov.uk" or host.endswith(".economy-ni.gov.uk")


@pytest.mark.network
class TestListTables:
    """The full table catalogue."""

    @pytest.fixture(scope="class")
    def tables(self) -> pd.DataFrame:
        return hla.list_tables()

    def test_expected_columns(self, tables: pd.DataFrame):
        assert {"table_id", "sheet_name", "title"}.issubset(tables.columns)

    def test_twenty_nine_tables(self, tables: pd.DataFrame):
        assert len(tables) == 29

    def test_notes_sheet_excluded(self, tables: pd.DataFrame):
        assert "Notes" not in set(tables["table_id"])

    def test_all_four_series_present(self, tables: pd.DataFrame):
        prefixes = {table_id[0] for table_id in tables["table_id"]}
        assert prefixes == {"A", "B", "C", "S"}

    def test_a1_present(self, tables: pd.DataFrame):
        assert "A1" in set(tables["table_id"])

    def test_table_ids_unique(self, tables: pd.DataFrame):
        assert not tables["table_id"].duplicated().any()

    def test_titles_have_notes_stripped(self, tables: pd.DataFrame):
        assert not tables["title"].str.contains(r"\[notes?", case=False, regex=True).any()


@pytest.mark.network
class TestGetStarts:
    """Table A2: HLA starts by sex."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return hla.get_starts()

    def test_expected_categories(self, df: pd.DataFrame):
        assert set(df["category"]) == {"Female", "Male", "Total"}

    def test_female_plus_male_equals_total(self, df: pd.DataFrame):
        year_columns = [c for c in df.columns if c != "category"]
        female = df[df["category"] == "Female"][year_columns].iloc[0]
        male = df[df["category"] == "Male"][year_columns].iloc[0]
        total = df[df["category"] == "Total"][year_columns].iloc[0]
        assert ((female + male) == total).all()

    def test_counts_non_negative(self, df: pd.DataFrame):
        year_columns = [c for c in df.columns if c != "category"]
        assert (df[year_columns].dropna(how="all") >= 0).all().all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert hla.validate_data(df) is True


@pytest.mark.network
class TestGetParticipants:
    """Table B2: HLA participants by sex."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return hla.get_participants()

    def test_expected_categories(self, df: pd.DataFrame):
        assert set(df["category"]) == {"Female", "Male", "Total"}

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert hla.validate_data(df) is True


@pytest.mark.network
class TestGetQualifiers:
    """Table C1: HLA qualifiers by academic year."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return hla.get_qualifiers()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {"category", "qualified_hla_students_no"}.issubset(df.columns)

    def test_five_years(self, df: pd.DataFrame):
        assert len(df) == 5

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["qualified_hla_students_no"].dropna() >= 0).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert hla.validate_data(df) is True


@pytest.mark.network
class TestGetTableVariety:
    """get_table() across a sample of differently-shaped sheets."""

    @pytest.mark.parametrize("table_id", ["A1", "A6", "A8", "B1", "S1", "S3"])
    def test_returns_category_and_data_columns(self, table_id):
        df = hla.get_table(table_id)
        assert "category" in df.columns
        assert len(df.columns) > 1
        assert hla.validate_data(df) is True

    def test_case_insensitive_table_id(self):
        upper = hla.get_table("A2")
        lower = hla.get_table("a2")
        pd.testing.assert_frame_equal(upper, lower)

    def test_lgd_breakdown_has_eleven_districts_plus_total(self):
        df = hla.get_table("A8")
        # 11 LGDs + Total row.
        assert len(df) == 12

    def test_lgd_names_include_comma_containing_district(self):
        df = hla.get_table("A8")
        assert "Armagh City, Banbridge and Craigavon" in set(df["category"])

    def test_supplementary_table_has_number_and_percentage(self):
        df = hla.get_table("S1")
        assert {"category", "number", "percentage"}.issubset(df.columns)


@pytest.mark.network
class TestErrorHandling:
    """Invalid inputs."""

    def test_unknown_table_id_raises(self):
        with pytest.raises(DfEDataNotFoundError):
            hla.get_table("Z99")


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(DfEValidationError):
            hla.validate_data(pd.DataFrame())

    def test_rejects_missing_category_column(self):
        with pytest.raises(DfEValidationError):
            hla.validate_data(pd.DataFrame({"2024_25_no": [100]}))

    def test_rejects_no_data_columns(self):
        df = pd.DataFrame({"category": ["Total"]})
        with pytest.raises(DfEValidationError):
            hla.validate_data(df)

    def test_rejects_all_null_data(self):
        df = pd.DataFrame({"category": ["Total"], "2024_25_no": [None]})
        with pytest.raises(DfEValidationError):
            hla.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"category": ["Total"], "2024_25_no": [390]})
        assert hla.validate_data(df) is True


class TestCleanColumn:
    """Behaviour of the column-name normaliser (no network required)."""

    def test_simple_year_number(self):
        from bolster.data_sources.dfe.higher_level_apprenticeships import _clean_column

        assert _clean_column("2024/25 (No.)") == "2024_25_no"

    def test_sex_combination(self):
        from bolster.data_sources.dfe.higher_level_apprenticeships import _clean_column

        assert _clean_column("2020/21 Female (No.)") == "2020_21_female_no"
