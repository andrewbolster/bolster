"""Tests for bolster.utils.io module."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from bolster.utils.io import save_xls


class TestSaveXls:
    """Test the save_xls function."""

    def test_save_xls_with_string_path(self):
        """Test saving DataFrames to Excel file using string path."""
        # Create test data
        df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        df2 = pd.DataFrame({"C": [5, 6], "D": [7, 8]})
        dict_df = {"Sheet1": df1, "Sheet2": df2}

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            save_xls(dict_df, tmp.name)
            tmp_path = tmp.name

        try:
            # Verify file was created and can be read
            loaded_data = pd.read_excel(tmp_path, sheet_name=None)

            assert len(loaded_data) == 2
            assert "Sheet1" in loaded_data
            assert "Sheet2" in loaded_data

            # Verify data integrity (Excel includes index as first column, so we ignore it)
            pd.testing.assert_frame_equal(
                loaded_data["Sheet1"].iloc[:, 1:],  # Skip index column
                df1,
                check_index_type=False
            )
            pd.testing.assert_frame_equal(
                loaded_data["Sheet2"].iloc[:, 1:],  # Skip index column
                df2,
                check_index_type=False
            )
        finally:
            # Clean up
            Path(tmp_path).unlink(missing_ok=True)

    def test_save_xls_with_binary_io(self):
        """Test saving DataFrames to Excel file using binary IO object."""
        # Create test data
        df1 = pd.DataFrame({"X": [10, 20], "Y": [30, 40]})
        dict_df = {"TestSheet": df1}

        # Save to temporary file using binary IO
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
            save_xls(dict_df, tmp)

            # Verify file was written by checking size
            tmp.seek(0, 2)  # Seek to end
            file_size = tmp.tell()
            assert file_size > 0  # Should have content

            # Reset and verify we can read it
            tmp.seek(0)
            loaded_data = pd.read_excel(tmp, sheet_name=None)

            assert len(loaded_data) == 1
            assert "TestSheet" in loaded_data

            # Verify data integrity (Excel includes index as first column)
            pd.testing.assert_frame_equal(
                loaded_data["TestSheet"].iloc[:, 1:],  # Skip index column
                df1,
                check_index_type=False
            )

    def test_save_xls_empty_dict(self):
        """Test saving empty dictionary - should handle gracefully."""
        dict_df = {}

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            # Empty dict will cause openpyxl to fail since no sheets exist
            # This test verifies the function doesn't crash unexpectedly
            with pytest.raises(IndexError, match="At least one sheet must be visible"):
                save_xls(dict_df, tmp.name)

            # Clean up - file may or may not exist depending on when the error occurs
            Path(tmp.name).unlink(missing_ok=True)
