#!/usr/bin/env python
"""Tests for `bolster` package."""

import sys

import pytest
from click.testing import CliRunner

from bolster.cli import cli


@pytest.fixture
def response():
    """Sample pytest fixture.

    See more at: http://doc.pytest.org/en/latest/fixture.html
    """
    # import requests
    # return requests.get('https://github.com/audreyr/cookiecutter-pypackage')


def test_content(response):
    """Sample pytest test function with the pytest fixture as an argument."""
    # from bs4 import BeautifulSoup
    # assert 'GitHub' in BeautifulSoup(response.content).title.string


@pytest.mark.skipif(sys.version_info < (3, 10), reason="Click exit code behavior differs on Python 3.9")
def test_command_line_interface_exit_code():
    """Test the CLI exit code for newer Python versions."""
    runner = CliRunner()
    result = runner.invoke(cli)
    assert result.exit_code == 2


@pytest.mark.skipif(sys.version_info >= (3, 10), reason="Click exit code behavior differs on Python 3.10+")
def test_command_line_interface_exit_code_python39():
    """Test the CLI exit code for Python 3.9."""
    runner = CliRunner()
    result = runner.invoke(cli)
    assert result.exit_code == 0


def test_command_line_interface():
    """Test the CLI help functionality."""
    runner = CliRunner()

    # Help should work properly regardless of Python version
    help_result = runner.invoke(cli, ["--help"])
    assert help_result.exit_code == 0
    assert "--help" in help_result.output and "Show this message and exit" in help_result.output


def test_cli_help_content():
    """Test CLI help content is comprehensive."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0

    # Check for comprehensive help content - focus on key functional elements
    assert "Bolster - A comprehensive Python utility library" in result.output
    assert "Northern Ireland" in result.output
    assert "data sources" in result.output
    assert "Commands:" in result.output
    assert "water-quality" in result.output
    assert "--help" in result.output

    # Check for version option (flexible text matching)
    assert "--version" in result.output
    assert "version" in result.output.lower()

    # Check for commands
    assert "Commands:" in result.output
    assert "get-precipitation" in result.output


def test_cli_version():
    """Test CLI version option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "bolster, version" in result.output
    assert "0.3.4" in result.output


def test_precipitation_command_help():
    """Test get-precipitation command help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["get-precipitation", "--help"])
    assert result.exit_code == 0

    # Check comprehensive help content
    assert "Download UK precipitation data from the Met Office" in result.output
    assert "Met Office API key" in result.output
    assert "Environment Variables:" in result.output
    assert "MET_OFFICE_API_KEY" in result.output
    assert "MAP_IMAGES_ORDER_NAME" in result.output
    assert "Examples:" in result.output

    # Check for all options
    assert "--bounding-box" in result.output
    assert "--order-name" in result.output
    assert "--output" in result.output

    # Check option descriptions
    assert "Geographic bounding box" in result.output
    assert "precipitation.png" in result.output


def test_precipitation_command_missing_api_key():
    """Test get-precipitation command handles missing API key gracefully."""
    runner = CliRunner()
    # Run with required parameters but without API key environment variable
    result = runner.invoke(cli, ["get-precipitation", "--order-name", "test"])

    # Should handle gracefully and show helpful error message
    assert result.exit_code == 0
    # Check for error indication in output
    assert "MET_OFFICE_API_KEY environment variable is required" in result.output
    assert "Error:" in result.output


def test_precipitation_command_option_parsing():
    """Test precipitation command parses options correctly."""
    runner = CliRunner()

    # Test with --help to ensure all options are recognized
    result = runner.invoke(cli, ["get-precipitation", "--help"])
    assert result.exit_code == 0

    # Verify all three options are present
    assert "--bounding-box" in result.output
    assert "--order-name" in result.output
    assert "--output" in result.output


def test_precipitation_command_option_descriptions():
    """Test precipitation command option descriptions are comprehensive."""
    runner = CliRunner()
    result = runner.invoke(cli, ["get-precipitation", "--help"])
    assert result.exit_code == 0

    # Check detailed option descriptions
    assert "Geographic bounding box" in result.output
    assert "Met Office API order name" in result.output
    assert "Output filename for the precipitation map image" in result.output
    assert "precipitation.png" in result.output  # Default value shown


def test_invalid_command():
    """Test CLI handles invalid commands gracefully."""
    runner = CliRunner()
    result = runner.invoke(cli, ["nonexistent-command"])

    assert result.exit_code != 0
    assert "No such command" in result.output


def test_cli_structure():
    """Test CLI structure and command organization."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0

    # Verify CLI structure elements
    assert "Usage:" in result.output
    assert "Options:" in result.output
    assert "Commands:" in result.output

    # Verify available commands are listed
    assert "get-precipitation" in result.output
