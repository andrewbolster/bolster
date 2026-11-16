"""Data integrity tests for NISRA population statistics.

These tests validate that the data is internally consistent across different
dimensions and time periods. They use real data from NISRA (not mocked) and
should work with any dataset (latest or historical).

Key validations:
- Total population should equal sum of male + female population
- No negative values
- Temporal continuity (no missing years in time series)
- Required columns, age bands, sex categories present
"""

import re

import pandas as pd
import pytest

from bolster.data_sources.nisra import population


class TestPopulationDataIntegrity:
    """Test suite for validating internal consistency of population data."""

    @pytest.fixture(scope="class")
    def latest_population_ni(self):
        """Fetch latest Northern Ireland population data once for the test class."""
        return population.get_latest_population(area="Northern Ireland", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_population_all(self):
        """Fetch all geographic areas for testing."""
        return population.get_latest_population(area="all", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_population_lgd(self):
        """Fetch the Local Government District estimates."""
        return population.get_latest_population(area="Local Government Districts", force_refresh=False)

    def test_each_supported_area_returns_only_its_own_rows(
        self, latest_population_ni, latest_population_lgd, latest_population_all
    ):
        """Every accepted ``area`` value returns rows, and 'all' is exactly the union of the others."""
        assert set(latest_population_ni["area"]) == {"1. Northern Ireland"}
        assert latest_population_lgd["area"].nunique() == 1
        assert latest_population_lgd["area"].iloc[0].startswith("2. Local Government Districts")
        assert len(latest_population_all) == len(latest_population_ni) + len(latest_population_lgd)

    def test_local_government_districts_coverage(self, latest_population_lgd):
        """The 11 districts are present from 2001, with one row per district, year, sex and age cell.

        Each row is a cell of the intersection of the file's three age groupings, so a row is
        identified by ``age_5``, ``age_band`` and ``age_broad`` together (23 rows for each district,
        year and sex).
        """
        assert latest_population_lgd["area_name"].nunique() == 11
        assert latest_population_lgd["year"].min() == 2001
        keys = ["area_name", "year", "sex", "age_5", "age_band", "age_broad"]
        assert not latest_population_lgd.duplicated(subset=keys).any()
        assert set(latest_population_lgd.groupby(["area_name", "year", "sex"]).size()) == {23}

    def test_district_totals_reconcile_to_northern_ireland(self, latest_population_ni, latest_population_lgd):
        """In every year with district data, the districts sum exactly to the Northern Ireland total."""
        persons = lambda df: df[df["sex"] == "All persons"].groupby("year")["population"].sum()  # noqa: E731
        ni, lgd = persons(latest_population_ni), persons(latest_population_lgd)

        assert set(lgd.index) <= set(ni.index)
        mismatched = [year for year in lgd.index if lgd[year] != ni[year]]
        assert not mismatched, f"District totals differ from the NI total in {mismatched}"

    def test_unsupported_area_names_what_the_file_holds(self):
        """A grouping the file lacks raises an error naming the groupings it has, never data."""
        with pytest.raises(population.NISRAValidationError, match="Local Government Districts"):
            population.get_latest_population(area="Health and Social Care Trusts", force_refresh=False)

    def test_sex_sum_to_total(self, latest_population_ni):
        """Test that male + female population equals all persons for each year/age group."""
        # Use constitutional validation function instead of manual checks
        assert population.validate_population_totals(latest_population_ni)

    def test_no_negative_values(self, latest_population_all):
        """Test that there are no negative population counts."""
        assert (latest_population_all["population"] >= 0).all(), "Data contains negative population counts"

    def test_temporal_continuity(self, latest_population_ni):
        """Test that there are no missing years in the time series."""
        years = sorted(latest_population_ni["year"].unique())

        # Check for NI overall (should have 1971-present)
        min_year = min(years)
        max_year = max(years)

        expected_years = set(range(min_year, max_year + 1))
        actual_years = set(years)

        missing_years = expected_years - actual_years

        assert len(missing_years) == 0, f"Missing years in time series: {sorted(missing_years)}"

    def test_required_columns_present(self, latest_population_all):
        """Test that all required columns are present."""
        required_columns = {
            "area",
            "area_code",
            "area_name",
            "year",
            "sex",
            "age_5",
            "age_band",
            "age_broad",
            "population",
        }

        assert set(latest_population_all.columns) == required_columns, (
            f"Incorrect columns: {set(latest_population_all.columns)}"
        )

    def test_sex_categories_complete(self, latest_population_all):
        """Test that all expected sex categories are present."""
        expected_sexes = {"All persons", "Males", "Females"}

        actual_sexes = set(latest_population_all["sex"].unique())
        assert actual_sexes == expected_sexes, f"Expected sexes {expected_sexes}, got {actual_sexes}"

    def test_age_bands_complete(self, latest_population_ni):
        """Test that all expected 5-year age bands are present."""
        expected_age_bands = {
            "00-04",
            "05-09",
            "10-14",
            "15-19",
            "20-24",
            "25-29",
            "30-34",
            "35-39",
            "40-44",
            "45-49",
            "50-54",
            "55-59",
            "60-64",
            "65-69",
            "70-74",
            "75-79",
            "80-84",
            "85-89",
            "90+",
        }

        actual_age_bands = set(latest_population_ni["age_5"].unique())
        assert actual_age_bands == expected_age_bands, (
            f"Age bands mismatch. Missing: {expected_age_bands - actual_age_bands}, "
            f"Extra: {actual_age_bands - expected_age_bands}"
        )

    def test_area_filter_works(self, latest_population_all):
        """Test that area filtering returns correct data."""
        areas = latest_population_all["area"].unique()

        # Should have at least 2 area types (NI + LGDs); NISRA reduced from 4 in 2024 publication
        assert len(areas) >= 2, f"Expected at least 2 area types, got {len(areas)}"

        # Each area should have expected numbered naming pattern
        for area in areas:
            assert re.match(r"^\d+\.", area), f"Unexpected area format: {area}"

    def test_get_population_by_year_function(self, latest_population_ni):
        """Test the get_population_by_year helper function."""
        # Get data for a specific year
        latest_year = latest_population_ni["year"].max()
        year_data = population.get_population_by_year(latest_population_ni, latest_year)

        # Should only have data for that year
        assert year_data["year"].nunique() == 1
        assert year_data["year"].iloc[0] == latest_year

        # Should have all sex categories by default
        assert set(year_data["sex"].unique()) == {"All persons"}

        # Test with specific sex
        male_data = population.get_population_by_year(latest_population_ni, latest_year, sex="Males")
        assert male_data["sex"].nunique() == 1
        assert male_data["sex"].iloc[0] == "Males"

    def test_population_pyramid_function(self, latest_population_ni):
        """Test the get_population_pyramid_data helper function."""
        latest_year = latest_population_ni["year"].max()
        pyramid = population.get_population_pyramid_data(latest_population_ni, latest_year)

        # Should have 19 age bands
        assert len(pyramid) == 19

        # Should have males, females, age_5 columns
        assert set(pyramid.columns) == {"age_5", "males", "females"}

        # Males should be positive, females negative (for pyramid plotting)
        assert (pyramid["males"] > 0).all()
        assert (pyramid["females"] < 0).all()

        # Total should match NI population
        total_males = pyramid["males"].sum()
        total_females = abs(pyramid["females"].sum())

        expected_total = latest_population_ni[
            (latest_population_ni["year"] == latest_year) & (latest_population_ni["sex"] == "All persons")
        ]["population"].sum()

        assert total_males + total_females == expected_total

    def test_validate_function_works(self, latest_population_ni):
        """Test that the validate_population_totals function works correctly."""
        # Should pass with valid data
        assert population.validate_population_totals(latest_population_ni)

        # Create invalid data
        invalid_data = latest_population_ni.copy()
        invalid_data.loc[invalid_data["sex"] == "Males", "population"] = 0

        # Should fail
        with pytest.raises(population.NISRAValidationError):
            population.validate_population_totals(invalid_data)

    def test_historical_data_coverage(self, latest_population_ni):
        """Test that Northern Ireland has historical data back to 1971."""
        min_year = latest_population_ni["year"].min()
        max_year = latest_population_ni["year"].max()

        # NI overall should have data from 1971
        assert min_year <= 1971, f"Expected data from 1971, earliest is {min_year}"

        # Should have recent data (within last 2 years)
        import datetime

        current_year = datetime.datetime.now().year
        assert max_year >= current_year - 2, f"Latest data ({max_year}) is more than 2 years old"


class TestHeaderCaseTolerance:
    """NISRA upper-cased the age headers in MYE25; both spellings must parse."""

    @pytest.mark.parametrize("upper", [False, True])
    def test_age_column_case_is_normalised(self, tmp_path, upper):
        columns = ["area", "area_code", "area_name", "year", "sex", "age_5", "age_band", "age_broad", "MYE"]
        if upper:
            columns = [c.upper() if c.startswith("age_") else c for c in columns]
        row = [
            "1. Northern Ireland",
            "N92000002",
            "NORTHERN IRELAND",
            2025,
            "All persons",
            "00-04",
            "00-03",
            "00-15",
            100,
        ]
        path = tmp_path / "pop.xlsx"
        pd.DataFrame([row], columns=columns).to_excel(path, sheet_name="Flat", index=False)

        df = population.parse_population_file(path)

        assert {"age_5", "age_band", "age_broad", "population"} <= set(df.columns)
        assert df["population"].iloc[0] == 100


def _flat_workbook(path, groupings):
    """Write a minimal Flat sheet with one row per (raw area label, area name)."""
    columns = ["area", "area_code", "area_name", "year", "sex", "age_5", "age_band", "age_broad", "MYE"]
    rows = [
        [area, f"CODE{i}", name, 2025, "All persons", "00-04", "00-03", "00-15", 100 + i]
        for i, (area, name) in enumerate(groupings)
    ]
    pd.DataFrame(rows, columns=columns).to_excel(path, sheet_name="Flat", index=False)
    return path


class TestAreaOptions:
    """``area`` accepts exactly the groupings in the file (offline, on a small synthetic Flat sheet)."""

    GROUPINGS = [
        ("1. Northern Ireland", "NORTHERN IRELAND"),
        ("2. Local Government Districts (LGD2014)", "Belfast"),
        ("2. Local Government Districts (LGD2014)", "Mid Ulster"),
    ]

    @pytest.fixture
    def flat_file(self, tmp_path):
        return _flat_workbook(tmp_path / "pop.xlsx", self.GROUPINGS)

    def test_northern_ireland_selects_only_its_rows(self, flat_file):
        df = population.parse_population_file(flat_file, area="Northern Ireland")
        assert set(df["area"]) == {"1. Northern Ireland"}

    def test_local_government_districts_drops_the_numbering_and_vintage(self, flat_file):
        df = population.parse_population_file(flat_file, area="Local Government Districts")
        assert sorted(df["area_name"]) == ["Belfast", "Mid Ulster"]

    @pytest.mark.parametrize("area", ["all", None])
    def test_all_returns_every_grouping(self, flat_file, area):
        assert len(population.parse_population_file(flat_file, area=area)) == len(self.GROUPINGS)

    @pytest.mark.parametrize(
        "area",
        [
            "Health and Social Care Trusts",
            "Parliamentary Constituencies (2024)",
            "Parliamentary Constituencies (2008)",
            "2. Local Government Districts (LGD2014)",
            "northern ireland",
            "Nonsense",
        ],
    )
    def test_other_values_raise_naming_the_groupings_in_the_file(self, flat_file, area):
        with pytest.raises(population.NISRAValidationError) as excinfo:
            population.parse_population_file(flat_file, area=area)

        message = str(excinfo.value)
        assert message.startswith(f"Unknown area {area!r}")
        assert "'Northern Ireland'" in message
        assert "'Local Government Districts'" in message
        assert "'all'" in message

    def test_accepted_values_follow_the_file(self, tmp_path):
        """A grouping NISRA adds to the file becomes selectable without a code change."""
        groupings = [*self.GROUPINGS, ("3. Health and Social Care Trusts", "Belfast Trust")]
        path = _flat_workbook(tmp_path / "pop_with_trusts.xlsx", groupings)

        df = population.parse_population_file(path, area="Health and Social Care Trusts")

        assert list(df["area_name"]) == ["Belfast Trust"]

    def test_area_options_maps_names_to_raw_values(self, flat_file):
        df = pd.read_excel(flat_file, sheet_name="Flat")
        assert population._area_options(df) == {
            "Northern Ireland": "1. Northern Ireland",
            "Local Government Districts": "2. Local Government Districts (LGD2014)",
        }
