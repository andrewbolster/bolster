"""Data integrity tests for NISRA quarterly visitor statistics.

These tests validate that visitor statistics data is internally consistent
and provides reasonable values. They use real data from NISRA (not mocked)
and should work with any dataset (latest or historical quarterly data).

Key validations:
- All expected markets present (GB, ROI, NI, etc.)
- Values are non-negative
- Total row sums correctly
- Helper functions work correctly
"""

import pytest

from bolster.data_sources.nisra.tourism import visitor_statistics


class TestVisitorStatisticsDataIntegrity:
    """Test suite for validating internal consistency of visitor statistics data."""

    @pytest.fixture(scope="class")
    def latest_stats(self):
        """Fetch latest visitor statistics data once for the test class."""
        return visitor_statistics.get_latest_visitor_statistics(force_refresh=False)

    def test_required_columns_present(self, latest_stats):
        """Test that all required columns are present."""
        required_columns = {"market", "trips", "nights", "expenditure", "period", "year"}

        assert required_columns.issubset(set(latest_stats.columns)), (
            f"Missing columns: {required_columns - set(latest_stats.columns)}"
        )

    def test_all_markets_present(self, latest_stats):
        """Test that all expected markets are present in the data."""
        expected_markets = {
            "Great Britain",
            "Other Europe",
            "North America",
            "Other Overseas",
            "Republic of Ireland",
            "NI Residents",
            "Total",
        }

        actual_markets = set(latest_stats["market"].unique())

        missing = expected_markets - actual_markets
        assert len(missing) == 0, f"Missing markets: {missing}"

    def test_no_negative_trips(self, latest_stats):
        """Test that trip counts are not negative."""
        assert (latest_stats["trips"] >= 0).all(), "Found negative trip values"

    def test_no_negative_nights(self, latest_stats):
        """Test that nights spent are not negative."""
        assert (latest_stats["nights"] >= 0).all(), "Found negative nights values"

    def test_no_negative_expenditure(self, latest_stats):
        """Test that expenditure values are not negative."""
        assert (latest_stats["expenditure"] >= 0).all(), "Found negative expenditure values"

    def test_total_matches_sum(self, latest_stats):
        """Test that Total row approximately matches sum of individual markets."""
        non_total = latest_stats[latest_stats["market"] != "Total"]
        total_row = latest_stats[latest_stats["market"] == "Total"]

        if len(total_row) > 0:
            expected_trips = non_total["trips"].sum()
            actual_trips = total_row["trips"].iloc[0]

            # Allow 5% tolerance for rounding
            tolerance = 0.05
            assert abs(expected_trips - actual_trips) / actual_trips < tolerance, (
                f"Total trips ({actual_trips:,.0f}) doesn't match sum of markets ({expected_trips:,.0f})"
            )

    def test_nights_greater_than_trips(self, latest_stats):
        """Test that nights spent exceeds trips (multiple nights per trip on average)."""
        for _, row in latest_stats.iterrows():
            if row["trips"] > 0:
                assert row["nights"] >= row["trips"], (
                    f"{row['market']}: nights ({row['nights']:,.0f}) should be >= trips ({row['trips']:,.0f})"
                )

    def test_year_is_recent(self, latest_stats):
        """Test that data year is recent (within last 2 years)."""
        import datetime

        current_year = datetime.datetime.now().year
        data_year = latest_stats["year"].iloc[0]

        if data_year is not None:
            assert data_year >= current_year - 2, f"Data year ({data_year}) is more than 2 years old"

    def test_period_is_valid(self, latest_stats):
        """Test that period value is valid."""
        valid_periods = {"12-month rolling", "year-to-date", "quarterly"}

        for period in latest_stats["period"].unique():
            assert period in valid_periods, f"Invalid period: {period}"


