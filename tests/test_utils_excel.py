"""Unit tests for bolster.utils.excel — no network required."""

import pandas as pd

from bolster.utils.excel import find_marker_row


class TestFindMarkerRow:
    def test_finds_first_matching_row(self):
        sheet = pd.DataFrame([["Title"], ["Mode and Year"], ["Full-time"]])
        assert find_marker_row(sheet, lambda v: str(v).strip() == "Mode and Year") == 1

    def test_returns_none_when_no_match(self):
        sheet = pd.DataFrame([["Title"], ["Mode and Year"]])
        assert find_marker_row(sheet, lambda v: str(v).strip() == "Nope") is None

    def test_only_scans_within_max_rows(self):
        rows = [["irrelevant"]] * 5 + [["Target"]]
        sheet = pd.DataFrame(rows)
        assert find_marker_row(sheet, lambda v: v == "Target", max_rows=5) is None
        assert find_marker_row(sheet, lambda v: v == "Target", max_rows=6) == 5

    def test_predicate_receives_raw_cell_including_non_string(self):
        sheet = pd.DataFrame([[float("nan")], [42]])
        assert find_marker_row(sheet, lambda v: v == 42) == 1

    def test_substring_predicate(self):
        sheet = pd.DataFrame([["This worksheet contains one table."], ["Category"]])
        assert find_marker_row(sheet, lambda v: isinstance(v, str) and "worksheet contains" in v.lower()) == 0

    def test_shorter_sheet_than_max_rows_does_not_error(self):
        sheet = pd.DataFrame([["only one row"]])
        assert find_marker_row(sheet, lambda v: v == "nope", max_rows=10) is None
