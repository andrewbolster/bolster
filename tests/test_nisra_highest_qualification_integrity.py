"""Integrity tests for the NISRA Highest Qualification and Participation module.

Validates real data quality and structure using live downloads. All tests
use real data (no mocks) with ``scope="class"`` fixtures to minimise
network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import highest_qualification as hq
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError

_STANDARD_BREAKDOWNS = [b for b in hq.LEVEL_2_3_BREAKDOWNS if b != "Deprivation"]


@pytest.mark.network
class TestURLDiscovery:
    """Discovery of the two workbook URLs."""

    def test_qualification_levels_url_is_xlsx(self):
        url = hq.get_qualification_levels_url()
        assert url.endswith(".xlsx")

    def test_level_2_3_url_is_xlsx(self):
        url = hq.get_level_2_3_url()
        assert url.endswith(".xlsx")

    def test_urls_are_distinct(self):
        assert hq.get_qualification_levels_url() != hq.get_level_2_3_url()

    def test_urls_are_nisra_domain(self):
        from urllib.parse import urlparse

        for url in (hq.get_qualification_levels_url(), hq.get_level_2_3_url()):
            host = urlparse(url).hostname
            assert host is not None
            assert host == "www.nisra.gov.uk" or host.endswith(".nisra.gov.uk")


@pytest.mark.network
class TestQualificationLevels:
    """Highest qualification level held, NI & UK."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return hq.get_qualification_levels()

    def test_expected_columns(self, df: pd.DataFrame):
        assert {
            "geography",
            "year",
            "no_qualifications_number",
            "no_qualifications_pct",
            "level_6_number",
            "total_number",
        }.issubset(df.columns)

    def test_geographies_are_ni_and_uk(self, df: pd.DataFrame):
        assert set(df["geography"]) == {"NI", "UK"}

    def test_year_range_starts_2015(self, df: pd.DataFrame):
        assert df["year"].min() == 2015

    def test_counts_non_negative(self, df: pd.DataFrame):
        assert (df["total_number"].dropna() >= 0).all()

    def test_qualification_bands_sum_to_total(self, df: pd.DataFrame):
        band_columns = [
            "no_qualifications_number",
            "below_level_2_number",
            "level_2_number",
            "level_3_number",
            "level_4_to_5_number",
            "level_6_number",
        ]
        ni = df[df["geography"] == "NI"].dropna(subset=band_columns + ["total_number"])
        band_sum = ni[band_columns].sum(axis=1)
        # Rounded-to-nearest-1000 components can be off by a small amount.
        assert (abs(band_sum - ni["total_number"]) <= 5000).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert hq.validate_data(df) is True


@pytest.mark.network
class TestParticipation:
    """Lifelong learning participation headline series."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return hq.get_participation()

    def test_expected_columns(self, df: pd.DataFrame):
        assert "year" in df.columns
        assert any("_ni" in c for c in df.columns)
        assert any("_uk" in c for c in df.columns)

    def test_year_range_starts_2016(self, df: pd.DataFrame):
        assert df["year"].min() == 2016

    def test_no_geography_column(self, df: pd.DataFrame):
        # NI and UK are already side by side in one row per year.
        assert "geography" not in df.columns

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert hq.validate_data(df) is True


@pytest.mark.network
class TestQualifiedLevel23:
    """Level 2+ / Level 3+ attainment breakdowns."""

    @pytest.fixture(scope="class", params=_STANDARD_BREAKDOWNS)
    def breakdown_df(self, request) -> tuple[str, pd.DataFrame]:
        return request.param, hq.get_qualified_level_2_3(request.param)

    def test_expected_columns(self, breakdown_df):
        _, df = breakdown_df
        assert {
            "area",
            "year",
            "level_2_and_above_number",
            "level_2_and_above_pct",
            "level_3_and_above_number",
            "level_3_and_above_pct",
        }.issubset(df.columns)

    def test_twelve_areas_ni_plus_eleven_lgds(self, breakdown_df):
        _, df = breakdown_df
        assert df["area"].nunique() == 12
        assert "NI" in set(df["area"])

    def test_includes_comma_containing_lgd_name(self, breakdown_df):
        # Regression check: "Armagh City, Banbridge and Craigavon" has an
        # internal comma that once broke title-based area extraction.
        _, df = breakdown_df
        assert "Armagh City, Banbridge and Craigavon" in set(df["area"])

    def test_level_3_never_exceeds_level_2(self, breakdown_df):
        _, df = breakdown_df
        both = df.dropna(subset=["level_2_and_above_pct", "level_3_and_above_pct"])
        assert (both["level_3_and_above_pct"] <= both["level_2_and_above_pct"]).all()

    def test_validate_data_passes(self, breakdown_df):
        _, df = breakdown_df
        assert hq.validate_data(df) is True


@pytest.mark.network
class TestQualifiedLevel23Deprivation:
    """The Deprivation breakdown splits by quintile, not LGD."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return hq.get_qualified_level_2_3("Deprivation")

    def test_two_quintiles(self, df: pd.DataFrame):
        assert set(df["area"]) == {"quintile 1 (most deprived)", "quintile 5 (least deprived)"}

    def test_most_deprived_has_lower_attainment(self, df: pd.DataFrame):
        most = df[df["area"] == "quintile 1 (most deprived)"]
        least = df[df["area"] == "quintile 5 (least deprived)"]
        merged = most.merge(least, on="year", suffixes=("_most", "_least"))
        assert (merged["level_3_and_above_pct_most"] < merged["level_3_and_above_pct_least"]).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert hq.validate_data(df) is True


