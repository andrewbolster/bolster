"""Tests for RSS feed parsing utilities."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from bolster.utils.rss import (
    Feed,
    FeedEntry,
    filter_entries,
    get_nisra_statistics_feed,
    parse_date,
    parse_rss_feed,
)


def test_feed_entry_creation():
    """Test FeedEntry dataclass creation."""
    entry = FeedEntry(
        title="Test Entry",
        link="https://example.com/entry1",
        published=datetime(2024, 1, 1, 12, 0, 0),
        summary="Test summary",
        categories=["test", "example"],
    )

    assert entry.title == "Test Entry"
    assert entry.link == "https://example.com/entry1"
    assert entry.published.year == 2024
    assert len(entry.categories) == 2


def test_feed_entry_to_dict():
    """Test FeedEntry to_dict conversion."""
    entry = FeedEntry(
        title="Test Entry",
        link="https://example.com/entry1",
        published=datetime(2024, 1, 1, 12, 0, 0),
    )

    entry_dict = entry.to_dict()

    assert entry_dict["title"] == "Test Entry"
    assert entry_dict["link"] == "https://example.com/entry1"
    assert "2024-01-01" in entry_dict["published"]


def test_feed_creation():
    """Test Feed dataclass creation."""
    entries = [
        FeedEntry(title="Entry 1", link="https://example.com/1"),
        FeedEntry(title="Entry 2", link="https://example.com/2"),
    ]

    feed = Feed(
        title="Test Feed",
        link="https://example.com/feed",
        description="Test description",
        entries=entries,
    )

    assert feed.title == "Test Feed"
    assert len(feed.entries) == 2
    assert feed.entries[0].title == "Entry 1"


def test_parse_date():
    """Test date parsing from various formats."""
    # ISO format
    date1 = parse_date("2024-01-15T10:30:00Z")
    assert date1 is not None
    assert date1.year == 2024
    assert date1.month == 1

    # RFC 2822 format
    date2 = parse_date("Mon, 15 Jan 2024 10:30:00 GMT")
    assert date2 is not None

    # Invalid date
    date3 = parse_date("not a date")
    assert date3 is None

    # None input
    date4 = parse_date(None)
    assert date4 is None


def test_filter_entries_by_title():
    """Test filtering entries by title."""
    entries = [
        FeedEntry(title="Health Statistics 2024", link="https://example.com/1"),
        FeedEntry(title="Crime Report", link="https://example.com/2"),
        FeedEntry(title="Health Survey Results", link="https://example.com/3"),
    ]

    filtered = filter_entries(entries, title_contains="health")

    assert len(filtered) == 2
    assert all("health" in e.title.lower() for e in filtered)


def test_filter_entries_by_date():
    """Test filtering entries by date range."""
    entries = [
        FeedEntry(title="Entry 1", link="https://example.com/1", published=datetime(2024, 1, 1)),
        FeedEntry(title="Entry 2", link="https://example.com/2", published=datetime(2024, 6, 1)),
        FeedEntry(title="Entry 3", link="https://example.com/3", published=datetime(2024, 12, 1)),
    ]

    # After date filter
    filtered_after = filter_entries(entries, after_date="2024-05-01")
    assert len(filtered_after) == 2

    # Before date filter
    filtered_before = filter_entries(entries, before_date="2024-07-01")
    assert len(filtered_before) == 2

    # Date range
    filtered_range = filter_entries(entries, after_date="2024-02-01", before_date="2024-11-01")
    assert len(filtered_range) == 1
    assert filtered_range[0].title == "Entry 2"


def test_filter_entries_by_category():
    """Test filtering entries by category."""
    entries = [
        FeedEntry(title="Entry 1", link="https://example.com/1", categories=["health", "statistics"]),
        FeedEntry(title="Entry 2", link="https://example.com/2", categories=["crime", "statistics"]),
        FeedEntry(title="Entry 3", link="https://example.com/3", categories=["health", "survey"]),
    ]

    filtered = filter_entries(entries, category="health")

    assert len(filtered) == 2
    assert all("health" in e.categories for e in filtered)


@patch("bolster.utils.rss.requests.get")
def test_parse_rss_feed_success(mock_get):
    """Test successful RSS feed parsing."""
    # Mock response with minimal valid RSS
    mock_response = Mock()
    mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>Test Feed</title>
            <link>https://example.com</link>
            <description>Test Description</description>
            <item>
                <title>Test Entry</title>
                <link>https://example.com/entry1</link>
                <description>Test entry description</description>
                <pubDate>Mon, 15 Jan 2024 10:30:00 GMT</pubDate>
            </item>
        </channel>
    </rss>"""
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    feed = parse_rss_feed("https://example.com/feed.xml")

    assert feed.title == "Test Feed"
    assert feed.link == "https://example.com"
    assert len(feed.entries) == 1
    assert feed.entries[0].title == "Test Entry"


