"""RSS Feed parsing utilities for bolster.

This module provides utilities for parsing and working with RSS/Atom feeds,
with a focus on government statistics and research publications.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union

import feedparser
import requests
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


@dataclass
class FeedEntry:
    """Represents a single entry from an RSS/Atom feed."""

    title: str
    link: str
    published: Optional[datetime] = None
    updated: Optional[datetime] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    categories: List[str] = None
    content: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self):
        """Initialize empty lists for mutable default arguments."""
        if self.categories is None:
            self.categories = []

    def to_dict(self) -> Dict:
        """Convert entry to dictionary representation."""
        return {
            "title": self.title,
            "link": self.link,
            "published": self.published.isoformat() if self.published else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "summary": self.summary,
            "author": self.author,
            "categories": self.categories,
            "content": self.content,
            "id": self.id,
        }


@dataclass
class Feed:
    """Represents a parsed RSS/Atom feed."""

    title: str
    link: str
    description: Optional[str] = None
    entries: List[FeedEntry] = None
    language: Optional[str] = None
    updated: Optional[datetime] = None

    def __post_init__(self):
        """Initialize empty lists for mutable default arguments."""
        if self.entries is None:
            self.entries = []

    def to_dict(self) -> Dict:
        """Convert feed to dictionary representation."""
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "language": self.language,
            "updated": self.updated.isoformat() if self.updated else None,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string into a datetime object.

    Args:
        date_str: Date string in various formats

    Returns:
        Parsed datetime object or None if parsing fails
    """
    if not date_str:
        return None

    try:
        return date_parser.parse(date_str)
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse date '{date_str}': {e}")
        return None


def parse_feed_entry(entry: feedparser.FeedParserDict) -> FeedEntry:
    """Parse a feedparser entry into a FeedEntry object.

    Args:
        entry: feedparser entry dictionary

    Returns:
        FeedEntry object
    """
    # Extract categories
    categories = []
    if hasattr(entry, "tags"):
        categories = [tag.get("term", "") for tag in entry.tags if tag.get("term")]

    # Extract dates - try updated first since some feeds only have updated
    updated = None
    if hasattr(entry, "updated"):
        updated = parse_date(entry.updated)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            updated = datetime(*entry.updated_parsed[:6])
        except (TypeError, ValueError):
            pass

    published = None
    if hasattr(entry, "published"):
        published = parse_date(entry.published)
    elif hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            published = datetime(*entry.published_parsed[:6])
        except (TypeError, ValueError):
            pass

    # Fall back to updated if published is not available
    if published is None and updated is not None:
        published = updated

    # Extract content
    content = None
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "") if isinstance(entry.content, list) else entry.content

    # Extract summary
    summary = entry.get("summary", None)

    # Extract author
    author = None
    if hasattr(entry, "author"):
        author = entry.author
    elif hasattr(entry, "author_detail") and entry.author_detail:
        author = entry.author_detail.get("name", None)

    return FeedEntry(
        title=entry.get("title", "No title"),
        link=entry.get("link", ""),
        published=published,
        updated=updated,
        summary=summary,
        author=author,
        categories=categories,
        content=content,
        id=entry.get("id", None),
    )


def parse_rss_feed(feed_url: str, timeout: int = 30) -> Feed:
    """Parse an RSS or Atom feed from a URL.

    Args:
        feed_url: URL of the RSS/Atom feed
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Feed object containing parsed feed data

    Raises:
        requests.RequestException: If the feed cannot be fetched
        ValueError: If the feed cannot be parsed

    Example:
        >>> feed = parse_rss_feed("https://example.com/feed.xml")
        >>> print(f"Feed: {feed.title}")
        >>> for entry in feed.entries:
        ...     print(f"  - {entry.title}")
    """
    # Fetch the feed
    try:
        response = requests.get(feed_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch feed from {feed_url}: {e}")
        raise

    # Parse the feed
    parsed = feedparser.parse(response.content)

    if parsed.bozo and not parsed.entries:
        # Feed is malformed and has no entries
        error_msg = f"Failed to parse feed from {feed_url}"
        if hasattr(parsed, "bozo_exception"):
            error_msg += f": {parsed.bozo_exception}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Extract feed metadata
    feed_info = parsed.get("feed", {})

    # Extract feed updated date
    updated = None
    if hasattr(feed_info, "updated"):
        updated = parse_date(feed_info.updated)
    elif hasattr(feed_info, "updated_parsed") and feed_info.updated_parsed:
        try:
            updated = datetime(*feed_info.updated_parsed[:6])
        except (TypeError, ValueError):
            pass

    # Parse entries
    entries = [parse_feed_entry(entry) for entry in parsed.entries]

    return Feed(
        title=feed_info.get("title", "Unknown Feed"),
        link=feed_info.get("link", feed_url),
        description=feed_info.get("description", None),
        language=feed_info.get("language", None),
        updated=updated,
        entries=entries,
    )


def filter_entries(
    entries: List[FeedEntry],
    title_contains: Optional[str] = None,
    category: Optional[str] = None,
    after_date: Optional[Union[datetime, str]] = None,
    before_date: Optional[Union[datetime, str]] = None,
) -> List[FeedEntry]:
    """Filter feed entries based on various criteria.

    Args:
        entries: List of FeedEntry objects to filter
        title_contains: Filter entries whose title contains this string (case-insensitive)
        category: Filter entries that have this category
        after_date: Filter entries published after this date
        before_date: Filter entries published before this date

    Returns:
        Filtered list of FeedEntry objects

    Example:
        >>> feed = parse_rss_feed("https://example.com/feed.xml")
        >>> recent = filter_entries(
        ...     feed.entries,
        ...     title_contains="statistics",
        ...     after_date="2024-01-01"
        ... )
    """
    filtered = entries

    # Filter by title
    if title_contains:
        title_lower = title_contains.lower()
        filtered = [e for e in filtered if title_lower in e.title.lower()]

    # Filter by category
    if category:
        filtered = [e for e in filtered if category in e.categories]

    # Filter by date range
    if after_date:
        if isinstance(after_date, str):
            after_date = parse_date(after_date)
        if after_date:
            filtered = [e for e in filtered if e.published and e.published >= after_date]

    if before_date:
        if isinstance(before_date, str):
            before_date = parse_date(before_date)
        if before_date:
            filtered = [e for e in filtered if e.published and e.published <= before_date]

    return filtered


def get_nisra_statistics_feed(order: str = "recent", timeout: int = 30) -> Feed:
    """Get the NISRA statistics feed from GOV.UK.

    Args:
        order: Sort order - 'recent' for newest first, 'oldest' for oldest first
        timeout: Request timeout in seconds

    Returns:
        Feed object with NISRA statistics

    Example:
        >>> feed = get_nisra_statistics_feed()
        >>> print(f"Found {len(feed.entries)} NISRA publications")
    """
    # Build the URL based on sort order
    if order == "oldest":
        url = (
            "https://www.gov.uk/search/research-and-statistics.atom?"
            "content_store_document_type=all_research_and_statistics&"
            "organisations%5B%5D=northern-ireland-statistics-and-research-agency&"
            "order=release-date-oldest"
        )
    else:
        url = (
            "https://www.gov.uk/search/research-and-statistics.atom?"
            "content_store_document_type=all_research_and_statistics&"
            "organisations%5B%5D=northern-ireland-statistics-and-research-agency"
        )

    return parse_rss_feed(url, timeout=timeout)
