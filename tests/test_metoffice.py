#!/usr/bin/env python
"""Tests for Met Office module."""

from datetime import datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

from bolster.data_sources.metoffice import (
    BASE_URL,
    filter_relevant_files,
    generate_image,
    get_file,
    get_file_meta,
    get_order_latest,
    get_uk_precipitation,
    is_my_date,
    make_borders,
    make_isolines,
    make_precipitation,
)


class TestConstants:
    """Test module constants and configuration."""

    def test_base_url_configured(self):
        """Test that BASE_URL is properly configured."""
        assert BASE_URL == "https://data.hub.api.metoffice.gov.uk/map-images/1.0.0"

    def test_regex_pattern_exists(self):
        """Test that the date regex pattern is defined."""
        assert is_my_date is not None
        assert hasattr(is_my_date, "match")


class TestDateRegexPattern:
    """Test the date regex pattern for file filtering."""

    def test_regex_matches_valid_date_files(self):
        """Test that regex matches files ending with 10 digits."""
        valid_files = [
            "parameter_name_t+24_1234567890",
            "complex_parameter_name_t+00_9876543210",
            "pressure_t+48_1122334455",
        ]

        for filename in valid_files:
            assert is_my_date.match(filename), f"Should match: {filename}"

    def test_regex_rejects_invalid_files(self):
        """Test that regex rejects files not ending with 10 digits."""
        invalid_files = [
            "parameter_name_t+24_123456789",  # 9 digits
            "parameter_name_t+24_12345678901",  # 11 digits
            "parameter_name_t+24_abcdefghij",  # letters
            "parameter_name_t+24",  # no digits
            "parameter_name",  # no pattern at all
        ]

        for filename in invalid_files:
            assert not is_my_date.match(filename), f"Should not match: {filename}"


class TestFilterRelevantFiles:
    """Test the file filtering logic."""

    def create_mock_order_status(self, files_data):
        """Create a mock order status with given files data."""
        return {"orderDetails": {"files": [{"fileId": file_data["fileId"]} for file_data in files_data]}}

    def test_filter_empty_file_list(self):
        """Test filtering with empty file list."""
        order_status = self.create_mock_order_status([])
        result = filter_relevant_files(order_status)
        assert result == []

    def test_filter_no_matching_files(self):
        """Test filtering when no files match the pattern."""
        files_data = [
            {"fileId": "invalid_file_name"},
            {"fileId": "another_invalid_123"},
            {"fileId": "file_without_digits"},
        ]
        order_status = self.create_mock_order_status(files_data)
        result = filter_relevant_files(order_status)
        assert result == []

    def test_filter_valid_files_parsing(self):
        """Test that valid files are correctly parsed."""
        # Test file: pressure_t+24_2023120812
        # Should parse as: parameter=pressure, time_step=t+24, forecast=2023120812
        files_data = [{"fileId": "pressure_t+24_2023120812"}]
        order_status = self.create_mock_order_status(files_data)
        result = filter_relevant_files(order_status)

        assert len(result) == 1
        file_info = result[0]

        assert file_info["fileId"] == "pressure_t+24_2023120812"
        assert file_info["parameter_name"] == "pressure"
        assert file_info["delta"] == 24

        # Check the parsed date: 2023-12-08 12:00 + 24 hours = 2023-12-09 12:00
        expected_date = datetime(2023, 12, 9, 12, 0)  # Base + 24 hours
        assert file_info["date"] == expected_date

    def test_filter_complex_parameter_name(self):
        """Test parsing files with complex parameter names containing underscores."""
        files_data = [{"fileId": "mean_sea_level_pressure_t+00_2023120900"}]
        order_status = self.create_mock_order_status(files_data)
        result = filter_relevant_files(order_status)

        assert len(result) == 1
        file_info = result[0]

        assert file_info["parameter_name"] == "mean_sea_level_pressure"
        assert file_info["delta"] == 0

        # Check the parsed date: 2023-12-09 00:00 + 0 hours = 2023-12-09 00:00
        expected_date = datetime(2023, 12, 9, 0, 0)
        assert file_info["date"] == expected_date

    def test_filter_multiple_files_sorted(self):
        """Test that multiple files are correctly sorted by date and delta."""
        files_data = [
            {"fileId": "pressure_t+48_2023120800"},  # 2023-12-10 00:00
            {"fileId": "pressure_t+24_2023120800"},  # 2023-12-09 00:00
            {"fileId": "pressure_t+00_2023120900"},  # 2023-12-09 00:00 (earlier delta)
        ]
        order_status = self.create_mock_order_status(files_data)
        result = filter_relevant_files(order_status)

        assert len(result) == 3

        # Should be sorted by date, then by delta
        # First: 2023-12-09 00:00 with delta 0
        assert result[0]["delta"] == 0
        assert result[0]["date"] == datetime(2023, 12, 9, 0, 0)

        # Second: 2023-12-09 00:00 with delta 24
        assert result[1]["delta"] == 24
        assert result[1]["date"] == datetime(2023, 12, 9, 0, 0)

        # Third: 2023-12-10 00:00 with delta 48
        assert result[2]["delta"] == 48
        assert result[2]["date"] == datetime(2023, 12, 10, 0, 0)

    def test_filter_mixed_valid_invalid_files(self):
        """Test filtering with mix of valid and invalid files."""
        files_data = [
            {"fileId": "invalid_file"},
            {"fileId": "pressure_t+00_2023120800"},
            {"fileId": "another_invalid"},
            {"fileId": "temperature_t+12_2023120812"},
            {"fileId": "bad_format_123"},
        ]
        order_status = self.create_mock_order_status(files_data)
        result = filter_relevant_files(order_status)

        # Should only return the 2 valid files
        assert len(result) == 2
        assert all("pressure" in f["parameter_name"] or "temperature" in f["parameter_name"] for f in result)

    def test_filter_time_delta_parsing(self):
        """Test that time delta is correctly parsed from different formats."""
        test_cases = [
            ("param_t+00_2023120800", 0),
            ("param_t+06_2023120800", 6),
            ("param_t+24_2023120800", 24),
            ("param_t+72_2023120800", 72),
        ]

        for file_id, expected_delta in test_cases:
            files_data = [{"fileId": file_id}]
            order_status = self.create_mock_order_status(files_data)
            result = filter_relevant_files(order_status)

            assert len(result) == 1
            assert result[0]["delta"] == expected_delta, f"Failed for {file_id}"


