#!/usr/bin/env python
"""Tests for ni_water module with proper mocking of external APIs."""

from unittest.mock import Mock, patch
from urllib.error import HTTPError

import pandas as pd
import pytest

from bolster.data_sources.ni_water import (
    INVALID_ZONE_IDENTIFIER,
    POSTCODE_DATASET_URL,
    T_HARDNESS,
    get_postcode_to_water_supply_zone,
    get_water_quality,
    get_water_quality_by_zone,
)


class TestPostcodeToWaterSupplyZone:
    """Test postcode to water supply zone mapping."""

    @patch('bolster.data_sources.ni_water.requests.get')
    def test_get_postcode_to_water_supply_zone_success(self, mock_get):
        """Test successful retrieval of postcode to zone mapping."""
        # Mock CSV data that matches the doctest expectations
        mock_csv_data = """POSTCODE,2023
BT1 1AA,ZS0107
BT1 1AB,ZS0107
BT2 1AA,ZS0108
BT3 1AA,
BT4 1AA,ZS0109
"""
        # Create a mock response that simulates streaming CSV data
        mock_response = Mock()
        mock_response.iter_lines.return_value = [line.encode('utf-8') for line in mock_csv_data.strip().split('\n')]
        mock_get.return_value.__enter__.return_value = mock_response

        zones = get_postcode_to_water_supply_zone()

        # Verify the function was called with correct URL
        mock_get.assert_called_once_with(POSTCODE_DATASET_URL, stream=True)

        # Test expectations from doctests
        assert isinstance(zones, dict)
        assert zones['BT1 1AA'] == 'ZS0107'
        assert zones['BT1 1AB'] == 'ZS0107'
        assert zones['BT2 1AA'] == 'ZS0108'
        assert zones['BT3 1AA'] == ''  # Empty zone
        assert zones['BT4 1AA'] == 'ZS0109'

    @patch('bolster.data_sources.ni_water.requests.get')
    def test_get_postcode_to_water_supply_zone_empty_response(self, mock_get):
        """Test handling of empty response."""
        # Mock empty CSV data
        mock_csv_data = "POSTCODE,2023\n"
        mock_response = Mock()
        mock_response.iter_lines.return_value = [line.encode('utf-8') for line in mock_csv_data.strip().split('\n')]
        mock_get.return_value.__enter__.return_value = mock_response

        with pytest.raises(RuntimeError, match="No data found"):
            get_postcode_to_water_supply_zone()

    @patch('bolster.data_sources.ni_water.requests.get')
    def test_get_postcode_to_water_supply_zone_http_error_retry(self, mock_get):
        """Test retry logic on HTTP errors."""
        # Create a proper mock response for the successful retry
        mock_response = Mock()
        mock_csv_data = """POSTCODE,2023
BT1 1AA,ZS0107
"""
        mock_response.iter_lines.return_value = [line.encode('utf-8') for line in mock_csv_data.strip().split('\n')]

        # Create a context manager mock for the successful call
        mock_context_manager = Mock()
        mock_context_manager.__enter__ = Mock(return_value=mock_response)
        mock_context_manager.__exit__ = Mock(return_value=None)

        # First call raises HTTPError, second returns context manager
        mock_get.side_effect = [
            HTTPError(url='test', code=404, msg='Not Found', hdrs=None, fp=None),
            mock_context_manager
        ]

        zones = get_postcode_to_water_supply_zone()
        assert zones['BT1 1AA'] == 'ZS0107'

        # Should have been called twice due to retry
        assert mock_get.call_count == 2