@patch("bolster.utils.rss.requests.get")
def test_parse_rss_feed_atom_format(mock_get):
    """Test parsing Atom feeds."""
    # Mock response with minimal valid Atom feed
    mock_response = Mock()
    mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
        <title>Test Atom Feed</title>
        <link href="https://example.com"/>
        <entry>
            <title>Test Atom Entry</title>
            <link href="https://example.com/entry1"/>
            <summary>Test summary</summary>
            <published>2024-01-15T10:30:00Z</published>
        </entry>
    </feed>"""
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    feed = parse_rss_feed("https://example.com/feed.atom")

    assert feed.title == "Test Atom Feed"
    assert len(feed.entries) == 1


@patch("bolster.utils.rss.requests.get")
def test_parse_rss_feed_network_error(mock_get):
    """Test handling of network errors."""
    import requests

    mock_get.side_effect = requests.RequestException("Network error")

    with pytest.raises(requests.RequestException):
        parse_rss_feed("https://example.com/feed.xml")


@patch("bolster.utils.rss.requests.get")
def test_parse_rss_feed_malformed(mock_get):
    """Test handling of malformed feeds."""
    mock_response = Mock()
    mock_response.content = b"This is not valid XML"
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    with pytest.raises(ValueError, match="Failed to parse feed"):
        parse_rss_feed("https://example.com/feed.xml")


@patch("bolster.utils.rss.parse_rss_feed")
def test_get_nisra_statistics_feed(mock_parse):
    """Test NISRA statistics feed retrieval."""
    # Mock the parse_rss_feed function
    mock_feed = Feed(
        title="NISRA Statistics",
        link="https://www.gov.uk",
        entries=[FeedEntry(title="Test NISRA Entry", link="https://www.gov.uk/stats/1")],
    )
    mock_parse.return_value = mock_feed

    feed = get_nisra_statistics_feed(order="recent")

    # Verify the function was called with correct URL
    mock_parse.assert_called_once()
    call_args = mock_parse.call_args[0]
    assert "northern-ireland-statistics-and-research-agency" in call_args[0]
    assert "gov.uk" in call_args[0]

    # Verify feed data
    assert feed.title == "NISRA Statistics"
    assert len(feed.entries) == 1


@patch("bolster.utils.rss.parse_rss_feed")
def test_get_nisra_statistics_feed_oldest_order(mock_parse):
    """Test NISRA statistics feed with oldest-first ordering."""
    mock_feed = Feed(title="NISRA Stats", link="https://www.gov.uk", entries=[])
    mock_parse.return_value = mock_feed

    get_nisra_statistics_feed(order="oldest")

    # Verify URL includes oldest ordering
    call_args = mock_parse.call_args[0]
    assert "order=release-date-oldest" in call_args[0]


def test_feed_entry_empty_categories():
    """Test FeedEntry with no categories initializes empty list."""
    entry = FeedEntry(title="Test", link="https://example.com")

    assert entry.categories == []
    assert isinstance(entry.categories, list)


def test_feed_empty_entries():
    """Test Feed with no entries initializes empty list."""
    feed = Feed(title="Test Feed", link="https://example.com")

    assert feed.entries == []
    assert isinstance(feed.entries, list)
