"""Tests for bolster.utils.web HTTP session, retry configuration and link scraping."""

from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from urllib3.util.retry import RequestHistory

from bolster.utils.web import (
    LinkNotFoundError,
    RateLimitAwareRetry,
    _retry_strategy,
    find_publication_link,
    make_absolute_url,
    scrape_file_links,
    session,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _make_retry_with_history(*statuses):
    """Return a RateLimitAwareRetry with a simulated history of the given HTTP statuses."""
    r = RateLimitAwareRetry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    history = tuple(RequestHistory("GET", "http://example.com", None, s, None) for s in statuses)
    return r.new(history=history)


class TestRetryStatusList:
    def test_retries_on_500(self):
        assert 500 in _retry_strategy.status_forcelist

    def test_retries_on_502(self):
        assert 502 in _retry_strategy.status_forcelist

    def test_retries_on_503(self):
        assert 503 in _retry_strategy.status_forcelist

    def test_retries_on_504(self):
        assert 504 in _retry_strategy.status_forcelist

    def test_retries_on_429(self):
        assert 429 in _retry_strategy.status_forcelist

    def test_total_retries(self):
        assert _retry_strategy.total == 4

    def test_allowed_methods(self):
        assert "GET" in _retry_strategy.allowed_methods
        assert "HEAD" in _retry_strategy.allowed_methods

    def test_respect_retry_after_disabled(self):
        # Prevents a Retry-After: 86400 from hanging CI for hours
        assert _retry_strategy.respect_retry_after_header is False


class TestRateLimitBackoff:
    def test_429_uses_standard_urllib3_backoff(self):
        # 429 now uses the same urllib3 exponential backoff as other errors
        r = _make_retry_with_history(429)
        assert r.get_backoff_time() == 0  # first retry: 0s

    def test_non_429_uses_standard_backoff(self):
        r = _make_retry_with_history(500)
        assert r.get_backoff_time() == 0  # first retry: 0s

    def test_backoff_increases_with_history(self):
        # urllib3 with backoff_factor=1: 0, 2, 4, 8...
        r = _make_retry_with_history(500, 500)
        assert r.get_backoff_time() == 2


class TestSessionConfiguration:
    def test_session_type(self):
        import requests

        assert isinstance(session, requests.Session)

    def test_user_agent_set(self):
        ua = session.headers.get("User-Agent", "")
        assert "Bolster" in ua

    def test_http_adapter_mounted(self):
        adapter = session.get_adapter("http://example.com")
        assert adapter is not None

    def test_https_adapter_mounted(self):
        adapter = session.get_adapter("https://example.com")
        assert adapter is not None


class TestMakeAbsoluteUrl:
    @pytest.mark.parametrize(
        "href,base,expected",
        [
            ("/publications/file.xlsx", "https://www.nisra.gov.uk", "https://www.nisra.gov.uk/publications/file.xlsx"),
            ("publications/file.xlsx", "https://www.nisra.gov.uk", "https://www.nisra.gov.uk/publications/file.xlsx"),
            ("https://example.com/file.xlsx", "https://www.nisra.gov.uk", "https://example.com/file.xlsx"),
            ("http://example.com/file.xlsx", "https://www.nisra.gov.uk", "http://example.com/file.xlsx"),
            ("/data/stats.xlsx", "https://www.health-ni.gov.uk", "https://www.health-ni.gov.uk/data/stats.xlsx"),
        ],
    )
    def test_resolution(self, href, base, expected):
        assert make_absolute_url(href, base) == expected


class TestScrapeFileLinks:
    def test_filters_by_extension_and_resolves_urls(self):
        html = """
        <html><body>
            <a href="/data/report.xlsx">Annual Report 2023</a>
            <a href="https://external.com/data.xlsx">External Data</a>
            <a href="monthly_stats.xlsx">Monthly Stats</a>
            <a href="/data/report.pdf">PDF Report</a>
        </body></html>
        """
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)) as mock_fetch:
            result = scrape_file_links("https://www.nisra.gov.uk/data")

        assert result == [
            {"url": "https://www.nisra.gov.uk/data/report.xlsx", "text": "Annual Report 2023"},
            {"url": "https://external.com/data.xlsx", "text": "External Data"},
            {"url": "https://www.nisra.gov.uk/monthly_stats.xlsx", "text": "Monthly Stats"},
        ]
        mock_fetch.assert_called_once_with("https://www.nisra.gov.uk/data", force_refresh=False)

    def test_non_default_extension(self):
        html = """
        <html><body>
            <a href="/data/report.pdf">PDF Report</a>
            <a href="/data/data.csv">CSV Data</a>
        </body></html>
        """
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)):
            result = scrape_file_links("https://www.nisra.gov.uk/data", file_extension=".pdf")

        assert result == [{"url": "https://www.nisra.gov.uk/data/report.pdf", "text": "PDF Report"}]

    def test_base_url_defaults_to_page_origin(self):
        html = '<html><body><a href="/f.xlsx">F</a></body></html>'
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)):
            result = scrape_file_links("https://www.health-ni.gov.uk/publications/deep/page")

        assert result[0]["url"] == "https://www.health-ni.gov.uk/f.xlsx"

    def test_explicit_base_url_overrides_origin(self):
        html = '<html><body><a href="/f.xlsx">F</a></body></html>'
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)):
            result = scrape_file_links("https://www.nisra.gov.uk/data", base_url="https://cdn.example.com")

        assert result[0]["url"] == "https://cdn.example.com/f.xlsx"

    def test_matches_extension_anywhere_in_href(self):
        # Substring matching subsumes query strings and mixed case
        html = """
        <html><body>
            <a href="/f.XLSX">Upper</a>
            <a href="/f.xlsx?download=1">Query string</a>
            <a href="/notes.txt">Text</a>
        </body></html>
        """
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)):
            result = scrape_file_links("https://www.nisra.gov.uk/data")

        assert [link["text"] for link in result] == ["Upper", "Query string"]

    def test_no_matches_returns_empty_list(self):
        html = '<html><body><a href="/f.pdf">P</a></body></html>'
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)):
            assert scrape_file_links("https://www.nisra.gov.uk/data") == []

    def test_force_refresh_propagates(self):
        html = "<html><body></body></html>"
        with patch("bolster.utils.web.fetch_soup", return_value=_soup(html)) as mock_fetch:
            scrape_file_links("https://www.nisra.gov.uk/data", force_refresh=True)

        mock_fetch.assert_called_once_with("https://www.nisra.gov.uk/data", force_refresh=True)