class TestWaterQualityByZone:
    """Test water quality retrieval by zone."""

    def test_get_water_quality_by_zone_success(self):
        """Test successful water quality retrieval."""
        # Mock HTML data that pd.read_html would parse
        mock_html_tables = [
            pd.DataFrame({
                0: ['Water Supply Zone', 'Total Hardness (mg/l)', 'Magnesium (mg/l)',
                    'Potassium (mg/l)', 'Calcium (mg/l)', 'Total Hardness (mg CaCO3/l)',
                    'Clark English Degrees', 'French Degrees', 'German Degrees',
                    'NI Hardness Classification', 'Dishwasher Setting'],
                1: ['Dunore Ballygomartin North', '120.5', '15.2', '8.3', '45.1', '150.0',
                    '10.5', '15.0', '8.4', 'Moderately Hard', '3']
            })
        ]

        with patch('bolster.data_sources.ni_water.pd.read_html') as mock_read_html:
            mock_read_html.return_value = mock_html_tables + [pd.DataFrame(), pd.DataFrame()]

            data = get_water_quality_by_zone('ZS0101')

            # Verify the function was called with correct URL
            mock_read_html.assert_called_once_with('https://www.niwater.com/water-quality-lookup.ashx?z=ZS0101')

            # Test expectations from doctests
            assert data.name == 'ZS0101'
            assert data['Water Supply Zone'] == 'Dunore Ballygomartin North'

            # Verify index matches doctest expectations
            expected_index = ['Water Supply Zone', 'Total Hardness (mg/l)', 'Magnesium (mg/l)',
                            'Potassium (mg/l)', 'Calcium (mg/l)', 'Total Hardness (mg CaCO3/l)',
                            'Clark English Degrees', 'French Degrees', 'German Degrees',
                            'NI Hardness Classification', 'Dishwasher Setting']
            assert list(data.index) == expected_index

    def test_get_water_quality_by_zone_xml_syntax_error_strict(self):
        """Test XMLSyntaxError handling in strict mode."""
        from lxml.etree import XMLSyntaxError

        with patch('bolster.data_sources.ni_water.pd.read_html') as mock_read_html:
            # Create a proper XMLSyntaxError
            mock_read_html.side_effect = XMLSyntaxError('Invalid XML', None, 1, 1)

            with pytest.raises(ValueError, match="Potentially invalid Water Supply Zone XXXXXX"):
                get_water_quality_by_zone('XXXXXX', strict=True)

    def test_get_water_quality_by_zone_xml_syntax_error_non_strict(self):
        """Test XMLSyntaxError handling in non-strict mode."""
        from lxml.etree import XMLSyntaxError

        with patch('bolster.data_sources.ni_water.pd.read_html') as mock_read_html:
            # Create a proper XMLSyntaxError
            mock_read_html.side_effect = XMLSyntaxError('Invalid XML', None, 1, 1)

            with patch('bolster.data_sources.ni_water.logging.warning') as mock_warning:
                data = get_water_quality_by_zone('XXXXXX', strict=False)

                # Should return empty Series with zone name
                assert isinstance(data, pd.Series)
                assert data.name == 'XXXXXX'
                assert len(data) == 0

                # Should log warning
                mock_warning.assert_called_once_with("Potentially invalid Water Supply Zone XXXXXX")

    def test_get_water_quality_by_zone_with_report_entries(self):
        """Test filtering out zone water quality report entries."""
        # Mock HTML data with report entries that should be dropped
        mock_html_tables = [
            pd.DataFrame({
                0: ['Water Supply Zone', 'Total Hardness (mg/l)',
                    'Zone water quality report for quarter ending 31 March 2023',
                    'NI Hardness Classification'],
                1: ['Test Zone', '120.5', 'Some report text', 'Soft']
            })
        ]

        with patch('bolster.data_sources.ni_water.pd.read_html') as mock_read_html:
            with patch('bolster.data_sources.ni_water.logging.warning') as mock_warning:
                mock_read_html.return_value = mock_html_tables + [pd.DataFrame(), pd.DataFrame()]

                data = get_water_quality_by_zone('ZS0101')

                # Should drop the report entry and log warning
                assert 'Zone water quality report for quarter ending 31 March 2023' not in data.index
                assert 'Water Supply Zone' in data.index
                assert 'NI Hardness Classification' in data.index

                mock_warning.assert_called_once_with("Dropping Zone water quality report for quarter ending 31 March 2023")