class TestImageProcessingFunctions:
    """Test the image processing functions that don't require network calls."""

    def create_test_image_data(self, width=100, height=100, mode="L"):
        """Create test image data in bytes format."""
        # Create a test image with some pattern
        img = Image.new(mode, (width, height), color=128)

        # Add some pattern to make processing more interesting
        for x in range(0, width, 10):
            for y in range(0, height, 10):
                img.putpixel((x, y), 255)

        # Convert to bytes
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_make_borders_processing(self):
        """Test border detection image processing."""
        test_data = self.create_test_image_data()
        result = make_borders(test_data)

        assert isinstance(result, Image.Image)
        assert result.mode == "1"  # Should be binary image
        assert "transparency" in result.info

    def test_make_isolines_processing(self):
        """Test isoline detection image processing."""
        test_data = self.create_test_image_data()
        result = make_isolines(test_data)

        assert isinstance(result, Image.Image)
        assert result.mode == "1"  # Should be binary image
        assert "transparency" in result.info

    def test_make_precipitation_processing(self):
        """Test precipitation image processing."""
        test_data = self.create_test_image_data()
        result = make_precipitation(test_data)

        assert isinstance(result, Image.Image)
        assert result.mode == "L"  # Should be grayscale
        assert "transparency" in result.info

    def test_image_processing_with_different_sizes(self):
        """Test image processing with different image sizes."""
        sizes = [(50, 50), (200, 100), (100, 200)]

        for width, height in sizes:
            test_data = self.create_test_image_data(width, height)

            border_result = make_borders(test_data)
            assert border_result.size == (width, height)

            isoline_result = make_isolines(test_data)
            assert isoline_result.size == (width, height)

            precip_result = make_precipitation(test_data)
            assert precip_result.size == (width, height)

    def test_image_processing_with_color_image(self):
        """Test image processing functions with color input."""
        # Test with color image (RGB mode)
        test_data = self.create_test_image_data(mode="RGB")

        # All functions should handle color input gracefully
        border_result = make_borders(test_data)
        assert isinstance(border_result, Image.Image)

        isoline_result = make_isolines(test_data)
        assert isinstance(isoline_result, Image.Image)

        precip_result = make_precipitation(test_data)
        assert isinstance(precip_result, Image.Image)


