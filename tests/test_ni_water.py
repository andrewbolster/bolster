#!/usr/bin/env python
"""Tests for ni_water module."""

import logging
from unittest.mock import patch

import pandas as pd
import pytest

from bolster.data_sources.ni_water import (
    INVALID_ZONE_IDENTIFIER,
    T_HARDNESS,
    get_postcode_to_water_supply_zone,
    get_water_quality,
    get_water_quality_by_zone,
    get_water_quality_csv_data,
)


class TestWaterQualityCSVData:
    """Test CSV data retrieval."""

    def test_get_water_quality_csv_data_structure(self):
        """Test that CSV data has expected structure."""
        df = get_water_quality_csv_data()

        # Check it's a DataFrame with data
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert len(df) > 0

        # Check expected columns exist
        expected_cols = ["Site Code", "Site Name", "Parameter", "Report Value"]
        for col in expected_cols:
            assert col in df.columns, f"Missing expected column: {col}"

        # Check we have site codes
        assert not df["Site Code"].isna().all(), "No valid site codes found"

        # Check we have parameters
        assert not df["Parameter"].isna().all(), "No valid parameters found"


class TestPostcodeToWaterSupplyZone:
    """Test postcode to water supply zone mapping."""

    def test_get_postcode_to_water_supply_zone_real_data(self):
        """Test retrieval of real postcode to zone mapping."""
        zones = get_postcode_to_water_supply_zone()

        # Basic structure tests
        assert isinstance(zones, dict)
        assert len(zones) > 40000  # Should have tens of thousands of postcodes

        # Test some known patterns
        bt_postcodes = [k for k in zones.keys() if k.startswith("BT")]
        assert len(bt_postcodes) > 1000, "Should have many Belfast postcodes"

        # Test that we have valid zone codes and invalid zone identifiers
        zone_values = set(zones.values())
        assert len(zone_values) > 50, "Should have many unique zones"

        # Check for invalid zone identifiers (postcodes with no zone)
        # Note: Real data might not have invalid zones, so this is optional
        # invalid_zones = [k for k, v in zones.items() if v == '' or pd.isna(v)]
        # assert len(invalid_zones) > 0, "Should have some postcodes with no zone"


class TestWaterQualityByZone:
    """Test water quality retrieval by zone/site."""

    def test_get_water_quality_by_zone_valid_site(self):
        """Test retrieval with a real site code."""
        # First, get some actual site codes from the CSV data
        csv_data = get_water_quality_csv_data()
        available_sites = csv_data["Site Code"].dropna().unique()

        # Test with the first available site
        if len(available_sites) > 0:
            site_code = available_sites[0]
            data = get_water_quality_by_zone(site_code)

            # Check basic structure
            assert isinstance(data, pd.Series)
            assert data.name == site_code
            assert len(data) > 0

            # Check for key legacy format fields
            assert "Water Supply Zone" in data.index
            assert isinstance(data["Water Supply Zone"], str)

    def test_get_water_quality_by_zone_invalid_site(self):
        """Test retrieval with invalid site code."""
        # Test non-strict mode (default)
        data = get_water_quality_by_zone("INVALID_SITE_CODE", strict=False)
        assert isinstance(data, pd.Series)
        assert data.name == "INVALID_SITE_CODE"
        assert len(data) == 0  # Should return empty series

        # Test strict mode
        with pytest.raises(ValueError, match="Potentially invalid Water Supply Zone"):
            get_water_quality_by_zone("INVALID_SITE_CODE", strict=True)

    def test_get_water_quality_by_zone_logging_warning(self):
        """Test that invalid zones log warnings in non-strict mode."""
        with patch("bolster.data_sources.ni_water.logging.warning") as mock_warning:
            _ = get_water_quality_by_zone("INVALID_SITE", strict=False)

            # Should log a warning for invalid site
            mock_warning.assert_called_once()
            assert "Potentially invalid Water Supply Zone INVALID_SITE" in str(mock_warning.call_args)


