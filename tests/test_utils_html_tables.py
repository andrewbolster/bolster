"""Tests for bolster.utils.html_tables module.

These tests assert on the *shape* of generated HTML (tag structure, row/column
counts, cell content) using BeautifulSoup rather than matching literal HTML
strings, so they stay robust to incidental formatting changes (whitespace,
attribute ordering, etc.) while still catching real structural regressions.
"""

import pytest
from bs4 import BeautifulSoup

from bolster.utils.html_tables import (
    iterate_tables,
    make_html_table,
    make_nested_column_html_table_header,
    parse_html_table_data,
    table_walker,
)


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestMakeHtmlTable:
    """Structural tests for make_html_table's generated HTML."""

    def test_wraps_rows_in_tbody(self):
        """Confluence's storage format always wraps rows in <tbody>; generated
        HTML must match so freshly-generated and round-tripped tables parse
        the same way."""
        data = [{"name": "Alice", "score": 92}]
        html = make_html_table(data, keys=["name", "score"])
        soup = parse(html)

        table = soup.find("table")
        assert table is not None
        tbody = table.find("tbody")
        assert tbody is not None

    def test_header_row_present_with_index_column(self):
        data = [{"name": "Alice", "score": 92}]
        html = make_html_table(data, keys=["name", "score"])
        soup = parse(html)

        header_cells = soup.find_all("th")
        # One blank index header + one per key
        assert len(header_cells) == 3
        header_text = [c.get_text() for c in header_cells]
        assert header_text == ["", "name", "score"]

    def test_one_data_row_per_input_record(self):
        data = [
            {"name": "Alice", "score": 92},
            {"name": "Bob", "score": 85},
            {"name": "Charlie", "score": 78},
        ]
        html = make_html_table(data, keys=["name", "score"])
        soup = parse(html)

        rows = soup.find("tbody").find_all("tr")
        # Header row + 3 data rows
        assert len(rows) == 4

    def test_row_cell_count_matches_index_plus_keys(self):
        data = [{"name": "Alice", "score": 92}]
        html = make_html_table(data, keys=["name", "score"])
        soup = parse(html)

        data_row = soup.find("tbody").find_all("tr")[1]
        cells = data_row.find_all("td")
        # Index cell + one per key
        assert len(cells) == 3

    def test_default_indexer_uses_sequential_integers(self):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        html = make_html_table(data, keys=["name"])
        soup = parse(html)

        data_rows = soup.find("tbody").find_all("tr")[1:]
        index_values = [row.find_all("td")[0].get_text() for row in data_rows]
        assert index_values == ["0", "1"]

    def test_custom_indexer_overrides_row_index(self):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        custom_index = ["a", "b"]
        html = make_html_table(data, keys=["name"], indexer=lambda d: zip(custom_index, d))
        soup = parse(html)

        data_rows = soup.find("tbody").find_all("tr")[1:]
        index_values = [row.find_all("td")[0].get_text() for row in data_rows]
        assert index_values == ["a", "b"]

    def test_cell_values_match_input_data(self):
        data = [{"name": "Alice", "score": 92}]
        html = make_html_table(data, keys=["name", "score"])
        soup = parse(html)

        data_row = soup.find("tbody").find_all("tr")[1]
        cells = data_row.find_all("td")
        assert cells[1].get_text() == "Alice"
        assert cells[2].get_text() == "92"

    def test_keys_determine_column_order(self):
        data = [{"b": 2, "a": 1}]
        html = make_html_table(data, keys=["a", "b"])
        soup = parse(html)

        header_cells = soup.find_all("th")
        header_text = [c.get_text() for c in header_cells]
        assert header_text == ["", "a", "b"]

    def test_no_keys_infers_columns_from_data(self):
        data = [{"name": "Alice", "score": 92}]
        html = make_html_table(data)
        soup = parse(html)

        header_cells = soup.find_all("th")
        # blank index header + the 2 inferred columns (order not guaranteed
        # since they come from a set, so just check membership/count)
        assert len(header_cells) == 3
        header_text = {c.get_text() for c in header_cells}
        assert header_text == {"", "name", "score"}

    def test_empty_data_produces_header_only_table(self):
        html = make_html_table([], keys=["name", "score"])
        soup = parse(html)

        rows = soup.find("tbody").find_all("tr")
        assert len(rows) == 1  # header row only

    def test_fractional_values_formatted_as_percentages(self):
        """Default fmt formats 0<v<1 floats as percentages."""
        data = [{"rate": 0.5}]
        html = make_html_table(data, keys=["rate"])
        soup = parse(html)

        cell = soup.find("tbody").find_all("tr")[1].find_all("td")[1]
        assert cell.get_text() == "50.00%"

    def test_integer_values_not_formatted_as_percentages(self):
        data = [{"count": 5}]
        html = make_html_table(data, keys=["count"])
        soup = parse(html)

        cell = soup.find("tbody").find_all("tr")[1].find_all("td")[1]
        assert cell.get_text() == "5"

    def test_custom_fmt_applied_to_all_values(self):
        data = [{"name": "alice"}]
        html = make_html_table(data, keys=["name"], fmt=lambda v: str(v).upper())
        soup = parse(html)

        cell = soup.find("tbody").find_all("tr")[1].find_all("td")[1]
        assert cell.get_text() == "ALICE"