class TestWaterQuality:
    """Test combined water quality data retrieval."""

    @patch('bolster.data_sources.ni_water.get_water_quality_by_zone')
    @patch('bolster.data_sources.ni_water.get_postcode_to_water_supply_zone')
    def test_get_water_quality_success(self, mock_get_zones, mock_get_quality):
        """Test successful water quality DataFrame creation."""
        # Mock zone mapping
        mock_get_zones.return_value = {
            'BT1 1AA': 'ZS0107',
            'BT1 1AB': 'ZS0107',
            'BT2 1AA': 'ZS0108',
            'BT3 1AA': INVALID_ZONE_IDENTIFIER,  # This should be filtered out
            'BT4 1AA': 'ZS0109',
        }

        # Mock water quality data for unique zones
        def mock_quality_side_effect(zone_code):
            quality_data = {
                'ZS0107': pd.Series({
                    'Water Supply Zone': 'Zone A',
                    'Total Hardness (mg/l)': '120.5',
                    'NI Hardness Classification': 'Moderately Hard'
                }, name='ZS0107'),
                'ZS0108': pd.Series({
                    'Water Supply Zone': 'Zone B',
                    'Total Hardness (mg/l)': '80.0',
                    'NI Hardness Classification': 'Soft'
                }, name='ZS0108'),
                'ZS0109': pd.Series({
                    'Water Supply Zone': 'Zone C',
                    'Total Hardness (mg/l)': '150.0',
                    'NI Hardness Classification': 'Slightly Hard'
                }, name='ZS0109'),
            }
            return quality_data.get(zone_code, pd.Series(name=zone_code))

        mock_get_quality.side_effect = mock_quality_side_effect

        df = get_water_quality()

        # Test expectations from doctests
        assert isinstance(df, pd.DataFrame)
        assert df.shape[1] == 3  # Three columns in our mock data

        # Should have 3 rows for unique zones (excluding INVALID_ZONE_IDENTIFIER)
        assert len(df) == 3

        # Verify NI Hardness Classification is properly typed as categorical
        assert df['NI Hardness Classification'].dtype == T_HARDNESS

        # Verify zone filtering - should not include invalid zones
        mock_get_quality.assert_any_call('ZS0107')
        mock_get_quality.assert_any_call('ZS0108')
        mock_get_quality.assert_any_call('ZS0109')

        # Should not call for invalid zone identifier
        calls = [call[0][0] for call in mock_get_quality.call_args_list]
        assert INVALID_ZONE_IDENTIFIER not in calls

    @patch('bolster.data_sources.ni_water.get_water_quality_by_zone')
    @patch('bolster.data_sources.ni_water.get_postcode_to_water_supply_zone')
    def test_get_water_quality_categorical_ordering(self, mock_get_zones, mock_get_quality):
        """Test that hardness classification maintains proper categorical ordering."""
        # Mock zone mapping with single zone
        mock_get_zones.return_value = {'BT1 1AA': 'ZS0107'}

        # Mock water quality data with different hardness levels
        hardness_levels = ['Soft', 'Moderately Soft', 'Slightly Hard', 'Moderately Hard']

        def mock_quality_side_effect(zone_code):
            # Return different hardness levels for different calls
            idx = len(mock_get_quality.call_args_list) - 1
            hardness = hardness_levels[idx % len(hardness_levels)]
            return pd.Series({
                'Water Supply Zone': f'Zone {idx}',
                'NI Hardness Classification': hardness
            }, name=zone_code)

        mock_get_quality.side_effect = mock_quality_side_effect

        df = get_water_quality()

        # Verify categorical dtype
        assert df['NI Hardness Classification'].dtype == T_HARDNESS

        # Verify that value_counts respects categorical ordering when sort=False
        value_counts = df['NI Hardness Classification'].value_counts(sort=False)

        # The index should be in categorical order, not frequency order
        expected_categories = ['Soft', 'Moderately Soft', 'Slightly Hard', 'Moderately Hard']
        # Filter to only categories that appear in our data
        present_categories = [cat for cat in expected_categories if cat in value_counts.index]
        assert list(value_counts.index[:len(present_categories)]) == present_categories


class TestConstants:
    """Test module constants."""

    def test_postcode_dataset_url(self):
        """Test that the dataset URL is properly defined."""
        assert POSTCODE_DATASET_URL.startswith('https://')
        assert 'opendatani.gov.uk' in POSTCODE_DATASET_URL

    def test_hardness_categorical_type(self):
        """Test hardness categorical type definition."""
        expected_categories = ["Soft", "Moderately Soft", "Slightly Hard", "Moderately Hard"]
        assert list(T_HARDNESS.categories) == expected_categories
        assert T_HARDNESS.ordered is True

    def test_invalid_zone_identifier(self):
        """Test invalid zone identifier constant."""
        assert INVALID_ZONE_IDENTIFIER == "No Zone Identified"