class TestModuleImports:
    """Test module imports and function signatures."""

    def test_all_functions_importable(self):
        """Test that all expected functions are importable."""
        functions = [
            filter_relevant_files,
            make_borders,
            make_isolines,
            make_precipitation,
            get_order_latest,
            get_file_meta,
            get_file,
            get_uk_precipitation,
            generate_image,
        ]

        for func in functions:
            assert callable(func)

    def test_filter_relevant_files_signature(self):
        """Test filter_relevant_files function signature."""
        import inspect

        sig = inspect.signature(filter_relevant_files)
        params = list(sig.parameters.keys())
        assert len(params) == 1
        assert params[0] == "order_status"

    def test_image_processing_function_signatures(self):
        """Test image processing function signatures."""
        import inspect

        # All image processing functions should take 1 parameter (data)
        for func in [make_borders, make_isolines, make_precipitation]:
            sig = inspect.signature(func)
            assert len(sig.parameters) == 1
            param_name = list(sig.parameters.keys())[0]
            assert param_name == "data"

    def test_generate_image_signature(self):
        """Test generate_image function signature."""
        import inspect

        sig = inspect.signature(generate_image)
        params = list(sig.parameters.keys())

        assert "order_name" in params
        assert "block" in params
        assert "bounding_box" in params

        # bounding_box should have a default value
        assert sig.parameters["bounding_box"].default == (100, 250, 500, 550)


class TestNetworkFunctionDefinitions:
    """Test that network functions exist but don't test network operations."""

    def test_network_functions_exist(self):
        """Test that network-dependent functions exist and are callable."""
        # These functions should exist but their network calls are excluded from coverage
        network_functions = [
            get_order_latest,
            get_file_meta,
            get_file,
            get_uk_precipitation,
            generate_image,
        ]

        for func in network_functions:
            assert callable(func)

    def test_get_order_latest_signature(self):
        """Test get_order_latest function signature without calling it."""
        import inspect

        sig = inspect.signature(get_order_latest)
        params = list(sig.parameters.keys())
        assert len(params) == 1
        assert params[0] == "order_name"

    def test_get_file_meta_signature(self):
        """Test get_file_meta function signature without calling it."""
        import inspect

        sig = inspect.signature(get_file_meta)
        params = list(sig.parameters.keys())
        assert len(params) == 2
        assert "order_name" in params
        assert "file_id" in params

    def test_get_file_signature(self):
        """Test get_file function signature without calling it."""
        import inspect

        sig = inspect.signature(get_file)
        params = list(sig.parameters.keys())
        assert len(params) == 2
        assert "order_name" in params
        assert "file_id" in params

    def test_get_uk_precipitation_signature(self):
        """Test get_uk_precipitation function signature without calling it."""
        import inspect

        sig = inspect.signature(get_uk_precipitation)
        params = list(sig.parameters.keys())
        assert "order_name" in params
        assert "bounding_box" in params

        # bounding_box should have default None
        assert sig.parameters["bounding_box"].default is None


class TestBusinessLogicEdgeCases:
    """Test edge cases and error handling in business logic."""

    def test_filter_relevant_files_malformed_order_status(self):
        """Test filter_relevant_files with malformed order status."""
        # Missing orderDetails
        with pytest.raises(KeyError):
            filter_relevant_files({})

        # Missing files in orderDetails
        with pytest.raises(KeyError):
            filter_relevant_files({"orderDetails": {}})

    def test_filter_relevant_files_empty_file_objects(self):
        """Test filter_relevant_files with empty file objects."""
        order_status = {
            "orderDetails": {
                "files": [
                    {},  # Empty file object
                    {"fileId": ""},  # Empty fileId
                    {"fileId": "valid_t+00_1234567890"},  # Valid file
                ]
            }
        }

        # Should handle empty objects gracefully and only process valid ones
        with pytest.raises(KeyError):
            filter_relevant_files(order_status)

    def test_filter_relevant_files_invalid_date_format(self):
        """Test filter_relevant_files with invalid date components in filename."""
        files_data = [
            {"fileId": "param_t+00_202313xxxx"},  # Invalid month
            {"fileId": "param_t+00_20231332xx"},  # Invalid day
            {"fileId": "param_t+00_2023123025"},  # Invalid hour
        ]
        order_status = {"orderDetails": {"files": files_data}}

        # Should raise ValueError when trying to create invalid datetime
        with pytest.raises(ValueError):
            filter_relevant_files(order_status)

    def test_image_processing_with_invalid_data(self):
        """Test image processing functions with invalid data."""
        invalid_data = b"not-an-image"

        # Should raise exceptions when trying to process invalid image data
        with pytest.raises(Exception):  # PIL will raise various exceptions
            make_borders(invalid_data)

        with pytest.raises(Exception):
            make_isolines(invalid_data)

        with pytest.raises(Exception):
            make_precipitation(invalid_data)