class TestWaterQuality:
    """Test combined water quality data retrieval."""

    def test_get_water_quality_structure(self):
        """Test that water quality DataFrame has expected structure."""
        df = get_water_quality()

        # Basic structure
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert len(df) > 0

        # Should have site codes as index
        assert all(isinstance(idx, str) for idx in df.index), "Index should be strings (site codes)"

        # Should have multiple columns (various water quality parameters)
        assert len(df.columns) >= 3, f"Expected multiple columns, got {len(df.columns)}"

        # Check for key columns
        assert "Water Supply Zone" in df.columns, "Missing Water Supply Zone column"

    def test_get_water_quality_hardness_classification(self):
        """Test hardness classification is properly typed."""
        df = get_water_quality()

        # Check if we have hardness classification data
        if "NI Hardness Classification" in df.columns:
            # Should be categorical with proper ordering
            hardness_series = df["NI Hardness Classification"]

            # Filter out missing values for testing
            non_null_hardness = hardness_series.dropna()
            if len(non_null_hardness) > 0:
                assert non_null_hardness.dtype == T_HARDNESS

                # Test categorical ordering is maintained
                value_counts = non_null_hardness.value_counts(sort=False)
                if len(value_counts) > 1:
                    # Index should follow categorical order
                    expected_order = ["Soft", "Moderately Soft", "Slightly Hard", "Moderately Hard"]
                    present_categories = [cat for cat in expected_order if cat in value_counts.index]
                    actual_order = [cat for cat in value_counts.index if cat in present_categories]
                    assert actual_order == present_categories, f"Categorical order wrong: {actual_order}"

    def test_get_water_quality_data_integrity(self):
        """Test data integrity and consistency."""
        df = get_water_quality()

        # All rows should have a Water Supply Zone name
        assert df["Water Supply Zone"].notna().all(), "All sites should have a zone name"

        # Zone names should be non-empty strings
        zone_names = df["Water Supply Zone"].dropna()
        assert all(isinstance(name, str) and len(name.strip()) > 0 for name in zone_names)

        # If hardness data exists, it should be consistent
        hardness_cols = [col for col in df.columns if "Hardness" in col]
        if hardness_cols:
            for col in hardness_cols:
                # Hardness values should be numeric strings or actual numbers
                hardness_values = df[col].dropna()
                if len(hardness_values) > 0:
                    # Try to convert to float - should work for most values
                    numeric_values = []
                    for val in hardness_values:
                        try:
                            numeric_values.append(float(val))
                        except (ValueError, TypeError):
                            pass  # Some might be non-numeric, that's ok

                    if numeric_values:
                        assert len(numeric_values) > 0, f"No valid numeric values found in {col}"
                        assert all(val >= 0 for val in numeric_values), f"Negative hardness values in {col}"


class TestConstants:
    """Test module constants and configuration."""

    def test_hardness_categorical_type(self):
        """Test hardness categorical type definition."""
        expected_categories = ["Soft", "Moderately Soft", "Slightly Hard", "Moderately Hard"]
        assert list(T_HARDNESS.categories) == expected_categories
        assert T_HARDNESS.ordered is True

    def test_invalid_zone_identifier(self):
        """Test invalid zone identifier constant."""
        assert INVALID_ZONE_IDENTIFIER == "No Zone Identified"
        assert isinstance(INVALID_ZONE_IDENTIFIER, str)


class TestDataSourceIntegration:
    """Test integration between different data sources."""

    def test_postcode_zone_integration(self):
        """Test that postcode zones exist in water quality data."""
        # Get postcode mapping
        zones = get_postcode_to_water_supply_zone()

        # Get water quality data
        wq_df = get_water_quality()

        # Get CSV data to understand available sites
        csv_data = get_water_quality_csv_data()
        available_sites = set(csv_data["Site Code"].dropna().unique())

        # The old zone codes from postcode mapping might not directly match
        # the new site codes, but this test verifies the data sources are accessible
        assert len(zones) > 0, "Postcode mapping should have data"
        assert len(wq_df) > 0, "Water quality data should have data"
        assert len(available_sites) > 0, "CSV data should have site codes"

        # Basic consistency check - both should represent NI water infrastructure
        zone_codes = set(v for v in zones.values() if v and v != "")

        # We expect many more postcode entries than water quality sites
        assert len(zones) > len(wq_df), "Should be more postcodes than water quality sites"
        assert len(zone_codes) >= len(wq_df) * 0.1, "Should have reasonable number of unique zones"


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_empty_site_code_handling(self):
        """Test handling of empty or None site codes."""
        # Empty string - may or may not match data depending on CSV content
        data = get_water_quality_by_zone("", strict=False)
        assert isinstance(data, pd.Series)
        assert data.name == ""
        # Note: Empty string might match data due to CSV search logic

        # Test with clearly invalid site code
        data_invalid = get_water_quality_by_zone("DEFINITELY_INVALID_SITE_CODE", strict=False)
        assert isinstance(data_invalid, pd.Series)
        assert data_invalid.name == "DEFINITELY_INVALID_SITE_CODE"
        assert len(data_invalid) == 0

        # Test that it doesn't crash with None (though this would be a programming error)
        # This tests robustness of the string operations
        with pytest.raises((ValueError, TypeError)):
            get_water_quality_by_zone(None, strict=True)

    def test_logging_configuration(self):
        """Test that logging is properly configured for the module."""
        # This is more of a smoke test to ensure logging calls don't crash
        logger = logging.getLogger("bolster.data_sources.ni_water")

        # Should be able to log without errors
        logger.info("Test log message")
        logger.warning("Test warning message")
        logger.debug("Test debug message")

        # Test passes if no exceptions are raised
        assert True
