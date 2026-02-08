"""Data integrity tests for NISRA Small Service Accommodation (SSA) occupancy statistics.

These tests validate that SSA (B&B, guest house) occupancy data is internally
consistent across different time periods. They use real data from NISRA (not mocked)
and should work with any dataset (latest or historical).

Key validations:
- Occupancy rates between 0 and 1
- No negative rooms/beds sold values
- Temporal continuity (no missing months in time series)
- Cross-validation with hotel occupancy data (shared column structure)
"""

import datetime

import pytest

from bolster.data_sources.nisra.tourism import occupancy


class TestSSAOccupancyDataIntegrity:
    """Test suite for validating internal consistency of SSA occupancy data."""

    @pytest.fixture(scope="class")
    def latest_ssa_occupancy(self):
        """Fetch latest SSA occupancy data once for the test class."""
        return occupancy.get_latest_ssa_occupancy(force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_ssa_rooms_beds_sold(self):
        """Fetch latest SSA rooms/beds sold data once for the test class."""
        return occupancy.get_latest_ssa_rooms_beds_sold(force_refresh=False)

    def test_required_columns_present_occupancy(self, latest_ssa_occupancy):
        """Test that all required columns are present in SSA occupancy data."""
        required_columns = {"date", "year", "month", "room_occupancy", "bed_occupancy"}

        assert set(latest_ssa_occupancy.columns) == required_columns, (
            f"Incorrect columns: {set(latest_ssa_occupancy.columns)}"
        )

    def test_required_columns_present_rooms_beds(self, latest_ssa_rooms_beds_sold):
        """Test that all required columns are present in SSA rooms/beds sold data."""
        required_columns = {"date", "year", "month", "rooms_sold", "beds_sold"}

        assert set(latest_ssa_rooms_beds_sold.columns) == required_columns, (
            f"Incorrect columns: {set(latest_ssa_rooms_beds_sold.columns)}"
        )

    def test_occupancy_rates_between_zero_and_one(self, latest_ssa_occupancy):
        """Test that SSA occupancy rates are between 0 and 1."""
        room_occ = latest_ssa_occupancy["room_occupancy"].dropna()
        bed_occ = latest_ssa_occupancy["bed_occupancy"].dropna()

        assert (room_occ >= 0).all(), "Room occupancy contains values < 0"
        assert (room_occ <= 1).all(), "Room occupancy contains values > 1"

        assert (bed_occ >= 0).all(), "Bed occupancy contains values < 0"
        assert (bed_occ <= 1).all(), "Bed occupancy contains values > 1"

    def test_no_negative_rooms_beds_sold(self, latest_ssa_rooms_beds_sold):
        """Test that SSA rooms/beds sold are not negative."""
        rooms = latest_ssa_rooms_beds_sold["rooms_sold"].dropna()
        beds = latest_ssa_rooms_beds_sold["beds_sold"].dropna()

        assert (rooms >= 0).all(), "Rooms sold contains negative values"
        assert (beds >= 0).all(), "Beds sold contains negative values"

    def test_temporal_continuity(self, latest_ssa_occupancy):
        """Test that there are no unexpected gaps in the SSA time series.

        Note: 2020-2021 have gaps due to COVID-19 closures.
        """
        covid_years = {2020, 2021}

        for year in latest_ssa_occupancy["year"].unique():
            if year in covid_years:
                continue

            year_data = latest_ssa_occupancy[latest_ssa_occupancy["year"] == year].copy()
            year_data = year_data.sort_values("date")

            months = year_data["date"].dt.month.tolist()

            if len(months) < 12:
                for i in range(1, len(months)):
                    assert months[i] == months[i - 1] + 1 or months[i] == 1, (
                        f"Year {year}: Months are not consecutive: {months}"
                    )

    def test_data_types_correct_occupancy(self, latest_ssa_occupancy):
        """Test that column data types are correct for SSA occupancy data."""
        assert latest_ssa_occupancy["date"].dtype == "datetime64[ns]", "date should be datetime"
        assert latest_ssa_occupancy["year"].dtype in ["int64", "int32"], "year should be integer"
        assert latest_ssa_occupancy["month"].dtype == "object", "month should be string"
        assert latest_ssa_occupancy["room_occupancy"].dtype == "float64", "room_occupancy should be float"
        assert latest_ssa_occupancy["bed_occupancy"].dtype == "float64", "bed_occupancy should be float"

    def test_data_types_correct_rooms_beds(self, latest_ssa_rooms_beds_sold):
        """Test that column data types are correct for SSA rooms/beds sold data."""
        assert latest_ssa_rooms_beds_sold["date"].dtype == "datetime64[ns]", "date should be datetime"
        assert latest_ssa_rooms_beds_sold["year"].dtype in ["int64", "int32"], "year should be integer"
        assert latest_ssa_rooms_beds_sold["month"].dtype == "object", "month should be string"
        assert latest_ssa_rooms_beds_sold["rooms_sold"].dtype == "float64", "rooms_sold should be float"
        assert latest_ssa_rooms_beds_sold["beds_sold"].dtype == "float64", "beds_sold should be float"

    def test_month_names_valid(self, latest_ssa_occupancy):
        """Test that all month names are valid in SSA data."""
        expected_months = {
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        }

        actual_months = set(latest_ssa_occupancy["month"].unique())
        assert actual_months == expected_months, f"Unexpected month names: {actual_months - expected_months}"

    def test_date_year_consistency(self, latest_ssa_occupancy):
        """Test that date and year columns are consistent in SSA data."""
        date_years = latest_ssa_occupancy["date"].dt.year
        assert (date_years == latest_ssa_occupancy["year"]).all(), "date and year columns are inconsistent"

    def test_historical_coverage(self, latest_ssa_occupancy):
        """Test that SSA data goes back to at least 2013."""
        min_year = latest_ssa_occupancy["year"].min()

        assert min_year <= 2013, f"Expected SSA data from 2013, earliest is {min_year}"

    def test_recent_data_available(self, latest_ssa_occupancy):
        """Test that recent SSA data is available (within last year)."""
        max_year = latest_ssa_occupancy["year"].max()
        current_year = datetime.datetime.now().year

        assert max_year >= current_year - 1, f"Latest SSA data ({max_year}) is more than 1 year old"

    def test_no_duplicate_months(self, latest_ssa_occupancy):
        """Test that there are no duplicate year-month combinations in SSA data."""
        duplicates = latest_ssa_occupancy.groupby(["year", "month"]).size()
        duplicates = duplicates[duplicates > 1]

        assert len(duplicates) == 0, f"Found duplicate year-month combinations: {duplicates}"

    def test_beds_sold_higher_than_rooms_sold(self, latest_ssa_rooms_beds_sold):
        """Test that SSA beds sold is typically higher than rooms sold."""
        valid_data = latest_ssa_rooms_beds_sold[
            latest_ssa_rooms_beds_sold["rooms_sold"].notna() & latest_ssa_rooms_beds_sold["beds_sold"].notna()
        ]

        beds_higher = valid_data["beds_sold"] >= valid_data["rooms_sold"]
        pct_beds_higher = beds_higher.sum() / len(valid_data) * 100

        assert pct_beds_higher > 95, (
            f"Beds sold should be higher than rooms sold (only {pct_beds_higher:.1f}% of months)"
        )


class TestCrossValidation:
    """Test cross-validation between hotel and SSA occupancy data."""

    @pytest.fixture(scope="class")
    def combined_occupancy(self):
        """Fetch combined hotel and SSA occupancy data."""
        return occupancy.get_combined_occupancy(force_refresh=False)

    def test_combined_has_both_types(self, combined_occupancy):
        """Test that combined data includes both hotel and SSA."""
        types = set(combined_occupancy["accommodation_type"].unique())

        assert "hotel" in types, "Combined data should include hotel"
        assert "ssa" in types, "Combined data should include ssa"

    def test_combined_has_required_columns(self, combined_occupancy):
        """Test that combined data has all required columns."""
        required_cols = {"date", "year", "month", "room_occupancy", "bed_occupancy", "accommodation_type"}

        assert set(combined_occupancy.columns) == required_cols, (
            f"Missing columns: {required_cols - set(combined_occupancy.columns)}"
        )

    def test_compare_accommodation_types_function(self, combined_occupancy):
        """Test the compare_accommodation_types helper function."""
        comparison = occupancy.compare_accommodation_types(combined_occupancy)

        assert "year" in comparison.columns
        assert "hotel_room_occupancy" in comparison.columns
        assert "ssa_room_occupancy" in comparison.columns
        assert "difference" in comparison.columns
        assert "ratio" in comparison.columns

        # Hotels should have positive difference (hotel > ssa) in most years
        non_covid = comparison[~comparison["year"].isin([2020, 2021])]
        positive_diff = (non_covid["difference"] > 0).sum()
        total = len(non_covid)

        assert positive_diff / total > 0.8, (
            f"Hotel should have higher occupancy than SSA in most years ({positive_diff}/{total})"
        )