class TestDateParsingLogic:
    """Test the specific date parsing logic in detail."""

    def test_forecast_date_parsing_components(self):
        """Test individual components of date parsing."""
        # Test file: param_t+12_2023120815 should parse as:
        # Year: 2023, Month: 12, Day: 08, Hour: 15, Delta: +12 hours
        # Final date: 2023-12-09 03:00

        files_data = [{"fileId": "param_t+12_2023120815"}]
        order_status = {"orderDetails": {"files": files_data}}
        result = filter_relevant_files(order_status)

        assert len(result) == 1
        file_info = result[0]

        # Check individual parsing
        assert file_info["parameter_name"] == "param"
        assert file_info["delta"] == 12

        # Check final computed date
        base_date = datetime(2023, 12, 8, 15, 0)
        expected_date = base_date + timedelta(hours=12)
        assert file_info["date"] == expected_date

    def test_edge_date_cases(self):
        """Test edge cases in date parsing."""
        edge_cases = [
            # Year rollover: Dec 31 23:00 + 24 hours = Jan 1 23:00 next year
            ("param_t+24_2023123123", datetime(2024, 1, 1, 23, 0)),
            # Month rollover: Jan 31 12:00 + 48 hours = Feb 2 12:00
            ("param_t+48_2023013112", datetime(2023, 2, 2, 12, 0)),
            # Day rollover: Any day 23:00 + 2 hours = next day 01:00
            ("param_t+02_2023061523", datetime(2023, 6, 16, 1, 0)),
        ]

        for file_id, expected_date in edge_cases:
            files_data = [{"fileId": file_id}]
            order_status = {"orderDetails": {"files": files_data}}
            result = filter_relevant_files(order_status)

            assert len(result) == 1
            assert result[0]["date"] == expected_date, f"Failed for {file_id}"

    def test_zero_delta_handling(self):
        """Test handling of zero time delta (t+00)."""
        files_data = [{"fileId": "param_t+00_2023120812"}]
        order_status = {"orderDetails": {"files": files_data}}
        result = filter_relevant_files(order_status)

        assert len(result) == 1
        file_info = result[0]

        assert file_info["delta"] == 0
        # Should be the exact same as the forecast date
        assert file_info["date"] == datetime(2023, 12, 8, 12, 0)


class TestParameterNameParsing:
    """Test parameter name parsing from file IDs."""

    def test_simple_parameter_names(self):
        """Test parsing of simple parameter names."""
        test_cases = [
            ("pressure_t+00_2023120812", "pressure"),
            ("temperature_t+12_2023120812", "temperature"),
            ("humidity_t+24_2023120812", "humidity"),
        ]

        for file_id, expected_param in test_cases:
            files_data = [{"fileId": file_id}]
            order_status = {"orderDetails": {"files": files_data}}
            result = filter_relevant_files(order_status)

            assert len(result) == 1
            assert result[0]["parameter_name"] == expected_param

    def test_complex_parameter_names(self):
        """Test parsing of complex parameter names with multiple underscores."""
        test_cases = [
            ("mean_sea_level_pressure_t+00_2023120812", "mean_sea_level_pressure"),
            ("total_precipitation_rate_t+12_2023120812", "total_precipitation_rate"),
            ("wind_speed_at_10m_t+24_2023120812", "wind_speed_at_10m"),
        ]

        for file_id, expected_param in test_cases:
            files_data = [{"fileId": file_id}]
            order_status = {"orderDetails": {"files": files_data}}
            result = filter_relevant_files(order_status)

            assert len(result) == 1
            assert result[0]["parameter_name"] == expected_param
