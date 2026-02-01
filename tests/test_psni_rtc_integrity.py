"""Data integrity tests for PSNI Road Traffic Collision statistics.

These tests verify:
- Data structure and column presence
- Value ranges and data types
- Cross-dataset consistency (collisions, casualties, vehicles)
- Geographic code mappings
- Historical data coverage
"""

import pytest

from bolster.data_sources.psni import road_traffic_collisions


class TestRTCDataIntegrity:
    """Test data integrity for Road Traffic Collision statistics."""

    @pytest.fixture(scope="class")
    def available_years(self):
        """Get list of available data years."""
        return road_traffic_collisions.get_available_years()

    @pytest.fixture(scope="class")
    def latest_year(self, available_years):
        """Get the latest available year."""
        return available_years[0] if available_years else None

    @pytest.fixture(scope="class")
    def collisions(self, latest_year):
        """Get collision data for latest year."""
        if latest_year is None:
            pytest.skip("No RTC data available")
        return road_traffic_collisions.get_collisions(latest_year)

    @pytest.fixture(scope="class")
    def casualties(self, latest_year):
        """Get casualty data for latest year."""
        if latest_year is None:
            pytest.skip("No RTC data available")
        return road_traffic_collisions.get_casualties(latest_year)

    @pytest.fixture(scope="class")
    def vehicles(self, latest_year):
        """Get vehicle data for latest year."""
        if latest_year is None:
            pytest.skip("No RTC data available")
        return road_traffic_collisions.get_vehicles(latest_year)

    # === Data Availability Tests ===

    def test_available_years_not_empty(self, available_years):
        """Test that at least one year of data is available."""
        assert len(available_years) > 0, "No RTC data years available"

    def test_available_years_recent(self, available_years):
        """Test that recent data is available (within last 3 years)."""
        latest = max(available_years)
        assert latest >= 2022, f"Latest data year {latest} is too old"

    def test_available_years_historical(self, available_years):
        """Test that historical data is available (from 2013+)."""
        earliest = min(available_years)
        assert earliest <= 2015, f"Earliest data year {earliest} - expected 2015 or earlier"

    # === Collision Data Structure Tests ===

    def test_collision_required_columns(self, collisions):
        """Test that collision data has required columns."""
        required = ["year", "ref", "district_code", "month", "day", "vehicles", "casualties"]
        missing = set(required) - set(collisions.columns)
        assert not missing, f"Missing required collision columns: {missing}"

    def test_collision_decoded_columns(self, collisions):
        """Test that decoded columns are present."""
        decoded = ["district", "weekday", "lgd_code"]
        missing = set(decoded) - set(collisions.columns)
        assert not missing, f"Missing decoded collision columns: {missing}"

    def test_collision_count_reasonable(self, collisions):
        """Test collision count is in reasonable range for NI."""
        # NI typically has 4,000-7,000 injury collisions per year
        assert 1000 < len(collisions) < 15000, f"Unexpected collision count: {len(collisions)}"

    def test_collision_vehicle_counts_positive(self, collisions):
        """Test that vehicle counts are positive."""
        assert (collisions["vehicles"] > 0).all(), "Found collisions with zero vehicles"

    def test_collision_casualty_counts_positive(self, collisions):
        """Test that casualty counts are positive."""
        assert (collisions["casualties"] > 0).all(), "Found collisions with zero casualties"

    def test_collision_months_valid(self, collisions):
        """Test that month values are valid (1-12)."""
        assert collisions["month"].between(1, 12).all(), "Invalid month values found"

    def test_collision_days_valid(self, collisions):
        """Test that day values are valid (1-31)."""
        assert collisions["day"].between(1, 31).all(), "Invalid day values found"

    def test_collision_hours_valid(self, collisions):
        """Test that hour values are valid (0-23)."""
        if "hour" in collisions.columns:
            valid_hours = collisions["hour"].dropna()
            assert valid_hours.between(0, 23).all(), "Invalid hour values found"

    # === Casualty Data Structure Tests ===

    def test_casualty_required_columns(self, casualties):
        """Test that casualty data has required columns."""
        required = ["year", "ref", "casualty_id", "severity_code"]
        missing = set(required) - set(casualties.columns)
        assert not missing, f"Missing required casualty columns: {missing}"

    def test_casualty_decoded_columns(self, casualties):
        """Test that decoded columns are present."""
        decoded = ["severity", "casualty_class"]
        missing = set(decoded) - set(casualties.columns)
        assert not missing, f"Missing decoded casualty columns: {missing}"

    def test_casualty_count_reasonable(self, casualties):
        """Test casualty count is in reasonable range."""
        # NI typically has 6,000-10,000 casualties per year
        assert 2000 < len(casualties) < 20000, f"Unexpected casualty count: {len(casualties)}"

    def test_casualty_severity_codes_valid(self, casualties):
        """Test that severity codes are valid (1, 2, or 3)."""
        valid_codes = {1, 2, 3}
        actual_codes = set(casualties["severity_code"].dropna().unique())
        assert actual_codes.issubset(valid_codes), f"Invalid severity codes: {actual_codes - valid_codes}"

    def test_casualty_severity_decoded(self, casualties):
        """Test that severity is properly decoded."""
        valid_severities = {"Fatal", "Serious", "Slight"}
        actual = set(casualties["severity"].dropna().unique())
        assert actual.issubset(valid_severities), f"Invalid severity values: {actual}"

    def test_casualty_fatalities_reasonable(self, casualties):
        """Test fatality count is in reasonable range for NI."""
        # NI typically has 50-100 road fatalities per year
        fatalities = len(casualties[casualties["severity"] == "Fatal"])
        assert 20 < fatalities < 200, f"Unexpected fatality count: {fatalities}"

    # === Vehicle Data Structure Tests ===

    def test_vehicle_required_columns(self, vehicles):
        """Test that vehicle data has required columns."""
        required = ["year", "ref", "vehicle_id", "vehicle_type_code"]
        missing = set(required) - set(vehicles.columns)
        assert not missing, f"Missing required vehicle columns: {missing}"

    def test_vehicle_count_reasonable(self, vehicles):
        """Test vehicle count is in reasonable range."""
        # Should be >= collisions (some collisions involve multiple vehicles)
        assert 3000 < len(vehicles) < 30000, f"Unexpected vehicle count: {len(vehicles)}"

    # === Cross-Dataset Consistency Tests ===

    def test_collision_casualty_refs_match(self, collisions, casualties):
        """Test that casualty refs are subset of collision refs."""
        collision_refs = set(collisions["ref"])
        casualty_refs = set(casualties["ref"])

        # All casualty refs should have a matching collision
        unmatched = casualty_refs - collision_refs
        assert not unmatched, f"Found {len(unmatched)} casualty refs without matching collisions"

    def test_collision_vehicle_refs_match(self, collisions, vehicles):
        """Test that vehicle refs are subset of collision refs."""
        collision_refs = set(collisions["ref"])
        vehicle_refs = set(vehicles["ref"])

        # All vehicle refs should have a matching collision
        unmatched = vehicle_refs - collision_refs
        assert not unmatched, f"Found {len(unmatched)} vehicle refs without matching collisions"

    def test_total_casualties_match(self, collisions, casualties):
        """Test that sum of casualties in collisions matches casualty count."""
        expected_total = collisions["casualties"].sum()
        actual_total = len(casualties)

        # Allow small tolerance for data quality issues
        tolerance = 0.02  # 2%
        diff_pct = abs(expected_total - actual_total) / expected_total

        assert diff_pct < tolerance, (
            f"Casualty count mismatch: expected {expected_total}, got {actual_total} (diff: {diff_pct:.1%})"
        )

    # === Geographic Code Tests ===

    def test_district_codes_valid(self, collisions):
        """Test that all district codes are recognized."""
        valid_codes = set(road_traffic_collisions.DISTRICT_CODES.keys())
        actual_codes = set(collisions["district_code"].dropna().unique())

        unrecognized = actual_codes - valid_codes
        assert not unrecognized, f"Unrecognized district codes: {unrecognized}"

    def test_lgd_codes_present(self, collisions):
        """Test that LGD codes are present for all records with districts."""
        with_district = collisions[collisions["district"].notna()]
        missing_lgd = with_district["lgd_code"].isna().sum()

        assert missing_lgd == 0, f"Missing LGD codes for {missing_lgd} records"

    def test_all_districts_represented(self, collisions):
        """Test that all 11 policing districts have data."""
        districts = collisions["district"].dropna().unique()
        expected_count = 11

        assert len(districts) >= expected_count, f"Only {len(districts)} districts, expected {expected_count}"

    # === Analysis Function Tests ===

    def test_casualties_by_district(self, latest_year):
        """Test casualties_by_district returns valid data."""
        df = road_traffic_collisions.get_casualties_by_district(latest_year)

        assert not df.empty, "Empty casualties by district result"
        assert "district" in df.columns
        assert "casualties" in df.columns
        assert "fatal" in df.columns
        assert df["casualties"].sum() > 0

    def test_casualties_by_road_user(self, latest_year):
        """Test casualties_by_road_user returns valid data."""
        df = road_traffic_collisions.get_casualties_by_road_user(latest_year)

        assert not df.empty, "Empty casualties by road user result"
        assert "casualty_class" in df.columns
        assert "casualties" in df.columns
        assert df["casualties"].sum() > 0

    def test_casualties_with_collision_details(self, latest_year):
        """Test merged casualty-collision data."""
        df = road_traffic_collisions.get_casualties_with_collision_details(latest_year)

        assert not df.empty, "Empty merged data"
        # Should have columns from both datasets
        assert "severity" in df.columns  # From casualties
        assert "district" in df.columns  # From collisions
        assert "date" in df.columns  # From collisions

    # === Validation Function Tests ===

    def test_validate_collision_data(self, collisions):
        """Test validation passes for collision data."""
        assert road_traffic_collisions.validate_data(collisions, "collision")

    def test_validate_casualty_data(self, casualties):
        """Test validation passes for casualty data."""
        assert road_traffic_collisions.validate_data(casualties, "casualty")

    def test_validate_vehicle_data(self, vehicles):
        """Test validation passes for vehicle data."""
        assert road_traffic_collisions.validate_data(vehicles, "vehicle")


class TestRTCAnnualSummary:
    """Test annual summary functionality."""

    @pytest.fixture(scope="class")
    def annual_summary(self):
        """Get annual summary for recent years."""
        years = road_traffic_collisions.get_available_years()
        # Get summary for 3 most recent years only (to keep tests fast)
        recent_years = years[:3] if len(years) >= 3 else years
        return road_traffic_collisions.get_annual_summary(years=recent_years)

    def test_annual_summary_columns(self, annual_summary):
        """Test annual summary has expected columns."""
        expected = ["year", "collisions", "casualties", "fatal", "serious", "slight"]
        missing = set(expected) - set(annual_summary.columns)
        assert not missing, f"Missing annual summary columns: {missing}"

    def test_annual_summary_consistency(self, annual_summary):
        """Test that fatal + serious + slight = casualties."""
        for _, row in annual_summary.iterrows():
            expected = row["fatal"] + row["serious"] + row["slight"]
            actual = row["casualties"]
            assert expected == actual, f"Year {row['year']}: {expected} != {actual}"

    def test_annual_summary_sorted(self, annual_summary):
        """Test that annual summary is sorted by year."""
        years = annual_summary["year"].tolist()
        assert years == sorted(years), "Annual summary not sorted by year"
