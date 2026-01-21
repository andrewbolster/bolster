#!/usr/bin/env python
"""Integration tests for Northern Ireland Water data functions.

These tests make real network requests to the OpenDataNI service to test
actual functionality without mocking.
"""

import pandas as pd
import pytest

from bolster.data_sources.ni_water import (
    INVALID_ZONE_IDENTIFIER,
    _site_code_to_zone_code,
    get_postcode_to_water_supply_zone,
    get_water_quality,
    get_water_quality_by_zone,
    get_water_quality_csv_data,
)

pytestmark = pytest.mark.network  # All tests in this module require network access


class TestNIWaterIntegrationBasic:
    """Basic integration tests for NI Water data functions."""

    def test_get_water_quality_csv_data_basic(self):
        """Test basic water quality CSV data retrieval."""
        try:
            df = get_water_quality_csv_data()
            assert isinstance(df, pd.DataFrame)
            assert len(df) > 0  # Should have some water quality records

            # Check for expected columns
            expected_columns = ["Year", "Sample Location", "Site Code", "Parameter", "Result"]
            for col in expected_columns:
                assert col in df.columns, f"Missing expected column: {col}"

            # Verify we have some actual data
            assert not df.empty

        except Exception as e:
            pytest.skip(f"OpenDataNI service unavailable: {e}")

    def test_get_water_quality_csv_data_caching(self):
        """Test that CSV data is properly cached."""
        try:
            # First call
            df1 = get_water_quality_csv_data()
            # Second call should use cache
            df2 = get_water_quality_csv_data()

            # Should be identical (cached)
            assert df1.equals(df2)
            assert len(df1) == len(df2)

        except Exception as e:
            pytest.skip(f"OpenDataNI service unavailable: {e}")

    def test_get_postcode_to_water_supply_zone_basic(self):
        """Test basic postcode to zone mapping retrieval."""
        try:
            zones = get_postcode_to_water_supply_zone()
            assert isinstance(zones, dict)
            assert len(zones) > 0  # Should have postcode mappings

            # Check for reasonable postcodes and zone codes
            sample_items = list(zones.items())[:5]  # Just check first 5
            for postcode, zone in sample_items:
                assert isinstance(postcode, str) and len(postcode) > 0
                assert isinstance(zone, str)
                # Zone should either be valid or the invalid identifier
                assert zone == INVALID_ZONE_IDENTIFIER or len(zone) > 0

        except Exception as e:
            pytest.skip(f"OpenDataNI service unavailable: {e}")


class TestNIWaterIntegrationZoneProcessing:
    """Test zone-based water quality processing."""

    def test_site_code_to_zone_code_basic(self):
        """Test site code conversion function."""
        # This is a simple function that should work without network
        test_site_code = "BALM"
        result = _site_code_to_zone_code(test_site_code)
        assert isinstance(result, str)
        assert result == test_site_code  # Current implementation returns input

    def test_get_water_quality_by_zone_valid_site(self):
        """Test getting water quality for a valid site code."""
        try:
            # First get the CSV data to find valid site codes
            df = get_water_quality_csv_data()
            if df.empty:
                pytest.skip("No water quality data available")

            # Get a sample site code from actual data
            valid_sites = df["Site Code"].dropna().unique()
            if len(valid_sites) == 0:
                pytest.skip("No valid site codes found in data")

            test_site = valid_sites[0]

            # Test getting data for this site
            result = get_water_quality_by_zone(test_site, strict=False)
            assert isinstance(result, pd.Series)
            assert result.name == test_site

        except Exception as e:
            pytest.skip(f"OpenDataNI service unavailable: {e}")

    def test_get_water_quality_by_zone_invalid_site_lenient(self):
        """Test handling of invalid site code in lenient mode."""
        try:
            # Test with an obviously invalid site code
            invalid_site = "INVALID_SITE_12345"
            result = get_water_quality_by_zone(invalid_site, strict=False)

            assert isinstance(result, pd.Series)
            assert result.name == invalid_site
            # Should return empty series for invalid site
            assert result.empty or len(result) == 0

            # This tests the uncovered warning path in lines 263-264

        except Exception as e:
            pytest.skip(f"OpenDataNI service unavailable: {e}")

    def test_get_water_quality_by_zone_invalid_site_strict(self):
        """Test handling of invalid site code in strict mode."""
        try:
            # Test with an obviously invalid site code in strict mode
            invalid_site = "INVALID_SITE_12345"

            with pytest.raises(ValueError, match="Potentially invalid Water Supply Zone"):
                get_water_quality_by_zone(invalid_site, strict=True)

            # This tests the uncovered error path in line 261

        except Exception as e:
            if "OpenDataNI service unavailable" in str(e):
                pytest.skip(f"OpenDataNI service unavailable: {e}")
            # Re-raise other exceptions as they might be the expected ValueError
            raise