class TestIterateTablesRoundTrip:
    """Round-trip tests: generated HTML must parse back to equivalent records."""

    def test_round_trips_simple_table(self):
        data = [
            {"name": "Alice", "score": 92},
            {"name": "Bob", "score": 85},
        ]
        html = make_html_table(data, keys=["name", "score"])

        parsed = next(iterate_tables(html))
        # Strip the synthetic index key (None) for comparison
        stripped = [{k: v for k, v in row.items() if k is not None} for row in parsed]

        assert stripped == [
            {"name": "Alice", "score": "92"},
            {"name": "Bob", "score": "85"},
        ]

    def test_round_trip_preserves_row_count(self):
        data = [{"name": f"Person{i}"} for i in range(5)]
        html = make_html_table(data, keys=["name"])

        parsed = next(iterate_tables(html))
        assert len(parsed) == 5

    def test_round_trip_preserves_custom_index(self):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        custom_index = ["row-a", "row-b"]
        html = make_html_table(data, keys=["name"], indexer=lambda d: zip(custom_index, d))

        parsed = next(iterate_tables(html))
        index_values = [row[None] for row in parsed]
        assert index_values == ["row-a", "row-b"]

    def test_empty_data_table_yields_single_blank_placeholder_row(self):
        """Known quirk: parse_table_data's fallback (`if not values and headers`)
        synthesizes one blank row of empty strings when a table has headers
        but no data rows, rather than returning an empty list. Documenting
        the actual current behaviour here rather than the arguably more
        intuitive empty-list result."""
        html = make_html_table([], keys=["name"])
        parsed = next(iterate_tables(html))
        assert parsed == [{None: "", "name": ""}]

    def test_no_table_in_body_yields_empty_list(self):
        parsed = next(iterate_tables("<p>no table here</p>"))
        assert parsed == []


