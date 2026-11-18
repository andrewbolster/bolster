"""Offline tests for LGD employment publication discovery: it raises and never substitutes another release."""

import inspect
from datetime import date
from unittest import mock

import pytest

from bolster.data_sources.nisra import labour_market
from bolster.data_sources.nisra._base import NISRADataNotFoundError

THIS_YEAR = date.today().year
WORKBOOK = "https://www.nisra.gov.uk/system/files/statistics/x/Labour%20Force%20Survey%20-%20LGD%20Tables.xlsx"


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _HTTPError(Exception):
    """Stands in for requests.HTTPError: carries a response with a status code."""

    def __init__(self, status_code: int):
        super().__init__(f"{status_code} Client Error")
        self.response = _Response(status_code)


def _page_url(year: int) -> str:
    return labour_market._LGD_PUBLICATION_URL.format(year=year)


def _scraper(pages: dict[str, object]):
    """Build a scrape_file_links replacement: a page maps to a link list, or an exception to raise."""
    calls: list[str] = []

    def fake(page_url, *args, **kwargs):
        calls.append(page_url)
        outcome = pages[page_url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


class TestLgdEmploymentDiscovery:
    def test_all_pages_missing_raises_naming_every_page_tried(self):
        pages = {_page_url(THIS_YEAR - n): _HTTPError(404) for n in range(labour_market._LGD_LOOKBACK_YEARS)}
        with (
            mock.patch.object(labour_market, "scrape_file_links", side_effect=_scraper(pages)),
            pytest.raises(NISRADataNotFoundError) as exc,
        ):
            labour_market.get_latest_lgd_employment_url()
        message = str(exc.value)
        assert "404" in message
        for url in pages:
            assert url in message

    def test_newest_page_missing_returns_the_next_published_year(self):
        pages = {_page_url(THIS_YEAR): _HTTPError(404), _page_url(THIS_YEAR - 1): [{"url": WORKBOOK, "text": "t"}]}
        scraper = _scraper(pages)
        with mock.patch.object(labour_market, "scrape_file_links", side_effect=scraper):
            url, year = labour_market.get_latest_lgd_employment_url()
        assert (url, year) == (WORKBOOK, THIS_YEAR - 1)
        assert scraper.calls == [_page_url(THIS_YEAR), _page_url(THIS_YEAR - 1)]

    def test_current_year_page_wins_when_published(self):
        scraper = _scraper({_page_url(THIS_YEAR): [{"url": WORKBOOK, "text": "t"}]})
        with mock.patch.object(labour_market, "scrape_file_links", side_effect=scraper):
            assert labour_market.get_latest_lgd_employment_url() == (WORKBOOK, THIS_YEAR)
        assert scraper.calls == [_page_url(THIS_YEAR)]

    def test_server_error_on_newest_page_raises_instead_of_moving_to_an_older_year(self):
        newest = _page_url(THIS_YEAR)
        scraper = _scraper({newest: _HTTPError(503), _page_url(THIS_YEAR - 1): [{"url": WORKBOOK, "text": "t"}]})
        with (
            mock.patch.object(labour_market, "scrape_file_links", side_effect=scraper),
            pytest.raises(NISRADataNotFoundError) as exc,
        ):
            labour_market.get_latest_lgd_employment_url()
        assert newest in str(exc.value)
        assert "503" in str(exc.value)
        assert isinstance(exc.value.__cause__, _HTTPError)
        assert scraper.calls == [newest]

    def test_page_without_a_workbook_raises_instead_of_moving_to_an_older_year(self):
        newest = _page_url(THIS_YEAR)
        scraper = _scraper({newest: [{"url": "https://www.nisra.gov.uk/x/other.xlsx", "text": "t"}]})
        with (
            mock.patch.object(labour_market, "scrape_file_links", side_effect=scraper),
            pytest.raises(NISRADataNotFoundError) as exc,
        ):
            labour_market.get_latest_lgd_employment_url()
        assert newest in str(exc.value)
        assert "no .xlsx workbook" in str(exc.value)
        assert scraper.calls == [newest]

    def test_connection_failure_raises_naming_the_page(self):
        newest = _page_url(THIS_YEAR)
        scraper = _scraper({newest: ConnectionError("timed out")})
        with (
            mock.patch.object(labour_market, "scrape_file_links", side_effect=scraper),
            pytest.raises(NISRADataNotFoundError, match="timed out") as exc,
        ):
            labour_market.get_latest_lgd_employment_url()
        assert newest in str(exc.value)


class TestNoSubstituteFileIsEverRequested:
    def test_employment_by_lgd_does_not_download_when_discovery_fails(self):
        pages = {_page_url(THIS_YEAR - n): _HTTPError(404) for n in range(labour_market._LGD_LOOKBACK_YEARS)}
        with (
            mock.patch.object(labour_market, "scrape_file_links", side_effect=_scraper(pages)),
            mock.patch.object(labour_market, "download_file") as download,
            pytest.raises(NISRADataNotFoundError),
        ):
            labour_market.get_latest_employment_by_lgd()
        download.assert_not_called()

    def test_employment_by_lgd_downloads_only_the_discovered_workbook(self):
        scraper = _scraper({_page_url(THIS_YEAR): [{"url": WORKBOOK, "text": "t"}]})
        with (
            mock.patch.object(labour_market, "scrape_file_links", side_effect=scraper),
            mock.patch.object(labour_market, "download_file", return_value="/tmp/x.xlsx") as download,
            mock.patch.object(labour_market, "parse_employment_by_lgd", return_value="parsed") as parse,
        ):
            assert labour_market.get_latest_employment_by_lgd() == "parsed"
        assert download.call_args.args[0] == WORKBOOK
        assert parse.call_args.kwargs["year"] == THIS_YEAR

    def test_module_holds_no_hard_coded_lgd_workbook(self):
        source = inspect.getsource(labour_market)
        assert "2009%20to%202024" not in source
        assert "known 2024" not in source