class TestFindPublicationLink:
    HUB = "https://www.nisra.gov.uk/statistics/hub"

    def _hop(self, hub_html, pub_html):
        """Patch fetch_soup so the hub page is served first, the publication page second."""
        return patch(
            "bolster.utils.web.fetch_soup",
            side_effect=[_soup(hub_html), _soup(pub_html)],
        )

    def test_two_hop_discovery_by_link_text(self):
        hub = """
        <html><body>
            <a href="/publications/other">Some Other Publication</a>
            <a href="/publications/lms-2025">Labour Market Report September 2025</a>
        </body></html>
        """
        pub = '<html><body><a href="/files/lms.xlsx">Tables</a></body></html>'

        with self._hop(hub, pub) as mock_fetch:
            result = find_publication_link(self.HUB, pub_text_contains="Labour Market Report")

        assert result == "https://www.nisra.gov.uk/files/lms.xlsx"
        assert mock_fetch.call_args_list[1].args[0] == "https://www.nisra.gov.uk/publications/lms-2025"

    def test_publication_matched_by_href(self):
        hub = """
        <html><body>
            <a href="/publications/other">Other</a>
            <a href="/publications/HOMELESSNESS-bulletin">Bulletin</a>
        </body></html>
        """
        pub = '<html><body><a href="/files/h.xlsx">Data</a></body></html>'

        with self._hop(hub, pub) as mock_fetch:
            find_publication_link(self.HUB, pub_href_contains="homelessness")

        assert mock_fetch.call_args_list[1].args[0] == "https://www.nisra.gov.uk/publications/HOMELESSNESS-bulletin"

    def test_file_href_contains_filter(self):
        hub = '<html><body><a href="/pub">Pub</a></body></html>'
        pub = """
        <html><body>
            <a href="/files/summary.xlsx">Summary</a>
            <a href="/files/detailed-tables.xlsx">Detailed</a>
        </body></html>
        """
        with self._hop(hub, pub):
            result = find_publication_link(self.HUB, file_href_contains="detailed")

        assert result == "https://www.nisra.gov.uk/files/detailed-tables.xlsx"

    def test_raises_when_no_publication_matches(self):
        hub = '<html><body><a href="/publications/other">Other</a></body></html>'

        with (
            patch("bolster.utils.web.fetch_soup", return_value=_soup(hub)),
            pytest.raises(LinkNotFoundError, match="No publication link found"),
        ):
            find_publication_link(self.HUB, pub_text_contains="Nonexistent")

    def test_raises_when_no_file_matches(self):
        hub = '<html><body><a href="/pub">Pub</a></body></html>'
        pub = '<html><body><a href="/files/notes.pdf">Notes</a></body></html>'

        with self._hop(hub, pub), pytest.raises(LinkNotFoundError, match="No .xlsx file found"):
            find_publication_link(self.HUB)