@pytest.mark.network
class TestErrorHandling:
    """Invalid inputs."""

    def test_invalid_breakdown_raises(self):
        with pytest.raises(NISRADataNotFoundError):
            hq.get_qualified_level_2_3("Not-A-Real-Breakdown")


class TestExtractArea:
    """Behaviour of the title-parsing helper (no network required)."""

    def test_simple_geography(self):
        title = "Table 1a: Highest qualification level held, NI, aged 16 to 64, number and percentage, 2015 to 2025"
        assert hq._extract_area(title, "Table_1") == "NI"

    def test_uk_geography(self):
        title = "Table 1b: Highest qualification level held, UK, aged 16 to 64, number and percentage, 2015 to 2025"
        assert hq._extract_area(title, "Table_1") == "UK"

    def test_comma_containing_lgd_name(self):
        title = (
            "Table 1d: Level 2 and above and Level 3 and above qualifications, "
            "Armagh City, Banbridge and Craigavon, aged 16 to 64, number and percentage, 2016 to 2025"
        )
        assert hq._extract_area(title, "NI") == "Armagh City, Banbridge and Craigavon"

    def test_simple_lgd_name(self):
        title = (
            "Table 1b: Level 2 and above and Level 3 and above qualifications, "
            "Antrim and Newtownabbey, aged 16 to 64, number and percentage, 2016 to 2025"
        )
        assert hq._extract_area(title, "NI") == "Antrim and Newtownabbey"

    def test_deprivation_quintile(self):
        title = (
            "Table 5.1a: Level 2 and above and Level 3 and above qualifications in deprivation "
            "quintile 1 (most deprived), NI, aged 16 to 64, number and percentage, 2016 to 2025"
        )
        assert hq._extract_area(title, "Deprivation") == "quintile 1 (most deprived)"

    def test_unparseable_title_raises(self):
        with pytest.raises(NISRADataNotFoundError):
            hq._extract_area("This is not a real table title", "Table_1")


class TestCleanColumn:
    """Behaviour of the column-name normaliser (no network required)."""

    def test_number_suffix(self):
        assert hq._clean_column("No qualifications\n(Number)") == "no_qualifications_number"

    def test_percent_suffix(self):
        assert hq._clean_column("No qualifications\n(%)") == "no_qualifications_pct"

    def test_percentage_word_suffix(self):
        assert hq._clean_column("Level 2 and above (percentage)") == "level_2_and_above_pct"

    def test_strips_note_reference(self):
        assert hq._clean_column("Small sample size cells\n[note 22]") == "small_sample_size_cells"

    def test_plain_year(self):
        assert hq._clean_column("Year") == "year"


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(NISRAValidationError):
            hq.validate_data(pd.DataFrame())

    def test_rejects_missing_year_column(self):
        with pytest.raises(NISRAValidationError):
            hq.validate_data(pd.DataFrame({"geography": ["NI"], "total_number": [100]}))

    def test_rejects_no_data_columns(self):
        df = pd.DataFrame({"geography": ["NI"], "year": [2025]})
        with pytest.raises(NISRAValidationError):
            hq.validate_data(df)

    def test_rejects_all_null_data(self):
        df = pd.DataFrame({"geography": ["NI"], "year": [2025], "total_number": [None]})
        with pytest.raises(NISRAValidationError):
            hq.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"geography": ["NI"], "year": [2025], "total_number": [1125000]})
        assert hq.validate_data(df) is True