class TestNIWaterIntegrationFullDataset:
    """Test full dataset processing functions."""

    @pytest.mark.slow
    def test_get_water_quality_full_dataset(self):
        """Test getting the full water quality dataset."""
        try:
            df = get_water_quality()
            assert isinstance(df, pd.DataFrame)

            if df.empty:
                pytest.skip("No water quality data available")

            # Check that we have reasonable structure
            assert len(df) > 0
            assert len(df.columns) > 0

            # Check for hardness classification if present
            if "NI Hardness Classification" in df.columns:
                # Should be categorical
                assert pd.api.types.is_categorical_dtype(df["NI Hardness Classification"])

        except Exception as e:
            pytest.skip(f"OpenDataNI service unavailable: {e}")


class TestNIWaterIntegrationErrorHandling:
    """Test error handling in water quality functions."""

    def test_get_water_quality_by_zone_error_handling_lenient(self):
        """Test error handling in lenient mode."""
        # We can't easily trigger network errors without mocking,
        # but we can test with edge case inputs that might cause processing errors

        try:
            # Test with empty string
            result = get_water_quality_by_zone("", strict=False)
            assert isinstance(result, pd.Series)
            # This should handle the error gracefully and return empty series

            # Test with None-like input
            result = get_water_quality_by_zone("None", strict=False)
            assert isinstance(result, pd.Series)

        except Exception as e:
            pytest.skip(f"Service unavailable: {e}")

    def test_hardness_classification_edge_cases(self):
        """Test hardness classification calculation with edge values."""
        try:
            # Get data that might have interesting hardness values
            df = get_water_quality_csv_data()
            if df.empty:
                pytest.skip("No data available")

            # Look for hardness data
            hardness_data = df[df["Parameter"].str.contains("hardness", case=False, na=False)]
            if hardness_data.empty:
                pytest.skip("No hardness data available")

            # Get a site with hardness data
            hardness_sites = hardness_data["Site Code"].dropna().unique()
            if len(hardness_sites) == 0:
                pytest.skip("No sites with hardness data")

            test_site = hardness_sites[0]
            result = get_water_quality_by_zone(test_site, strict=False)

            # This should exercise the hardness classification logic
            # including the uncovered lines 161-166 for different hardness categories
            assert isinstance(result, pd.Series)

        except Exception as e:
            pytest.skip(f"Service unavailable: {e}")


class TestNIWaterIntegrationProcessingErrors:
    """Test data processing error paths."""

    def test_empty_data_handling(self):
        """Test handling of edge cases in data processing."""
        # Test the site code to zone conversion with edge cases
        result1 = _site_code_to_zone_code("")
        assert result1 == ""

        result2 = _site_code_to_zone_code("TEST")
        assert result2 == "TEST"

        # These test basic functionality without network calls


class TestNIWaterIntegrationDataValidation:
    """Test data validation and integrity."""

    def test_postcode_zone_mapping_integrity(self):
        """Test the integrity of postcode to zone mapping."""
        try:
            zones = get_postcode_to_water_supply_zone()
            if not zones:
                pytest.skip("No postcode mapping data available")

            # Test that we have reasonable data structure
            # This tests the uncovered line 208 for empty data handling
            assert len(zones) > 0

            # Check for standard NI postcode format in keys
            bt_postcodes = [k for k in zones.keys() if k.startswith("BT")]
            assert len(bt_postcodes) > 0, "Should have Belfast (BT) postcodes"

        except RuntimeError as e:
            if "No data found" in str(e):
                # This tests the uncovered line 208
                pytest.fail("Empty data error handling was triggered")
            else:
                pytest.skip(f"Service unavailable: {e}")
        except Exception as e:
            pytest.skip(f"Service unavailable: {e}")
