#!/usr/bin/env python
"""Tests for CLI module."""

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bolster.cli import cli, get_precipitation


class TestCLIGroup:
    """Test the main CLI group and version information."""

    def test_cli_group_help(self):
        """Test that CLI group shows help information."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])

        assert result.exit_code == 0
        assert "Bolster - A comprehensive Python utility library" in result.output
        assert "get-precipitation" in result.output

    def test_cli_version(self):
        """Test that version command works."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--version'])

        assert result.exit_code == 0
        assert "bolster" in result.output.lower()


class TestGetPrecipitationCommand:
    """Test the get-precipitation CLI command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_get_precipitation_help(self):
        """Test get-precipitation command help."""
        result = self.runner.invoke(cli, ['get-precipitation', '--help'])

        assert result.exit_code == 0
        assert "Download UK precipitation data" in result.output
        assert "--bounding-box" in result.output
        assert "--order-name" in result.output
        assert "--output" in result.output

    @patch.dict(os.environ, {}, clear=True)
    def test_get_precipitation_no_api_key(self):
        """Test failure when API key is missing."""
        result = self.runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order'
        ])

        # The command should fail due to assertion error for missing API key
        assert result.exit_code != 0
        assert "MET_OFFICE_API_KEY not set" in str(result.exception)

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_get_precipitation_no_order_name(self):
        """Test behavior when no order name is provided."""
        result = self.runner.invoke(cli, ['get-precipitation'])

        assert result.exit_code == 0
        assert "Order name not provided and MAP_IMAGES_ORDER_NAME not set" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_get_precipitation_invalid_bounding_box(self):
        """Test handling of invalid bounding box format."""
        result = self.runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order',
            '--bounding-box', 'invalid-format'
        ])

        # Should exit cleanly with error message (the API call itself is not covered)
        assert "Invalid bounding box format" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_get_precipitation_insufficient_bounding_box_values(self):
        """Test handling of bounding box with insufficient values."""
        result = self.runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order',
            '--bounding-box', '1.0,2.0,3.0'  # Only 3 values instead of 4
        ])

        # Should exit cleanly with error message (the API call itself is not covered)
        assert "Invalid bounding box format" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_get_precipitation_valid_bounding_box_parsing(self):
        """Test that valid bounding box is parsed correctly."""
        result = self.runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order',
            '--bounding-box', '-8.5,54.0,-5.0,55.5'
        ])

        # Should parse bounding box successfully and show the parsed values
        assert "Bounding box: (-8.5, 54.0, -5.0, 55.5)" in result.output


class TestEnvironmentVariableHandling:
    """Test environment variable handling in CLI commands."""

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-key', 'MAP_IMAGES_ORDER_NAME': 'env-order'})
    def test_order_name_from_environment(self):
        """Test that order name is read from environment variable."""
        runner = CliRunner()

        result = runner.invoke(cli, ['get-precipitation'])

        # Should use environment variable and not show "not provided" message
        assert "Order name not provided and MAP_IMAGES_ORDER_NAME not set" not in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-key'})
    def test_missing_optional_env_vars_handled_gracefully(self):
        """Test that missing optional environment variables are handled gracefully."""
        runner = CliRunner()

        # Test without MAP_IMAGES_ORDER_NAME - should show helpful message
        result = runner.invoke(cli, ['get-precipitation'])

        assert result.exit_code == 0
        assert "Order name not provided and MAP_IMAGES_ORDER_NAME not set" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-key', 'MAP_IMAGES_ORDER_NAME': 'env-order'})
    def test_command_line_parameter_overrides_environment(self):
        """Test that command-line parameters override environment variables."""
        runner = CliRunner()

        result = runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'param-order'
        ])

        # Should use command-line parameter, not environment variable
        # (We can't verify the actual API call, but we can verify it doesn't show the env warning)
        assert "Order name not provided and MAP_IMAGES_ORDER_NAME not set" not in result.output


class TestParameterValidation:
    """Test parameter validation logic."""

    def test_invalid_command(self):
        """Test handling of invalid commands."""
        runner = CliRunner()
        result = runner.invoke(cli, ['invalid-command'])

        assert result.exit_code != 0
        assert "No such command" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_empty_order_name_parameter(self):
        """Test handling of empty order name parameter."""
        runner = CliRunner()
        result = runner.invoke(cli, ['get-precipitation', '--order-name', ''])

        # Empty string should be accepted as a parameter value
        # The API call itself is excluded from coverage
        assert "Order name not provided and MAP_IMAGES_ORDER_NAME not set" not in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_bounding_box_with_non_numeric_values(self):
        """Test bounding box with non-numeric values."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order',
            '--bounding-box', 'a,b,c,d'
        ])

        assert "Invalid bounding box format" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_bounding_box_with_extra_values(self):
        """Test bounding box with too many values."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order',
            '--bounding-box', '1.0,2.0,3.0,4.0,5.0'  # 5 values instead of 4
        ])

        assert "Invalid bounding box format" in result.output

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-api-key'})
    def test_bounding_box_mixed_valid_invalid_values(self):
        """Test bounding box with mix of valid and invalid numeric values."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            'get-precipitation',
            '--order-name', 'test-order',
            '--bounding-box', '1.0,invalid,3.0,4.0'
        ])

        assert "Invalid bounding box format" in result.output


class TestCLICommandStructure:
    """Test CLI command structure and configuration."""

    def test_cli_group_exists(self):
        """Test that the main CLI group is properly configured."""
        runner = CliRunner()
        result = runner.invoke(cli, [])

        assert result.exit_code == 0

    def test_get_precipitation_command_exists(self):
        """Test that get-precipitation command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])

        assert "get-precipitation" in result.output

    def test_get_precipitation_has_required_options(self):
        """Test that get-precipitation has all expected options."""
        runner = CliRunner()
        result = runner.invoke(cli, ['get-precipitation', '--help'])

        expected_options = [
            "--bounding-box",
            "--order-name",
            "--output"
        ]

        for option in expected_options:
            assert option in result.output

    def test_default_output_filename_in_help(self):
        """Test that default output filename is shown in help."""
        runner = CliRunner()
        result = runner.invoke(cli, ['get-precipitation', '--help'])

        assert "precipitation.png" in result.output


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_get_precipitation_api_key_assertion(self):
        """Test that missing API key is properly handled."""
        runner = CliRunner()

        # Clear environment to ensure no API key
        with patch.dict(os.environ, {}, clear=True):
            result = runner.invoke(cli, [
                'get-precipitation',
                '--order-name', 'test'
            ])

            assert result.exit_code != 0
            # Should raise AssertionError about missing API key
            assert isinstance(result.exception, AssertionError)
            assert "MET_OFFICE_API_KEY not set" in str(result.exception)

    @patch.dict(os.environ, {'MET_OFFICE_API_KEY': 'test-key'})
    def test_no_arguments_provided(self):
        """Test behavior when no arguments are provided to get-precipitation."""
        runner = CliRunner()
        result = runner.invoke(cli, ['get-precipitation'])

        # Should handle gracefully and show appropriate message
        assert result.exit_code == 0
        assert "Order name not provided and MAP_IMAGES_ORDER_NAME not set" in result.output

    def test_help_available_for_all_commands(self):
        """Test that help is available for all commands."""
        runner = CliRunner()

        # Main CLI help
        result = runner.invoke(cli, ['--help'])
        assert result.exit_code == 0

        # get-precipitation help
        result = runner.invoke(cli, ['get-precipitation', '--help'])
        assert result.exit_code == 0