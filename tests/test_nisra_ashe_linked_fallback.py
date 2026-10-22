"""Offline tests for the ASHE linked-tables year fallback."""

import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from bolster.data_sources.nisra import ashe
from bolster.data_sources.nisra._base import NISRADataNotFoundError


def _failure(status: int) -> NISRADataNotFoundError:
    """The error download_file raises, chained down to an HTTP response with ``status``."""
    http = requests.HTTPError(response=Mock(status_code=status))
    error = NISRADataNotFoundError(f"Failed to download: {status}")
    error.__cause__ = http
    return error


@pytest.fixture
def downloads():
    """Patch the publication year to 2026 and record which linked files are asked for."""
    asked: list[str] = []

    def make(missing: dict[int, int]):
        def fake(url: str, cache_ttl_hours: int, force_refresh: bool) -> Path:
            asked.append(url)
            for year, status in missing.items():
                if f"ASHE-{year}-linked" in url:
                    raise _failure(status)
            return Path("/tmp/linked.xlsx")

        return fake

    with patch.object(ashe, "get_latest_ashe_publication_url", return_value=("https://x", 2026)):
        yield asked, make


def test_uses_latest_year_when_published(downloads):
    asked, make = downloads
    with patch.object(ashe, "download_file", make({})):
        ashe._get_linked_file()
    assert [u.rsplit("/", 1)[-1] for u in asked] == ["ASHE-2026-linked.xlsx"]


def test_falls_back_to_previous_year_on_404(downloads, caplog):
    asked, make = downloads
    with patch.object(ashe, "download_file", make({2026: 404})), caplog.at_level(logging.WARNING):
        path = ashe._get_linked_file()
    assert path == Path("/tmp/linked.xlsx")
    assert [u.rsplit("/", 1)[-1] for u in asked] == ["ASHE-2026-linked.xlsx", "ASHE-2025-linked.xlsx"]
    assert "2026 linked tables are not published yet; using 2025" in caplog.text


def test_other_failures_are_not_masked_by_older_data(downloads):
    asked, make = downloads
    with patch.object(ashe, "download_file", make({2026: 500})), pytest.raises(NISRADataNotFoundError):
        ashe._get_linked_file()
    assert len(asked) == 1


def test_explicit_year_never_falls_back(downloads):
    asked, make = downloads
    with patch.object(ashe, "download_file", make({2026: 404})), pytest.raises(NISRADataNotFoundError):
        ashe._get_linked_file(2026)
    assert len(asked) == 1


def test_missing_in_both_years_raises(downloads):
    asked, make = downloads
    with patch.object(ashe, "download_file", make({2026: 404, 2025: 404})), pytest.raises(NISRADataNotFoundError):
        ashe._get_linked_file()
    assert len(asked) == 2


def test_reports_the_year_of_the_file_actually_used(downloads):
    asked, make = downloads
    with patch.object(ashe, "download_file", make({2026: 404})):
        _, year = ashe._get_linked_file_and_year()
    assert year == 2025


def test_geography_is_labelled_with_the_year_of_the_file_used(downloads):
    asked, make = downloads
    with (
        patch.object(ashe, "download_file", make({2026: 404})),
        patch.object(ashe, "parse_ashe_geography", return_value="parsed") as parse,
    ):
        assert ashe.get_latest_ashe_geography() == "parsed"
    assert parse.call_args.kwargs["year"] == 2025
