"""Unit tests for bolster.utils.datatables.

These tests use mocked HTTP responses and in-memory HTML — no real network calls.
"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from bolster.utils.datatables import (
    DataTablesError,
    _extract_datatables_payload,
    _parse_column_headers,
    datatables_to_dataframe,
    fetch_datatables_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dt_html(col_arrays: list, headers: list[str] | None = None) -> str:
    """Build a minimal HTML page containing a DT widget JSON block."""
    if headers is None:
        headers = [f"Col{i}" for i in range(len(col_arrays))]

    th_cells = "".join(f"<th>{h}</th>" for h in headers)
    container = f"<table><thead><tr>{th_cells}</tr></thead></table>"

    payload = {
        "x": {
            "data": col_arrays,
            "container": container,
            "evals": [],
            "jsHooks": [],
        }
    }

    script_content = json.dumps(payload)
    return (
        "<!DOCTYPE html><html><body>"
        f'<script type="application/json">{script_content}</script>'
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# _parse_column_headers
# ---------------------------------------------------------------------------


class TestParseColumnHeaders:
    def test_extracts_headers(self):
        html = "<table><thead><tr><th>Name</th><th>Value</th><th>Date</th></tr></thead></table>"
        assert _parse_column_headers(html) == ["Name", "Value", "Date"]

    def test_empty_html(self):
        assert _parse_column_headers("") == []

    def test_strips_whitespace(self):
        html = "<table><thead><tr><th>  First  </th><th>Last</th></tr></thead></table>"
        assert _parse_column_headers(html) == ["First", "Last"]


# ---------------------------------------------------------------------------
# _extract_datatables_payload
# ---------------------------------------------------------------------------


class TestExtractDataTablesPayload:
    def test_extracts_correct_payload(self):
        col_arrays = [["a", "b", "c"], [1, 2, 3]]
        html = _make_dt_html(col_arrays, headers=["Name", "Value"])
        payload = _extract_datatables_payload(html)
        assert payload["data"] == col_arrays

    def test_picks_largest_when_multiple_scripts(self):
        """Should return the payload from the largest matching script block."""
        small_payload = {
            "x": {"data": [["x"], [1]], "container": "<table><thead><tr><th>A</th><th>B</th></tr></thead></table>"}
        }
        big_col_arrays = [list(range(100)), list(range(100, 200))]
        big_payload = {
            "x": {
                "data": big_col_arrays,
                "container": "<table><thead><tr><th>A</th><th>B</th></tr></thead></table>",
            }
        }
        html = (
            "<!DOCTYPE html><html><body>"
            f'<script type="application/json">{json.dumps(small_payload)}</script>'
            f'<script type="application/json">{json.dumps(big_payload)}</script>'
            "</body></html>"
        )
        payload = _extract_datatables_payload(html)
        assert payload["data"] == big_col_arrays

    def test_raises_when_no_json_scripts(self):
        html = "<html><body><p>No scripts here</p></body></html>"
        with pytest.raises(DataTablesError, match="No application/json script blocks"):
            _extract_datatables_payload(html)

    def test_raises_when_no_column_array(self):
        """A JSON script without column-transposed data must raise."""
        payload = {"x": {"data": "not-a-list", "container": ""}}
        html = (
            "<!DOCTYPE html><html><body>"
            f'<script type="application/json">{json.dumps(payload)}</script>'
            "</body></html>"
        )
        with pytest.raises(DataTablesError, match="No DataTables column-transposed payload"):
            _extract_datatables_payload(html)

    def test_raises_when_data_is_row_oriented(self):
        """Row-oriented data (list of dicts) must not be treated as DT widget."""
        payload = {"x": {"data": [{"col": 1}, {"col": 2}], "container": ""}}
        html = (
            "<!DOCTYPE html><html><body>"
            f'<script type="application/json">{json.dumps(payload)}</script>'
            "</body></html>"
        )
        with pytest.raises(DataTablesError, match="No DataTables column-transposed payload"):
            _extract_datatables_payload(html)

    def test_skips_malformed_json(self):
        """Malformed JSON in one script should not prevent finding valid data in another."""
        col_arrays = [["a", "b"], [1, 2]]
        good_payload = {
            "x": {
                "data": col_arrays,
                "container": "<table><thead><tr><th>Name</th><th>Value</th></tr></thead></table>",
            }
        }
        html = (
            "<!DOCTYPE html><html><body>"
            '<script type="application/json">not valid json }{</script>'
            f'<script type="application/json">{json.dumps(good_payload)}</script>'
            "</body></html>"
        )
        payload = _extract_datatables_payload(html)
        assert payload["data"] == col_arrays


# ---------------------------------------------------------------------------
# datatables_to_dataframe
# ---------------------------------------------------------------------------


class TestDatatablesToDataframe:
    def test_basic_conversion(self):
        payload = {
            "data": [["Alice", "Bob"], [30, 25]],
            "container": "<table><thead><tr><th>Name</th><th>Age</th></tr></thead></table>",
        }
        df = datatables_to_dataframe(payload)
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["Name", "Age"]
        assert len(df) == 2
        assert df["Name"].tolist() == ["Alice", "Bob"]
        assert df["Age"].tolist() == [30, 25]

    def test_falls_back_to_positional_columns_on_count_mismatch(self):
        """When header count != column count, fall back to col_0, col_1, …"""
        payload = {
            "data": [["a", "b"], [1, 2], [True, False]],
            "container": "<table><thead><tr><th>OnlyOne</th></tr></thead></table>",
        }
        df = datatables_to_dataframe(payload)
        assert list(df.columns) == ["col_0", "col_1", "col_2"]

    def test_uses_positional_names_when_no_container(self):
        payload = {"data": [["a", "b", "c"], [1, 2, 3]]}
        df = datatables_to_dataframe(payload)
        assert list(df.columns) == ["col_0", "col_1"]

    def test_raises_on_missing_data_key(self):
        with pytest.raises(DataTablesError, match="missing or empty"):
            datatables_to_dataframe({})

    def test_raises_on_empty_data(self):
        with pytest.raises(DataTablesError, match="missing or empty"):
            datatables_to_dataframe({"data": []})

    def test_raises_on_non_list_column_arrays(self):
        with pytest.raises(DataTablesError, match="list of column arrays"):
            datatables_to_dataframe({"data": ["not", "lists"]})

    def test_raises_on_unequal_column_lengths(self):
        with pytest.raises(DataTablesError, match="Column 1 has"):
            datatables_to_dataframe({"data": [["a", "b", "c"], [1, 2]]})

    def test_column_transposed_to_rows(self):
        """Verify the transposition is correct: data[col][row] → df[row][col]."""
        col0 = ["x", "y", "z"]
        col1 = [10, 20, 30]
        col2 = [True, False, True]
        payload = {
            "data": [col0, col1, col2],
            "container": "<table><thead><tr><th>A</th><th>B</th><th>C</th></tr></thead></table>",
        }
        df = datatables_to_dataframe(payload)
        assert df.loc[0, "A"] == "x"
        assert df.loc[1, "B"] == 20
        assert df.loc[2, "C"] is True or df.loc[2, "C"] == True  # noqa: E712

    def test_large_payload(self):
        """Handles larger payloads without issues."""
        n_rows = 1000
        payload = {
            "data": [list(range(n_rows)), list(range(n_rows, 2 * n_rows))],
            "container": "<table><thead><tr><th>X</th><th>Y</th></tr></thead></table>",
        }
        df = datatables_to_dataframe(payload)
        assert len(df) == n_rows
        assert df["X"].iloc[-1] == n_rows - 1


# ---------------------------------------------------------------------------
# fetch_datatables_json
# ---------------------------------------------------------------------------


class TestFetchDatatablesJson:
    def test_fetches_and_extracts_payload(self):
        """fetch_datatables_json should call the session and extract the payload."""
        col_arrays = [["val1", "val2"], [10, 20]]
        html = _make_dt_html(col_arrays, headers=["Col A", "Col B"])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("bolster.utils.datatables.session") as mock_session:
            mock_session.get.return_value = mock_response
            payload = fetch_datatables_json("https://example.com/data.html")

        assert payload["data"] == col_arrays
        mock_session.get.assert_called_once_with("https://example.com/data.html", timeout=30)

    def test_raises_datatables_error_on_http_failure(self):
        """HTTP errors must be wrapped in DataTablesError."""
        with patch("bolster.utils.datatables.session") as mock_session:
            mock_session.get.side_effect = ConnectionError("network unreachable")
            with pytest.raises(DataTablesError, match="Failed to fetch page"):
                fetch_datatables_json("https://example.com/data.html")

    def test_raises_datatables_error_on_missing_payload(self):
        """Pages without a DT payload must raise DataTablesError."""
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>No data here</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("bolster.utils.datatables.session") as mock_session:
            mock_session.get.return_value = mock_response
            with pytest.raises(DataTablesError):
                fetch_datatables_json("https://example.com/data.html")

    def test_uses_custom_timeout(self):
        """Custom timeout must be forwarded to the HTTP session."""
        col_arrays = [["a"], [1]]
        html = _make_dt_html(col_arrays)

        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("bolster.utils.datatables.session") as mock_session:
            mock_session.get.return_value = mock_response
            fetch_datatables_json("https://example.com/data.html", timeout=60)

        mock_session.get.assert_called_once_with("https://example.com/data.html", timeout=60)
