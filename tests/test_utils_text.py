"""Unit tests for bolster.utils.text — no network required."""

from bolster.utils.text import clean_column_name


class TestCleanColumnName:
    def test_simple_combination(self):
        assert clean_column_name("First degree NI") == "first_degree_ni"

    def test_parens_and_digits(self):
        assert clean_column_name("OU(1)") == "ou_1"

    def test_collapses_internal_whitespace_runs(self):
        assert clean_column_name("Postgraduate  Total") == "postgraduate_total"

    def test_strips_leading_and_trailing_punctuation(self):
        assert clean_column_name("  %Total%  ") == "total"

    def test_non_string_input(self):
        assert clean_column_name(2024) == "2024"

    def test_already_clean_input_is_idempotent(self):
        assert clean_column_name("already_clean") == "already_clean"