class TestMakeNestedColumnHtmlTableHeader:
    """Structural tests for the nested (multi-row, colspan/rowspan) header generator.

    `n` is a nested mapping where leaf values are empty lists; `depth(n)`
    (from bolster.__init__) determines how many header rows are produced —
    a plain ``{"a": [...]}`` is depth 1 (flat), while ``{"a": {"x": []}}``
    is depth 2 (one level of grouping).
    """

    def test_flat_structure_produces_single_header_row(self):
        n = {"name": [], "score": []}
        html = make_nested_column_html_table_header(n, index=True)
        soup = parse(f"<table><tbody>{html}</tbody></table>")

        rows = soup.find_all("tr")
        assert len(rows) == 1

    def test_one_level_nesting_produces_two_header_rows(self):
        n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        html = make_nested_column_html_table_header(n, index=True)
        soup = parse(f"<table><tbody>{html}</tbody></table>")

        rows = soup.find_all("tr")
        assert len(rows) == 2

    def test_two_level_nesting_produces_three_header_rows(self):
        n = {"a": {"b": {"c1": [], "c2": []}}, "d": {"e": []}}
        html = make_nested_column_html_table_header(n, index=True)
        soup = parse(f"<table><tbody>{html}</tbody></table>")

        rows = soup.find_all("tr")
        assert len(rows) == 3

    def test_group_header_colspan_matches_child_count(self):
        n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        html = make_nested_column_html_table_header(n, index=True)
        soup = parse(f"<table><tbody>{html}</tbody></table>")

        top_row = soup.find_all("tr")[0]
        group_a_th = [th for th in top_row.find_all("th") if th.get_text() == "group_a"][0]
        group_b_th = [th for th in top_row.find_all("th") if th.get_text() == "group_b"][0]
        assert group_a_th.get("colspan") == "2"
        assert group_b_th.get("colspan") is None  # single child, no colspan needed

    def test_index_column_rowspans_full_header_height(self):
        n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        html = make_nested_column_html_table_header(n, index=True)
        soup = parse(f"<table><tbody>{html}</tbody></table>")

        index_th = soup.find_all("tr")[0].find_all("th")[0]
        assert index_th.get_text() == ""
        assert index_th.get("rowspan") == "2"

    def test_without_index_omits_blank_corner_cell(self):
        n = {"group_a": {"x": [], "y": []}}
        with_index = make_nested_column_html_table_header(n, index=True)
        without_index = make_nested_column_html_table_header(n, index=False)

        soup_with = parse(f"<table><tbody>{with_index}</tbody></table>")
        soup_without = parse(f"<table><tbody>{without_index}</tbody></table>")

        # with index: blank cell + group_a = 2 cells in top row
        # without index: just group_a = 1 cell in top row
        assert len(soup_with.find_all("tr")[0].find_all("th")) == 2
        assert len(soup_without.find_all("tr")[0].find_all("th")) == 1

    def test_leaf_columns_appear_in_bottom_header_row(self):
        n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        html = make_nested_column_html_table_header(n, index=True)
        soup = parse(f"<table><tbody>{html}</tbody></table>")

        bottom_row = soup.find_all("tr")[-1]
        leaf_text = [th.get_text() for th in bottom_row.find_all("th")]
        assert leaf_text == ["x", "y", "z"]


class TestMakeHtmlTableNested:
    """Tests for make_html_table(nested=True), which uses the nested header
    generator above plus a single flattened data row per record."""

    def test_nested_table_has_correct_header_row_count(self):
        n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        data = [{"group_a": {"x": 1, "y": 2}, "group_b": {"z": 3}}]
        html = make_html_table(data, keys=n, nested=True)
        soup = parse(html)

        # 2 header rows (one-level nesting) + 1 data row
        rows = soup.find("tbody").find_all("tr")
        assert len(rows) == 3

    def test_nested_table_data_row_has_flattened_leaf_values(self):
        n = {"group_a": {"x": [], "y": []}, "group_b": {"z": []}}
        data = [{"group_a": {"x": 1, "y": 2}, "group_b": {"z": 3}}]
        html = make_html_table(data, keys=n, nested=True)
        soup = parse(html)

        data_row = soup.find("tbody").find_all("tr")[-1]
        cell_values = [td.get_text() for td in data_row.find_all("td")]
        # index cell + 3 flattened leaf values
        assert cell_values == ["0", "1", "2", "3"]


