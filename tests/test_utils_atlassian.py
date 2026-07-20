"""Tests for bolster.utils.atlassian — validation paths that do not require
a live Confluence server."""

import pytest

from bolster.utils.atlassian import Confluence


class TestConfluenceValidation:
    """Unit tests for validation edge cases — no network calls needed."""

    @pytest.fixture
    def client(self):
        # atlassian-python-api Confluence.__init__ sets up a requests session
        # but does NOT make any network connections — safe to use fake creds.
        return Confluence(url="http://fake.example.com", username="u", password="p")

    def test_append_and_prepend_raises_value_error(self, client):
        """post_html_report raises ValueError before any API call when both
        append and prepend are True."""
        with pytest.raises(ValueError, match="Can't have both append and prepend"):
            client.post_html_report("SPACE", "Page", [{"a": 1}], ["a"], append=True, prepend=True)

    def test_non_list_new_index_raises_type_error(self, client):
        """post_html_report raises TypeError before any API call when new_index
        is not a list."""
        with pytest.raises(TypeError, match="expected a list"):
            client.post_html_report("SPACE", "Page", [{"a": 1}], ["a"], new_index="not-a-list")

    def test_create_page_mismatched_new_index_raises_value_error(self, client):
        """__create_new_table_report_page raises ValueError when new_index length
        does not match data length — no API call made."""
        with pytest.raises(ValueError, match="Invalid new_index definition"):
            client._Confluence__create_new_table_report_page(
                "SPACE", "Page", [{"a": 1}], ["a"], "", "", [1, 2]
            )
