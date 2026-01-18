"""Integrity tests for PSNI crime statistics data source."""

import pandas as pd
import pytest

from bolster.data_sources.psni import crime_statistics


@pytest.fixture(scope="module")
def data():
    """Load data once for all tests."""
    return crime_statistics.get_latest_crime_statistics()


class TestDataStructure:
    """Test data structure and format."""

    def test_returns_dataframe(self, data):
        """Should return a pandas DataFrame."""
        assert isinstance(data, pd.DataFrame)

    def test_not_empty(self, data):
        """Should contain data."""
        assert len(data) > 0

    def test_has_expected_columns(self, data):
        """Should have all expected columns."""
        expected = {
            "calendar_year",
            "month",
            "policing_district",
            "crime_type",
            "data_measure",
            "count",
            "date",
            "lgd_code",
            "nuts3_code",
            "nuts3_name",
        }
        assert expected.issubset(set(data.columns))

    def test_date_column_is_datetime(self, data):
        """Date column should be datetime type."""
        assert pd.api.types.is_datetime64_any_dtype(data["date"])

    def test_count_column_is_numeric(self, data):
        """Count column should be numeric."""
        assert pd.api.types.is_numeric_dtype(data["count"])

    def test_no_duplicate_records(self, data):
        """Should have no duplicate records."""
        # Check for duplicates on key columns
        key_cols = ["calendar_year", "month", "policing_district", "crime_type", "data_measure"]
        assert not data.duplicated(subset=key_cols).any()


class TestDataQuality:
    """Test data quality and integrity."""

    def test_no_null_in_required_columns(self, data):
        """Required columns should have no null values."""
        required = ["calendar_year", "month", "policing_district", "crime_type", "data_measure", "date"]
        for col in required:
            assert data[col].notna().all(), f"{col} has null values"

    def test_valid_date_range(self, data):
        """Dates should be within reasonable range."""
        assert data["date"].min() >= pd.Timestamp("2001-01-01"), "Data before 2001"
        assert data["date"].max() <= pd.Timestamp.now(), "Data in the future"

    def test_crime_counts_non_negative(self, data):
        """Crime counts should be non-negative."""
        crime_counts = data[data["data_measure"] == "Police Recorded Crime"]["count"]
        # Filter out NA values (which represent "/0")
        crime_counts = crime_counts.dropna()
        assert (crime_counts >= 0).all(), "Found negative crime counts"

    def test_outcome_rates_in_valid_range(self, data):
        """Outcome rates should be non-negative percentages.

        Note: Outcome rates CAN exceed 100% in policing data because:
        - Outcomes from previous periods resolved in current period
        - Multiple outcomes for a single crime
        - Crimes recorded in one period with outcomes in another

        This is documented behavior in PSNI statistics methodology.
        """
        outcome_rates = data[data["data_measure"] == "Police Recorded Crime Outcomes (rate %)"]["count"]
        # Filter out NA values
        outcome_rates = outcome_rates.dropna()
        assert (outcome_rates >= 0).all(), "Found negative outcome rates"
        # Note: rates > 100% are valid - see docstring for explanation

    def test_has_expected_policing_districts(self, data):
        """Should have all expected policing districts."""
        expected_districts = {
            "Northern Ireland",
            "Belfast City",
            "Lisburn & Castlereagh City",
            "Ards & North Down",
            "Newry Mourne & Down",
            "Armagh City Banbridge & Craigavon",
            "Mid Ulster",
            "Fermanagh & Omagh",
            "Derry City & Strabane",
            "Causeway Coast & Glens",
            "Mid & East Antrim",
            "Antrim & Newtownabbey",
        }
        actual_districts = set(data["policing_district"].unique())
        assert expected_districts.issubset(actual_districts), (
            f"Missing districts: {expected_districts - actual_districts}"
        )

    def test_has_expected_data_measures(self, data):
        """Should have all expected data measure types."""
        expected_measures = {
            "Police Recorded Crime",
            "Police Recorded Crime Outcomes (number)",
            "Police Recorded Crime Outcomes (rate %)",
        }
        actual_measures = set(data["data_measure"].unique())
        assert expected_measures == actual_measures, "Data measure mismatch"

    def test_lgd_codes_valid_for_districts(self, data):
        """LGD codes should be valid for district policing districts."""
        # Filter to individual districts (not "Northern Ireland")
        districts = data[data["policing_district"] != "Northern Ireland"]

        # All districts should have LGD codes
        assert districts["lgd_code"].notna().all(), "Some districts missing LGD codes"

        # LGD codes should follow N09000XXX pattern
        lgd_pattern = r"^N09000\d{3}$"
        assert districts["lgd_code"].str.match(lgd_pattern).all(), "Invalid LGD code format"

    def test_nuts3_codes_valid(self, data):
        """NUTS3 codes should be valid UK codes."""
        # Filter to individual districts
        districts = data[data["policing_district"] != "Northern Ireland"]

        # All districts should have NUTS3 codes
        assert districts["nuts3_code"].notna().all(), "Some districts missing NUTS3 codes"

        # NUTS3 codes should follow UKN pattern
        nuts_pattern = r"^UKN\d{2}$"
        assert districts["nuts3_code"].str.match(nuts_pattern).all(), "Invalid NUTS3 code format"