class TestParseHtmlTableData:
    """Tests for parse_html_table_data / table_walker — the position-indexed
    (row, col) -> value table parsing path used for reconstructing nested
    table structure (the inverse of make_nested_column_html_table_header).

    Input must use an empty-string key ("") for the index column header,
    matching make_html_table's own convention of [""] + headers.
    """

    def test_flat_table_indexed_by_record(self):
        table_data = {
            0: {0: "", 1: "name", 2: "score"},
            1: {0: 0, 1: "Alice", 2: 92},
            2: {0: 1, 1: "Bob", 2: 85},
        }
        result = parse_html_table_data(table_data, index_by="record")
        assert result == {0: {"name": "Alice", "score": 92}, 1: {"name": "Bob", "score": 85}}

    def test_flat_table_indexed_by_index(self):
        table_data = {
            0: {0: "", 1: "name", 2: "score"},
            1: {0: 0, 1: "Alice", 2: 92},
            2: {0: 1, 1: "Bob", 2: 85},
        }
        result = parse_html_table_data(table_data, index_by="index")
        assert result == {"": [0, 1], "name": ["Alice", "Bob"], "score": [92, 85]}

    def test_invalid_index_by_raises_value_error(self):
        table_data = {0: {0: "", 1: "name"}, 1: {0: 0, 1: "Alice"}}
        with pytest.raises(ValueError, match="Invalid value for `index_by`"):
            parse_html_table_data(table_data, index_by="bogus")

    def test_nested_columns_reconstruct_grouped_structure(self):
        """A 2-row header (group_a spanning cols 1-2, group_b at col 3)
        followed by data rows should reconstruct the original nesting."""
        table_data = {
            0: {0: "", 1: "group_a", 3: "group_b"},
            1: {1: "x", 2: "y", 3: "z"},
            2: {0: 0, 1: 10, 2: 20, 3: 30},
            3: {0: 1, 1: 11, 2: 21, 3: 31},
        }
        result = parse_html_table_data(table_data, index_by="record")
        assert result == {
            0: {"group_a": {"x": 10, "y": 20}, "group_b": 30},
            1: {"group_a": {"x": 11, "y": 21}, "group_b": 31},
        }

    def test_missing_index_column_header_raises_key_error(self):
        """Documents current behaviour: omitting the empty-string index key
        from the header row causes a KeyError rather than a clear validation
        message — table_data must include an explicit "" header column."""
        table_data = {
            0: {0: "name", 1: "score"},
            1: {0: "Alice", 1: 92},
        }
        with pytest.raises(KeyError):
            parse_html_table_data(table_data, index_by="record")

    def test_inconsistent_column_heights_raises_value_error(self):
        """ValueError when a data row omits a column so one leaf ends up shorter."""
        table_data = {
            0: {0: "", 1: "A", 2: "B"},
            1: {0: 0, 1: 10, 2: 20},
            2: {0: 1, 1: 11},  # missing column 2 — B leaf will be shorter
        }
        with pytest.raises(ValueError, match="not the same height"):
            parse_html_table_data(table_data, index_by="record")


class TestTableWalkerDirect:
    """Direct unit tests for table_walker edge cases not reached by round-trip tests."""

    def test_col_min_skips_and_last_col_recurses(self):
        """Line 71 (col_min skip) and line 92 (else-recurse for last col) fire
        when the last column in a header row is NOT the global max key."""
        # Row 0 ends at col 2, but row 1 has a col at index 3 (max_key=3).
        # 'b' is last in row 0 with _w=None and _id=2 != max_key=3 → line 92.
        # The recursive call for 'b' has col_min=1; row 1's col 1 satisfies
        # _id <= col_min (1<=1) → line 71 fires and skips it.
        table_data = {
            0: {0: "", 1: "a", 2: "b"},
            1: {1: "x", 2: "y", 3: "z"},
        }
        result = table_walker(table_data, row_index=0)
        assert result == {"": [], "a": [], "b": {"y": [], "z": []}}

    def test_empty_schema_returned_as_list(self):
        """Line 95 fires when all child-row columns fall outside col_max."""
        # 'grp' spans cols 0-4 (width=5); the recursive call on row 1 has
        # col_max=4, but row 1 only has cols 6 and 7 — both > col_max.
        # The recursive loop body never runs, leaving schema={}, which becomes [].
        table_data = {
            0: {0: "grp", 5: "other"},
            1: {6: "x", 7: "y"},
        }
        result = table_walker(table_data, row_index=0)
        assert result["grp"] == []


class TestIterateTablesBareRows:
    """Tests for <table> elements whose direct children are bare <tr> rows
    (no <tbody> wrapper), exercising the else-branch in parse_table_data."""

    def test_header_only_bare_tr_table_yields_placeholder_row(self):
        """A bare-tr table with only a header row synthesises one empty-string row."""
        html = "<table><tr><th>name</th><th>score</th></tr></table>"
        parsed = next(iterate_tables(html))
        assert parsed == [{"name": "", "score": ""}]
