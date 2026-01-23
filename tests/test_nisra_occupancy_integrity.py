"""Data integrity tests for NISRA hotel occupancy statistics.

These tests validate that the data is internally consistent across different
time periods. They use real data from NISRA (not mocked) and should work with
any dataset (latest or historical).

Key validations:
- Occupancy rates between 0 and 1
- Realistic rooms/beds sold values
- Temporal continuity (no missing months in time series)
- Seasonal patterns (summer months typically have higher occupancy)
- COVID-19 impact visible in 2020
"""

import datetime

import pytest

from bolster.data_sources.nisra import occupancy


class TestHotelOccupancyDataIntegrity:
    """Test suite for validating internal consistency of hotel occupancy data."""

    @pytest.fixture(scope="class")
    def latest_occupancy(self):
        """Fetch latest hotel occupancy data once for the test class."""
        return occupancy.get_latest_hotel_occupancy(force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_rooms_beds_sold(self):
        """Fetch latest rooms/beds sold data once for the test class."""
        return occupancy.get_latest_rooms_beds_sold(force_refresh=False)

    def test_required_columns_present_occupancy(self, latest_occupancy):
        """Test that all required columns are present in occupancy data."""
        required_columns = {"date", "year", "month", "room_occupancy", "bed_occupancy"}

        assert set(latest_occupancy.columns) == required_columns, (
            f"Incorrect columns: {set(latest_occupancy.columns)}"
        )

    def test_required_columns_present_rooms_beds(self, latest_rooms_beds_sold):
        """Test that all required columns are present in rooms/beds sold data."""
        required_columns = {"date", "year", "month", "rooms_sold", "beds_sold"}

        assert set(latest_rooms_beds_sold.columns) == required_columns, (
            f"Incorrect columns: {set(latest_rooms_beds_sold.columns)}"
        )

    def test_occupancy_rates_between_zero_and_one(self, latest_occupancy):
        """Test that occupancy rates are between 0 and 1."""
        # Filter out NaN values
        room_occ = latest_occupancy["room_occupancy"].dropna()
        bed_occ = latest_occupancy["bed_occupancy"].dropna()

        assert (room_occ >= 0).all(), "Room occupancy contains values < 0"
        assert (room_occ <= 1).all(), "Room occupancy contains values > 1"

        assert (bed_occ >= 0).all(), "Bed occupancy contains values < 0"
        assert (bed_occ <= 1).all(), "Bed occupancy contains values > 1"

    def test_no_negative_rooms_beds_sold(self, latest_rooms_beds_sold):
        """Test that rooms/beds sold are not negative."""
        rooms = latest_rooms_beds_sold["rooms_sold"].dropna()
        beds = latest_rooms_beds_sold["beds_sold"].dropna()

        assert (rooms >= 0).all(), "Rooms sold contains negative values"
        assert (beds >= 0).all(), "Beds sold contains negative values"

    def test_realistic_rooms_sold_ranges(self, latest_rooms_beds_sold):
        """Test that rooms sold are within realistic ranges.

        Monthly hotel rooms sold in NI typically range from 50,000-250,000.
        """
        # Filter out NaN and COVID years (2020-2021)
        non_covid = latest_rooms_beds_sold[
            ~latest_rooms_beds_sold["year"].isin([2020, 2021])
        ]
        rooms = non_covid["rooms_sold"].dropna()

        if len(rooms) > 0:
            max_rooms = rooms.max()
            min_rooms = rooms.min()

            assert max_rooms < 300000, f"Max rooms sold ({max_rooms:,.0f}) unrealistically high"
            assert min_rooms > 50000, f"Min rooms sold ({min_rooms:,.0f}) unrealistically low"

    def test_temporal_continuity(self, latest_occupancy):
        """Test that there are no unexpected gaps in the time series.

        Note: 2020-2021 have gaps due to COVID-19 hotel closures:
        - Hotels closed March 26 to July 2, 2020
        - Hotels closed Oct 17 to Dec 10, 2020
        - Hotels closed Dec 27, 2020 to May 23, 2021
        """
        # Group by year and check month continuity (excluding COVID years)
        covid_years = {2020, 2021}

        for year in latest_occupancy["year"].unique():
            if year in covid_years:
                continue  # Skip COVID years - gaps are expected

            year_data = latest_occupancy[latest_occupancy["year"] == year].copy()
            year_data = year_data.sort_values("date")

            months = year_data["date"].dt.month.tolist()

            # Allow incomplete years
            if len(months) < 12:
                # Check months are consecutive
                for i in range(1, len(months)):
                    assert months[i] == months[i - 1] + 1 or months[i] == 1, (
                        f"Year {year}: Months are not consecutive: {months}"
                    )

    def test_covid_impact_visible(self, latest_occupancy):
        """Test that COVID-19 impact is visible in 2020 data.

        2020 should show significantly reduced occupancy due to lockdowns.
        """
        if 2020 not in latest_occupancy["year"].values:
            pytest.skip("2020 data not available")

        df_2020 = occupancy.get_occupancy_by_year(latest_occupancy, 2020)
        df_2019 = occupancy.get_occupancy_by_year(latest_occupancy, 2019)

        # Average 2020 occupancy should be significantly lower than 2019
        avg_2020 = df_2020["room_occupancy"].mean()
        avg_2019 = df_2019["room_occupancy"].mean()

        reduction = ((avg_2019 - avg_2020) / avg_2019) * 100

        assert reduction > 20, (
            f"2020 occupancy ({avg_2020:.1%}) should show COVID-19 impact "
            f"(expected >20% reduction from 2019: {avg_2019:.1%})"
        )

    def test_seasonal_patterns(self, latest_occupancy):
        """Test that summer months typically have higher occupancy.

        Peak tourism season is typically June-September.
        """
        # Exclude COVID years for seasonal pattern analysis
        non_covid = latest_occupancy[~latest_occupancy["year"].isin([2020, 2021])]

        monthly_avg = non_covid.groupby("month")["room_occupancy"].mean()

        peak_months = ["June", "July", "August", "September"]
        off_peak_months = ["January", "February", "November", "December"]

        peak_avg = monthly_avg[monthly_avg.index.isin(peak_months)].mean()
        off_peak_avg = monthly_avg[monthly_avg.index.isin(off_peak_months)].mean()

        # Peak months should have higher occupancy
        assert peak_avg > off_peak_avg, (
            f"Peak months ({peak_avg:.1%}) should have higher occupancy "
            f"than off-peak months ({off_peak_avg:.1%})"
        )

    def test_data_types_correct_occupancy(self, latest_occupancy):
        """Test that column data types are correct for occupancy data."""
        assert latest_occupancy["date"].dtype == "datetime64[ns]", "date should be datetime"
        assert latest_occupancy["year"].dtype in ["int64", "int32"], "year should be integer"
        assert latest_occupancy["month"].dtype == "object", "month should be string"
        assert latest_occupancy["room_occupancy"].dtype == "float64", "room_occupancy should be float"
        assert latest_occupancy["bed_occupancy"].dtype == "float64", "bed_occupancy should be float"

    def test_data_types_correct_rooms_beds(self, latest_rooms_beds_sold):
        """Test that column data types are correct for rooms/beds sold data."""
        assert latest_rooms_beds_sold["date"].dtype == "datetime64[ns]", "date should be datetime"
        assert latest_rooms_beds_sold["year"].dtype in ["int64", "int32"], "year should be integer"
        assert latest_rooms_beds_sold["month"].dtype == "object", "month should be string"
        assert latest_rooms_beds_sold["rooms_sold"].dtype == "float64", "rooms_sold should be float"
        assert latest_rooms_beds_sold["beds_sold"].dtype == "float64", "beds_sold should be float"

    def test_month_names_valid(self, latest_occupancy):
        """Test that all month names are valid."""
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

        actual_months = set(latest_occupancy["month"].unique())
        assert actual_months == expected_months, f"Unexpected month names: {actual_months - expected_months}"

    def test_date_year_consistency(self, latest_occupancy):
        """Test that date and year columns are consistent."""
        date_years = latest_occupancy["date"].dt.year
        assert (date_years == latest_occupancy["year"]).all(), "date and year columns are inconsistent"

    def test_helper_function_get_occupancy_by_year(self, latest_occupancy):
        """Test the get_occupancy_by_year helper function."""
        if 2024 in latest_occupancy["year"].values:
            df_2024 = occupancy.get_occupancy_by_year(latest_occupancy, 2024)

            assert df_2024["year"].nunique() == 1
            assert df_2024["year"].iloc[0] == 2024
            assert len(df_2024) <= 12

    def test_helper_function_get_occupancy_summary_by_year(self, latest_occupancy):
        """Test the get_occupancy_summary_by_year helper function."""
        summary = occupancy.get_occupancy_summary_by_year(latest_occupancy)

        required_cols = {"year", "avg_room_occupancy", "avg_bed_occupancy", "months_reported"}
        assert set(summary.columns) == required_cols

        assert (summary["months_reported"] >= 1).all()
        assert (summary["months_reported"] <= 12).all()

    def test_helper_function_get_seasonal_patterns(self, latest_occupancy):
        """Test the get_seasonal_patterns helper function."""
        seasonal = occupancy.get_seasonal_patterns(latest_occupancy)

        assert len(seasonal) == 12
        assert "month" in seasonal.columns
        assert "avg_room_occupancy" in seasonal.columns
        assert "avg_bed_occupancy" in seasonal.columns

    def test_historical_coverage(self, latest_occupancy):
        """Test that data goes back to at least 2011."""
        min_year = latest_occupancy["year"].min()

        assert min_year <= 2011, f"Expected data from 2011, earliest is {min_year}"

    def test_recent_data_available(self, latest_occupancy):
        """Test that recent data is available (within last year)."""
        max_year = latest_occupancy["year"].max()
        current_year = datetime.datetime.now().year

        assert max_year >= current_year - 1, f"Latest data ({max_year}) is more than 1 year old"

    def test_no_duplicate_months(self, latest_occupancy):
        """Test that there are no duplicate year-month combinations."""
        duplicates = latest_occupancy.groupby(["year", "month"]).size()
        duplicates = duplicates[duplicates > 1]

        assert len(duplicates) == 0, f"Found duplicate year-month combinations: {duplicates}"

    def test_room_occupancy_higher_than_bed_occupancy(self, latest_occupancy):
        """Test that room occupancy is typically higher than bed occupancy.

        Room occupancy is usually higher because not all beds in a room are used.
        """
        # Filter out NaN values
        valid_data = latest_occupancy[
            latest_occupancy["room_occupancy"].notna() & latest_occupancy["bed_occupancy"].notna()
        ]

        room_higher = valid_data["room_occupancy"] >= valid_data["bed_occupancy"]

        # Most months should have higher room occupancy
        pct_room_higher = room_higher.sum() / len(valid_data) * 100

        assert pct_room_higher > 80, (
            f"Room occupancy should typically be higher than bed occupancy "
            f"(only {pct_room_higher:.1f}% of months)"
        )

    def test_beds_sold_higher_than_rooms_sold(self, latest_rooms_beds_sold):
        """Test that beds sold is typically higher than rooms sold.

        Multiple beds per room means beds sold should exceed rooms sold.
        """
        valid_data = latest_rooms_beds_sold[
            latest_rooms_beds_sold["rooms_sold"].notna() & latest_rooms_beds_sold["beds_sold"].notna()
        ]

        beds_higher = valid_data["beds_sold"] >= valid_data["rooms_sold"]

        # All months should have higher beds sold
        pct_beds_higher = beds_higher.sum() / len(valid_data) * 100

        assert pct_beds_higher > 95, (
            f"Beds sold should be higher than rooms sold "
            f"(only {pct_beds_higher:.1f}% of months)"
        )

    def test_summer_peak_occupancy(self, latest_occupancy):
        """Test that August typically has the highest occupancy.

        August is peak tourism season in Northern Ireland.
        """
        # Exclude COVID years
        non_covid = latest_occupancy[~latest_occupancy["year"].isin([2020, 2021])]

        monthly_avg = non_covid.groupby("month")["room_occupancy"].mean().sort_values(ascending=False)

        top_3_months = monthly_avg.head(3).index.tolist()

        summer_months = ["July", "August", "September"]
        has_summer_peak = any(month in top_3_months for month in summer_months)

        assert has_summer_peak, f"Summer months should be in top 3, but top 3 are: {top_3_months}"
