#!/usr/bin/env python
"""Tests for companies_house module."""

import pytest
from typing import Dict

from bolster.data_sources.companies_house import (
    companies_house_record_might_be_farset,
    get_basic_company_data_url,
    query_basic_company_data,
    get_companies_house_records_that_might_be_in_farset,
)


class TestFarsetHeuristicFunction:
    """Test the Farset Labs heuristic business logic."""

    def test_farset_heuristic_correct_postcode_farset_in_address(self):
        """Test that records with correct postcode and 'farset' in address return True."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "Unit 1, Weavers Court Business Park",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_correct_postcode_unit_1(self):
        """Test that records with correct postcode and 'unit 1' return True."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unit 1",
            "RegAddress.AddressLine2": "Weavers Court Business Park",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_wrong_postcode(self):
        """Test that records with wrong postcode return False."""
        record = {
            "RegAddress.PostCode": "BT1 1AB",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "Unit 1",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_correct_postcode_unit_10(self):
        """Test that records with correct postcode and 'unit 10' return False."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unit 10",
            "RegAddress.AddressLine2": "Weavers Court Business Park",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_correct_postcode_unit_17(self):
        """Test that records with correct postcode and 'unit 17' return False."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unit 17",
            "RegAddress.AddressLine2": "Weavers Court Business Park",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_correct_postcode_unit_18(self):
        """Test that records with correct postcode and 'unit 18' return False."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unit 18",
            "RegAddress.AddressLine2": "Weavers Court Business Park",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_correct_postcode_unknown_unit(self):
        """Test that records with correct postcode but unknown address return False."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unknown Business",
            "RegAddress.AddressLine2": "Random Address",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_postcode_case_insensitive(self):
        """Test that postcode matching is case insensitive."""
        record = {
            "RegAddress.PostCode": "bt12 5gh",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_postcode_with_spaces(self):
        """Test that postcode matching handles spaces correctly."""
        # Test with extra spaces
        record = {
            "RegAddress.PostCode": " BT12  5GH ",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

        # Test without spaces
        record = {
            "RegAddress.PostCode": "BT125GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_case_insensitive_address(self):
        """Test that address matching is case insensitive."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "FARSET LABS",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_farset_in_care_of(self):
        """Test that 'farset' in CareOf field is detected."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "C/O Farset Labs",
            "RegAddress.AddressLine1": "Some Company",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_farset_in_address_line_2(self):
        """Test that 'farset' in AddressLine2 field is detected."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Some Company",
            "RegAddress.AddressLine2": "Farset Labs Building",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_empty_fields(self):
        """Test handling of empty or missing address fields."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_missing_fields(self):
        """Test handling when fields are missing from the record."""
        # Missing AddressLine2 (optional field)
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_unit_1_variations(self):
        """Test various ways 'unit 1' might appear."""
        # Standard format
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unit 1, Weavers Court",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

        # Different case
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "UNIT 1",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

        # With different punctuation
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Unit 1;",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True


class TestModuleImports:
    """Test that module imports and function existence."""

    def test_module_functions_exist(self):
        """Test that all expected functions exist in the module."""
        # These functions should be importable
        assert callable(companies_house_record_might_be_farset)
        assert callable(get_basic_company_data_url)
        assert callable(query_basic_company_data)
        assert callable(get_companies_house_records_that_might_be_in_farset)

    def test_basic_company_data_url_function_exists(self):
        """Test that URL function exists and can be called without network operations."""
        # This tests the function definition and import, but doesn't test network calls
        # The actual network call is marked with pragma: no cover
        try:
            # Just test that the function exists and can be called
            # This will trigger the base_url assignment but fail on the network call
            get_basic_company_data_url()
        except Exception:
            # Expected to fail due to network operation, but confirms function callable
            pass

        # Test that the function is properly defined
        import inspect
        assert callable(get_basic_company_data_url)
        sig = inspect.signature(get_basic_company_data_url)
        assert len(sig.parameters) == 0

    def test_farset_heuristic_function_signature(self):
        """Test that the Farset heuristic function has expected signature."""
        import inspect
        sig = inspect.signature(companies_house_record_might_be_farset)
        params = list(sig.parameters.keys())
        assert len(params) == 1
        assert params[0] == 'r'
        assert sig.return_annotation == bool

    def test_get_basic_company_data_url_signature(self):
        """Test that URL function has expected signature."""
        import inspect
        sig = inspect.signature(get_basic_company_data_url)
        assert len(sig.parameters) == 0  # No parameters

    def test_query_basic_company_data_signature(self):
        """Test that query function has expected signature."""
        import inspect
        sig = inspect.signature(query_basic_company_data)
        params = list(sig.parameters.keys())
        assert 'query_func' in params
        # Should have a default value
        assert sig.parameters['query_func'].default is not inspect.Parameter.empty


class TestBusinessLogicEdgeCases:
    """Test edge cases and robustness of business logic."""

    def test_farset_heuristic_none_values(self):
        """Test handling of None values in record fields."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": None,
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": None,
        }
        # Should not crash and should handle None values gracefully
        result = companies_house_record_might_be_farset(record)
        assert isinstance(result, bool)
        assert result is True

    def test_farset_heuristic_numeric_values(self):
        """Test handling of numeric values in address fields."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": 123,  # Numeric instead of string
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": 456,
        }
        # Should convert to string and still work
        result = companies_house_record_might_be_farset(record)
        assert isinstance(result, bool)
        assert result is True

    def test_farset_heuristic_special_characters(self):
        """Test handling of special characters in address."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs & Co.",
            "RegAddress.AddressLine2": "Unit 1 - Building #5",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_unicode_characters(self):
        """Test handling of unicode characters."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs™",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True

    def test_farset_heuristic_empty_postcode(self):
        """Test handling of empty postcode."""
        record = {
            "RegAddress.PostCode": "",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is False

    def test_farset_heuristic_very_long_address(self):
        """Test handling of very long address lines."""
        long_address = "A" * 1000 + "farset" + "B" * 1000
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": long_address,
            "RegAddress.AddressLine2": "",
        }
        assert companies_house_record_might_be_farset(record) is True


class TestCompaniesHouseRecordStructure:
    """Test assumptions about Companies House record structure."""

    def test_expected_field_names(self):
        """Test that the function expects specific field names."""
        # This test documents the expected CSV field structure
        expected_fields = [
            "RegAddress.PostCode",
            "RegAddress.CareOf",
            "RegAddress.AddressLine1",
            "RegAddress.AddressLine2",
        ]

        # Create a minimal valid record
        record = {field: "" for field in expected_fields}
        record["RegAddress.PostCode"] = "BT12 5GH"
        record["RegAddress.AddressLine1"] = "Farset Labs"

        # Should not raise KeyError
        result = companies_house_record_might_be_farset(record)
        assert isinstance(result, bool)

    def test_missing_required_fields(self):
        """Test behavior when required fields are missing."""
        # Missing postcode field should raise KeyError
        record = {
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "",
        }

        with pytest.raises(KeyError):
            companies_house_record_might_be_farset(record)

    def test_extra_fields_ignored(self):
        """Test that extra fields in record are ignored."""
        record = {
            "RegAddress.PostCode": "BT12 5GH",
            "RegAddress.CareOf": "",
            "RegAddress.AddressLine1": "Farset Labs",
            "RegAddress.AddressLine2": "",
            "CompanyName": "Test Company Ltd",
            "CompanyNumber": "12345678",
            "ExtraField": "Should be ignored",
        }

        # Should work normally and ignore extra fields
        assert companies_house_record_might_be_farset(record) is True


class TestHeuristicLogic:
    """Test the specific heuristic logic rules."""

    def test_postcode_normalization(self):
        """Test that postcode normalization works correctly."""
        # The function should normalize by lowercasing and removing spaces
        test_postcodes = [
            "BT12 5GH",    # Standard format
            "bt12 5gh",    # Lowercase
            "BT125GH",     # No space
            "bt125gh",     # Lowercase, no space
            " BT12  5GH ", # Extra spaces
        ]

        for postcode in test_postcodes:
            record = {
                "RegAddress.PostCode": postcode,
                "RegAddress.CareOf": "",
                "RegAddress.AddressLine1": "Farset Labs",
                "RegAddress.AddressLine2": "",
            }
            assert companies_house_record_might_be_farset(record) is True, f"Failed for postcode: {postcode}"

    def test_address_concatenation_logic(self):
        """Test that address fields are properly concatenated and searched."""
        # Test that the function checks all address fields
        address_field_tests = [
            ("RegAddress.CareOf", "Farset Labs", "", ""),
            ("RegAddress.AddressLine1", "", "Farset Labs", ""),
            ("RegAddress.AddressLine2", "", "", "Farset Labs"),
        ]

        for field_name, care_of, line1, line2 in address_field_tests:
            record = {
                "RegAddress.PostCode": "BT12 5GH",
                "RegAddress.CareOf": care_of,
                "RegAddress.AddressLine1": line1,
                "RegAddress.AddressLine2": line2,
            }
            assert companies_house_record_might_be_farset(record) is True, f"Failed when farset in {field_name}"

    def test_unit_exclusion_priority(self):
        """Test that specific unit exclusions take priority over unit 1 inclusion."""
        # Even if "unit 1" appears in the address, if other units (10, 17, 18) also appear,
        # they should take priority and return False

        test_addresses = [
            "Unit 1 and Unit 10 building",  # Should return False due to Unit 10
            "Unit 1 and Unit 17 complex",  # Should return False due to Unit 17
            "Unit 1 and Unit 18 center",   # Should return False due to Unit 18
        ]

        for address in test_addresses:
            record = {
                "RegAddress.PostCode": "BT12 5GH",
                "RegAddress.CareOf": "",
                "RegAddress.AddressLine1": address,
                "RegAddress.AddressLine2": "",
            }
            assert companies_house_record_might_be_farset(record) is False, f"Failed for address: {address}"

    def test_fallback_logic(self):
        """Test the fallback logic when no specific patterns match."""
        # When postcode matches but no farset/unit patterns are found,
        # should return False
        test_addresses = [
            "Random Business Name",
            "Unit 5 Something",  # Not unit 1, 10, 17, or 18
            "Building 2",
            "Suite A",
        ]

        for address in test_addresses:
            record = {
                "RegAddress.PostCode": "BT12 5GH",
                "RegAddress.CareOf": "",
                "RegAddress.AddressLine1": address,
                "RegAddress.AddressLine2": "",
            }
            assert companies_house_record_might_be_farset(record) is False, f"Should return False for: {address}"