class TestDataValidation:
    """Test data validation functions."""

    def test_validation_passes(self, data):
        """Data validation should pass."""
        assert crime_statistics.validate_crime_statistics(data)


class TestHelperFunctions:
    """Test helper and filter functions."""

    def test_filter_by_district_single(self, data):
        """Should filter to a single district."""
        belfast = crime_statistics.filter_by_district(data, "Belfast City")

        assert len(belfast) > 0, "No Belfast data"
        assert (belfast["policing_district"] == "Belfast City").all()

    def test_filter_by_district_multiple(self, data):
        """Should filter to multiple districts."""
        cities = crime_statistics.filter_by_district(data, ["Belfast City", "Derry City & Strabane"])

        assert len(cities) > 0, "No city data"
        assert cities["policing_district"].isin(["Belfast City", "Derry City & Strabane"]).all()

    def test_filter_by_crime_type(self, data):
        """Should filter to specific crime type."""
        total = crime_statistics.filter_by_crime_type(data, "Total police recorded crime")

        assert len(total) > 0, "No total crime data"
        assert (total["crime_type"] == "Total police recorded crime").all()

    def test_filter_by_date_range(self, data):
        """Should filter to date range."""
        filtered = crime_statistics.filter_by_date_range(data, "2020-01-01", "2020-12-31")

        assert len(filtered) > 0, "No 2020 data"
        assert (filtered["date"] >= pd.Timestamp("2020-01-01")).all()
        assert (filtered["date"] <= pd.Timestamp("2020-12-31")).all()

    def test_get_total_crimes_by_district(self, data):
        """Should calculate total crimes by district."""
        totals = crime_statistics.get_total_crimes_by_district(data, year=2020)

        assert isinstance(totals, pd.DataFrame)
        assert len(totals) > 0
        assert "policing_district" in totals.columns
        assert "total_crimes" in totals.columns
        assert "lgd_code" in totals.columns

        # Should have data for all 11 districts + Northern Ireland
        assert len(totals) >= 11

    def test_get_crime_trends(self, data):
        """Should return crime trends."""
        trends = crime_statistics.get_crime_trends(data)

        assert isinstance(trends, pd.DataFrame)
        assert len(trends) > 0
        assert "date" in trends.columns
        assert "count" in trends.columns

        # Should be sorted by date
        assert trends["date"].is_monotonic_increasing

    def test_get_outcome_rates_by_district(self, data):
        """Should calculate outcome rates by district."""
        outcomes = crime_statistics.get_outcome_rates_by_district(data, year=2020)

        assert isinstance(outcomes, pd.DataFrame)
        assert len(outcomes) > 0
        assert "policing_district" in outcomes.columns
        assert "average_outcome_rate" in outcomes.columns

        # Outcome rates should be reasonable percentages
        assert (outcomes["average_outcome_rate"] >= 0).all()
        assert (outcomes["average_outcome_rate"] <= 100).all()

    def test_get_available_crime_types(self, data):
        """Should return list of crime types."""
        crime_types = crime_statistics.get_available_crime_types(data)

        assert isinstance(crime_types, list)
        assert len(crime_types) > 0
        assert "Total police recorded crime" in crime_types

    def test_get_available_districts(self, data):
        """Should return list of districts."""
        districts = crime_statistics.get_available_districts(data)

        assert isinstance(districts, list)
        assert len(districts) >= 12  # 11 districts + Northern Ireland
        assert "Belfast City" in districts
        assert "Northern Ireland" in districts