class TestVisitorStatisticsHelperFunctions:
    """Test helper functions for visitor statistics analysis."""

    @pytest.fixture(scope="class")
    def latest_stats(self):
        """Fetch latest visitor statistics data once for the test class."""
        return visitor_statistics.get_latest_visitor_statistics(force_refresh=False)

    def test_get_visitor_statistics_by_market(self, latest_stats):
        """Test the get_visitor_statistics_by_market helper function."""
        gb = visitor_statistics.get_visitor_statistics_by_market(latest_stats, "Great Britain")

        assert gb is not None, "Could not find Great Britain market"
        assert gb["market"] == "Great Britain"
        assert gb["trips"] > 0

    def test_get_visitor_statistics_by_market_case_insensitive(self, latest_stats):
        """Test that market lookup is case insensitive."""
        gb_lower = visitor_statistics.get_visitor_statistics_by_market(latest_stats, "great britain")
        gb_upper = visitor_statistics.get_visitor_statistics_by_market(latest_stats, "GREAT BRITAIN")

        assert gb_lower is not None
        assert gb_upper is not None
        assert gb_lower["trips"] == gb_upper["trips"]

    def test_get_visitor_statistics_by_market_not_found(self, latest_stats):
        """Test that non-existent market returns None."""
        result = visitor_statistics.get_visitor_statistics_by_market(latest_stats, "Atlantis")

        assert result is None

    def test_get_total_visitor_statistics(self, latest_stats):
        """Test the get_total_visitor_statistics helper function."""
        total = visitor_statistics.get_total_visitor_statistics(latest_stats)

        assert total is not None
        assert total["market"] == "Total"
        assert total["trips"] > 0

    def test_get_domestic_vs_external(self, latest_stats):
        """Test the get_domestic_vs_external helper function."""
        comparison = visitor_statistics.get_domestic_vs_external(latest_stats)

        assert len(comparison) == 2
        assert "Domestic (NI)" in comparison["category"].values
        assert "External" in comparison["category"].values

        # Check percentages sum to ~100%
        trips_pct_total = comparison["trips_pct"].sum()
        assert abs(trips_pct_total - 100) < 1, f"Trips percentages sum to {trips_pct_total}%"

    def test_get_expenditure_per_trip(self, latest_stats):
        """Test the get_expenditure_per_trip helper function."""
        spend_per_trip = visitor_statistics.get_expenditure_per_trip(latest_stats)

        assert "expenditure_per_trip" in spend_per_trip.columns
        assert len(spend_per_trip) > 0

        # Expenditure per trip should be positive
        assert (spend_per_trip["expenditure_per_trip"] > 0).all()

        # External visitors typically spend more per trip than NI residents
        ni = spend_per_trip[spend_per_trip["market"] == "NI Residents"]
        gb = spend_per_trip[spend_per_trip["market"] == "Great Britain"]

        if len(ni) > 0 and len(gb) > 0:
            assert gb["expenditure_per_trip"].iloc[0] > ni["expenditure_per_trip"].iloc[0], (
                "GB visitors should spend more per trip than NI residents"
            )

    def test_get_nights_per_trip(self, latest_stats):
        """Test the get_nights_per_trip helper function."""
        nights_per = visitor_statistics.get_nights_per_trip(latest_stats)

        assert "nights_per_trip" in nights_per.columns
        assert len(nights_per) > 0

        # Average nights per trip should be > 1
        assert (nights_per["nights_per_trip"] > 1).all(), "Average nights per trip should be > 1"

    def test_get_market_summary(self, latest_stats):
        """Test the get_market_summary helper function."""
        summary = visitor_statistics.get_market_summary(latest_stats)

        # Check required columns
        expected_cols = {
            "market",
            "trips",
            "trips_pct",
            "expenditure",
            "expenditure_pct",
            "nights_per_trip",
            "expenditure_per_trip",
        }
        assert expected_cols.issubset(set(summary.columns))

        # Total should not be in summary (it's excluded)
        assert "Total" not in summary["market"].values

        # Percentages should sum to ~100%
        trips_pct_total = summary["trips_pct"].sum()
        assert abs(trips_pct_total - 100) < 1, f"Trips percentages sum to {trips_pct_total}%"

    def test_get_domestic_vs_external_no_domestic(self):
        """Test that get_domestic_vs_external returns empty DataFrame when no domestic data."""
        import pandas as pd

        # DataFrame without NI Residents
        no_domestic_df = pd.DataFrame(
            [
                {"market": "Great Britain", "trips": 1000000, "nights": 3000000, "expenditure": 300},
                {"market": "Total", "trips": 1000000, "nights": 3000000, "expenditure": 300},
            ]
        )
        result = visitor_statistics.get_domestic_vs_external(no_domestic_df)

        assert result.empty


class TestVisitorStatisticsValidation:
    """Test validation function."""

    def test_validate_visitor_statistics_valid(self):
        """Test that valid data passes validation."""
        import pandas as pd

        valid_df = pd.DataFrame(
            [
                {"market": "Great Britain", "trips": 1000000, "nights": 3000000, "expenditure": 300},
                {"market": "NI Residents", "trips": 500000, "nights": 1000000, "expenditure": 100},
                {"market": "Total", "trips": 1500000, "nights": 4000000, "expenditure": 400},
            ]
        )

        assert visitor_statistics.validate_visitor_statistics(valid_df) is True

    def test_validate_visitor_statistics_empty(self):
        """Test that empty DataFrame fails validation."""
        import pandas as pd

        empty_df = pd.DataFrame()
        assert visitor_statistics.validate_visitor_statistics(empty_df) is False

    def test_validate_visitor_statistics_missing_columns(self):
        """Test that DataFrame with missing columns fails validation."""
        import pandas as pd

        incomplete_df = pd.DataFrame([{"market": "Great Britain", "trips": 1000000}])
        assert visitor_statistics.validate_visitor_statistics(incomplete_df) is False

    def test_validate_visitor_statistics_negative_trips(self):
        """Test that negative trip values fail validation."""
        import pandas as pd

        negative_df = pd.DataFrame(
            [
                {"market": "Great Britain", "trips": -1000, "nights": 3000000, "expenditure": 300},
                {"market": "NI Residents", "trips": 500000, "nights": 1000000, "expenditure": 100},
                {"market": "Total", "trips": 100000, "nights": 4000000, "expenditure": 400},
            ]
        )
        assert visitor_statistics.validate_visitor_statistics(negative_df) is False

    def test_validate_visitor_statistics_negative_expenditure(self):
        """Test that negative expenditure values fail validation."""
        import pandas as pd

        negative_df = pd.DataFrame(
            [
                {"market": "Great Britain", "trips": 1000000, "nights": 3000000, "expenditure": -300},
                {"market": "NI Residents", "trips": 500000, "nights": 1000000, "expenditure": 100},
                {"market": "Total", "trips": 1500000, "nights": 4000000, "expenditure": 400},
            ]
        )
        assert visitor_statistics.validate_visitor_statistics(negative_df) is False

    def test_validate_visitor_statistics_too_few_markets(self):
        """Test that too few markets fails validation."""
        import pandas as pd

        few_markets_df = pd.DataFrame(
            [
                {"market": "Great Britain", "trips": 1000000, "nights": 3000000, "expenditure": 300},
                {"market": "Total", "trips": 1000000, "nights": 3000000, "expenditure": 300},
            ]
        )
        assert visitor_statistics.validate_visitor_statistics(few_markets_df) is False