class TestGeographicUtilities:
    """Test geographic code lookup functions."""

    def test_get_lgd_code(self):
        """Should return correct LGD code for district."""
        assert crime_statistics.get_lgd_code("Belfast City") == "N09000003"
        assert crime_statistics.get_lgd_code("Derry City & Strabane") == "N09000005"
        assert crime_statistics.get_lgd_code("Invalid District") is None

    def test_get_nuts3_code(self):
        """Should return correct NUTS3 code for district."""
        assert crime_statistics.get_nuts3_code("Belfast City") == "UKN01"
        assert crime_statistics.get_nuts3_code("Derry City & Strabane") == "UKN02"
        assert crime_statistics.get_nuts3_code("Invalid District") is None

    def test_get_nuts_region_name(self):
        """Should return correct NUTS3 region name."""
        assert crime_statistics.get_nuts_region_name("UKN01") == "Belfast"
        assert crime_statistics.get_nuts_region_name("UKN02") == "North of Northern Ireland"
        assert crime_statistics.get_nuts_region_name("UKN06") == "Outer Belfast"
        assert crime_statistics.get_nuts_region_name("INVALID") is None

    def test_all_districts_have_lgd_codes(self, data):
        """All districts (except NI total) should map to LGD codes."""
        districts = data[data["policing_district"] != "Northern Ireland"]["policing_district"].unique()

        for district in districts:
            lgd = crime_statistics.get_lgd_code(district)
            assert lgd is not None, f"District '{district}' has no LGD code"
            assert lgd.startswith("N09000"), f"Invalid LGD code for {district}: {lgd}"

    def test_all_districts_have_nuts3_codes(self, data):
        """All districts (except NI total) should map to NUTS3 codes."""
        districts = data[data["policing_district"] != "Northern Ireland"]["policing_district"].unique()

        for district in districts:
            nuts3 = crime_statistics.get_nuts3_code(district)
            assert nuts3 is not None, f"District '{district}' has no NUTS3 code"
            assert nuts3.startswith("UKN"), f"Invalid NUTS3 code for {district}: {nuts3}"


class TestDataCoverage:
    """Test temporal and geographic data coverage."""

    def test_has_multi_year_coverage(self, data):
        """Should have data for multiple years."""
        years = data["calendar_year"].unique()
        assert len(years) >= 10, f"Only {len(years)} years of data"

    def test_has_monthly_data(self, data):
        """Should have monthly granularity."""
        months = data["month"].unique()
        # Should have at least most months
        assert len(months) >= 10, f"Only {len(months)} months present"

    def test_all_districts_have_data(self, data):
        """All policing districts should have data."""
        expected_districts = {
            "Belfast City",
            "Lisburn & Castlereagh City",
            "Ards & North Down",
            "Newry Mourne & Down",
            "Armagh City Banbridge & Craigavon",
            "Mid Ulster",
            "Fermanagh & Omagh",
            "Derry City & Strabane",
            "Causeway Coast & Glens",
            "Mid & East Antrim",
            "Antrim & Newtownabbey",
        }

        for district in expected_districts:
            district_data = data[data["policing_district"] == district]
            assert len(district_data) > 0, f"No data for {district}"

    def test_temporal_continuity(self, data):
        """Should have continuous monthly data (no large gaps)."""
        # Check that dates are mostly continuous
        dates = sorted(data["date"].unique())

        # Calculate gaps between consecutive dates
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]

        # Most gaps should be around 28-31 days (monthly)
        reasonable_gaps = [g for g in gaps if 25 <= g <= 35]

        # At least 95% of gaps should be reasonable monthly gaps
        gap_ratio = len(reasonable_gaps) / len(gaps)
        assert gap_ratio >= 0.95, f"Only {gap_ratio:.1%} of date gaps are monthly"
