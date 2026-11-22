"""Offline tests: pinned fallback releases are served only with ``allow_fallback=True``.

For each module that keeps a pinned release these check, with discovery and
download replaced by fakes:

- default: a failed discovery raises the provider's not-found error carrying the
  standard message, and nothing is downloaded;
- ``allow_fallback=True``: the pinned release is downloaded and the result is
  marked (columns, ``attrs``, :class:`FallbackWarning`);
- healthy discovery: the result is the unmarked frame whatever the flag says.
"""

import inspect
import warnings

import pandas as pd
import pytest

from bolster.data_sources.nisra import homelessness, housing_bulletin, housing_stock, work_quality
from bolster.data_sources.nisra._base import NISRADataNotFoundError
from bolster.data_sources.psni import stop_and_search
from bolster.data_sources.psni._base import PSNIDataNotFoundError
from bolster.utils.fallback import FALLBACK_COLUMNS, FallbackWarning

DISCOVERED = "https://example.org/discovered/latest.file"
BASE = pd.DataFrame({"year": [2025, 2026], "value": [1.0, 2.0]})


class Downloads:
    """Records the URLs a module's ``download_file`` was asked for."""

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url, *args, **kwargs):
        self.urls.append(url)
        return "/tmp/unused-by-the-faked-parser"


@pytest.fixture
def downloads():
    return Downloads()


def _broken(*args, **kwargs):
    raise OSError("connection refused")


def _assert_marked(df, *, served, served_url):
    assert list(df.columns) == [*BASE.columns, *FALLBACK_COLUMNS]
    assert df["fallback_used"].all()
    assert set(df["served_period"]) == {served}
    assert df.attrs["fallback"]["served"] == served
    assert df.attrs["fallback"]["served_url"] == served_url
    assert "connection refused" in df.attrs["fallback"]["reason"]


def _assert_unmarked(df):
    assert list(df.columns) == list(BASE.columns)
    assert "fallback" not in df.attrs
    pd.testing.assert_frame_equal(df, BASE)


def _assert_standard_message(message, *, searched, pinned_label, pinned_url):
    assert message.startswith("Could not find ")
    assert "connection refused" in message
    assert searched in message
    assert pinned_label in message
    assert pinned_url in message
    assert "allow_fallback=True" in message


class TestHousingStock:
    @pytest.fixture(autouse=True)
    def fakes(self, monkeypatch, downloads):
        monkeypatch.setattr(housing_stock, "download_file", downloads)
        monkeypatch.setattr(housing_stock, "parse_lgd_file", lambda path: BASE.copy())
        monkeypatch.setattr(housing_stock, "_first_table_sheet", lambda path: BASE.copy())

    def test_default_raises_and_never_downloads(self, monkeypatch, downloads):
        monkeypatch.setattr(housing_stock, "_scrape_publication_url", _broken)
        with pytest.raises(NISRADataNotFoundError) as excinfo:
            housing_stock.get_latest_housing_stock()
        _assert_standard_message(
            str(excinfo.value),
            searched=housing_stock._SOURCE_PAGE,
            pinned_label="2026 edition",
            pinned_url=housing_stock._FALLBACK_URLS["lgd"],
        )
        assert downloads.urls == []

    @pytest.mark.parametrize("geo", ["lgd", "ward", "soa"])
    def test_opt_in_serves_the_pinned_edition_for_each_geography(self, monkeypatch, downloads, geo):
        monkeypatch.setattr(housing_stock, "_scrape_publication_url", _broken)
        with pytest.warns(FallbackWarning):
            df = housing_stock.get_latest_housing_stock(geo=geo, allow_fallback=True)
        pinned = housing_stock._FALLBACK_URLS[geo]
        assert downloads.urls == [pinned]
        _assert_marked(df, served="2026 edition", served_url=pinned)

    def test_discovered_edition_is_unmarked_whatever_the_flag(self, monkeypatch, downloads):
        monkeypatch.setattr(housing_stock, "_scrape_publication_url", lambda geo: DISCOVERED)
        for flag in (False, True):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                _assert_unmarked(housing_stock.get_latest_housing_stock(allow_fallback=flag))
        assert downloads.urls == [DISCOVERED, DISCOVERED]

    def test_publication_url_helper_follows_the_flag(self, monkeypatch):
        monkeypatch.setattr(housing_stock, "_scrape_publication_url", _broken)
        with pytest.raises(NISRADataNotFoundError):
            housing_stock.get_latest_publication_url("lgd")
        assert (
            housing_stock.get_latest_publication_url("lgd", allow_fallback=True) == housing_stock._FALLBACK_URLS["lgd"]
        )

    def test_unknown_geo_is_a_value_error_not_a_fallback(self):
        with pytest.raises(ValueError, match="Unknown geo type"):
            housing_stock.get_latest_housing_stock(geo="county", allow_fallback=True)


class TestHousingStockDiscovery:
    """The topic page links to the publication page, which holds the workbooks."""

    TOPIC = (
        '<a href="/publications/housing-stock-quality-assurance-administrative-data">QA</a>'
        '<a href="/publications/annual-housing-stock-statistics">Annual Housing stock statistics 2008 - 2026</a>'
    )
    FILES = [
        {
            "url": "https://www.finance-ni.gov.uk/sites/default/files/2025-06/Housing%20Stock%20Tables%202008%20-%202025.xlsx"
        },
        {
            "url": "https://www.finance-ni.gov.uk/sites/default/files/2026-06/Housing%20Stock%20Tables%202008%20-%202026.xlsx"
        },
        {
            "url": "https://www.finance-ni.gov.uk/sites/default/files/2026-06/Housing%20Stock%20LGD%20Ward%20Tables%202008%20-%202026.xlsx"
        },
        {
            "url": "https://www.finance-ni.gov.uk/sites/default/files/2026-06/SOA%20Housing%20Stock%202008%20-%202026.xlsx"
        },
    ]

    @pytest.fixture
    def pages(self, monkeypatch):
        from bs4 import BeautifulSoup

        visited = []
        monkeypatch.setattr(housing_stock, "fetch_soup", lambda url: BeautifulSoup(self.TOPIC, "html.parser"))

        def scrape(page_url, file_extension, base_url=None):
            visited.append(page_url)
            return self.FILES

        monkeypatch.setattr(housing_stock, "scrape_file_links", scrape)
        return visited

    @pytest.mark.parametrize(
        ("geo", "expected"),
        [
            ("lgd", "2026-06/Housing%20Stock%20Tables%202008%20-%202026.xlsx"),
            ("ward", "2026-06/Housing%20Stock%20LGD%20Ward%20Tables%202008%20-%202026.xlsx"),
            ("soa", "2026-06/SOA%20Housing%20Stock%202008%20-%202026.xlsx"),
        ],
    )
    def test_picks_the_newest_workbook_for_the_geography(self, pages, geo, expected):
        url = housing_stock._scrape_publication_url(geo)

        assert url.endswith(expected)
        assert pages == ["https://www.finance-ni.gov.uk/publications/annual-housing-stock-statistics"]

    def test_no_publication_link_is_a_failed_discovery(self, monkeypatch):
        from bs4 import BeautifulSoup

        monkeypatch.setattr(housing_stock, "fetch_soup", lambda url: BeautifulSoup("<a href='/x'>x</a>", "html.parser"))
        with pytest.raises(NISRADataNotFoundError, match="annual-housing-stock-statistics"):
            housing_stock._scrape_publication_url("lgd")
        with pytest.raises(NISRADataNotFoundError, match="allow_fallback=True"):
            housing_stock.get_latest_publication_url("lgd")

    def test_publication_page_without_the_geography_is_a_failed_discovery(self, pages, monkeypatch):
        monkeypatch.setattr(housing_stock, "scrape_file_links", lambda *a, **k: self.FILES[:2])
        with pytest.raises(NISRADataNotFoundError, match="no soa .xlsx link"):
            housing_stock._scrape_publication_url("soa")


class TestHousingBulletin:
    @pytest.fixture(autouse=True)
    def fakes(self, monkeypatch, downloads):
        monkeypatch.setattr(housing_bulletin, "download_file", downloads)
        monkeypatch.setattr(housing_bulletin, "_load_sheet", lambda path, sheet: pd.DataFrame())
        monkeypatch.setattr(housing_bulletin, "_parse_supply_sheet", lambda raw, name: BASE.copy())
        monkeypatch.setattr(housing_bulletin, "find_publication_link", _broken)

    @pytest.mark.parametrize("table", sorted(housing_bulletin._TABLES))
    def test_default_raises_and_never_downloads_for_every_table(self, downloads, table):
        with pytest.raises(NISRADataNotFoundError) as excinfo:
            housing_bulletin.get_latest_data(table=table)
        _assert_standard_message(
            str(excinfo.value),
            searched=housing_bulletin._HUB_URL,
            pinned_label="Jan-Mar 2026 bulletin",
            pinned_url=housing_bulletin._FALLBACK_URL,
        )
        assert downloads.urls == []

    def test_both_extension_failures_are_named_in_the_cause(self):
        with pytest.raises(NISRADataNotFoundError) as excinfo:
            housing_bulletin.get_latest_publication_url()
        assert ".ods: connection refused" in str(excinfo.value)
        assert ".xlsx: connection refused" in str(excinfo.value)

    @pytest.mark.parametrize("entry_point", ["accessor", "dispatcher"])
    def test_opt_in_serves_the_pinned_bulletin(self, downloads, entry_point):
        with pytest.warns(FallbackWarning):
            if entry_point == "accessor":
                df = housing_bulletin.get_social_housing_starts(allow_fallback=True)
            else:
                df = housing_bulletin.get_latest_data("starts", allow_fallback=True)
        assert downloads.urls == [housing_bulletin._FALLBACK_URL]
        _assert_marked(df, served="Jan-Mar 2026 bulletin", served_url=housing_bulletin._FALLBACK_URL)

    def test_xlsx_when_ods_is_missing_is_discovery_not_fallback(self, monkeypatch, downloads):
        xlsx = "https://example.org/bulletin.xlsx"
        links = iter([OSError("no .ods"), xlsx])

        def find(*args, **kwargs):
            link = next(links)
            if isinstance(link, Exception):
                raise link
            return link

        monkeypatch.setattr(housing_bulletin, "find_publication_link", find)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _assert_unmarked(housing_bulletin.get_social_housing_starts())
        assert downloads.urls == [xlsx]

    def test_discovered_bulletin_is_unmarked_whatever_the_flag(self, monkeypatch, downloads):
        monkeypatch.setattr(housing_bulletin, "find_publication_link", lambda *a, **k: DISCOVERED)
        for flag in (False, True):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                _assert_unmarked(housing_bulletin.get_social_housing_starts(allow_fallback=flag))
        assert downloads.urls == [DISCOVERED, DISCOVERED]

    @pytest.mark.parametrize("table", sorted(housing_bulletin._TABLES))
    def test_every_accessor_takes_the_flag_defaulting_to_off(self, table):
        parameter = inspect.signature(housing_bulletin._TABLES[table]).parameters["allow_fallback"]
        assert parameter.default is False


class TestHomelessness:
    @pytest.fixture(autouse=True)
    def fakes(self, monkeypatch, downloads):
        monkeypatch.setattr(homelessness, "download_file", downloads)
        monkeypatch.setattr(
            homelessness, "parse_presentations", lambda path: BASE.rename(columns={"value": "presentations"})
        )
        monkeypatch.setattr(
            homelessness, "parse_acceptances", lambda path: BASE.rename(columns={"value": "acceptances"})
        )

    def test_default_raises_and_never_downloads(self, monkeypatch, downloads):
        monkeypatch.setattr(homelessness, "_scrape_publication_url", _broken)
        with pytest.raises(NISRADataNotFoundError) as excinfo:
            homelessness.get_latest_data()
        _assert_standard_message(
            str(excinfo.value),
            searched=homelessness._HUB_URL,
            pinned_label=homelessness._PINNED_EDITION,
            pinned_url=homelessness._FALLBACK_URL,
        )
        assert downloads.urls == []

    @pytest.mark.parametrize("section", ["presentations", "acceptances", "all"])
    def test_opt_in_marks_every_section(self, monkeypatch, downloads, section):
        monkeypatch.setattr(homelessness, "_scrape_publication_url", _broken)
        with pytest.warns(FallbackWarning):
            df = homelessness.get_latest_data(section=section, allow_fallback=True)
        assert downloads.urls == [homelessness._FALLBACK_URL]
        assert df["fallback_used"].all()
        assert set(df["served_period"]) == {homelessness._PINNED_EDITION}
        assert df.attrs["fallback"]["served_url"] == homelessness._FALLBACK_URL

    def test_discovered_bulletin_is_unmarked_whatever_the_flag(self, monkeypatch, downloads):
        monkeypatch.setattr(homelessness, "_scrape_publication_url", lambda: DISCOVERED)
        for flag in (False, True):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                df = homelessness.get_latest_data(allow_fallback=flag)
            assert list(df.columns) == ["year", "presentations"]
            assert "fallback" not in df.attrs
        assert downloads.urls == [DISCOVERED, DISCOVERED]

    def test_invalid_section_is_a_value_error_not_a_fallback(self):
        with pytest.raises(ValueError, match="section must be one of"):
            homelessness.get_latest_data(section="nope", allow_fallback=True)


class _Response:
    def __init__(self, payload=None, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return self._payload


class TestStopAndSearch:
    @pytest.fixture(autouse=True)
    def fakes(self, monkeypatch, downloads):
        monkeypatch.setattr(stop_and_search, "download_file", downloads)
        monkeypatch.setattr(stop_and_search, "_parse_stop_and_search", lambda path: BASE.copy())

    @pytest.fixture(params=["request-fails", "unsuccessful", "no-csv-resource"])
    def broken_api(self, monkeypatch, request):
        responses = {
            "request-fails": _Response(status_error=OSError("connection refused")),
            "unsuccessful": _Response({"success": False}),
            "no-csv-resource": _Response({"success": True, "result": {"resources": [{"format": "XLSX", "url": "x"}]}}),
        }
        monkeypatch.setattr(stop_and_search.session, "get", lambda *a, **k: responses[request.param])
        return request.param

    def test_default_raises_and_never_downloads(self, broken_api, downloads):
        with pytest.raises(PSNIDataNotFoundError) as excinfo:
            stop_and_search.get_latest_stop_and_search()
        message = str(excinfo.value)
        assert message.startswith("Could not find the latest PSNI stop and search CSV.")
        assert stop_and_search.DATASET_ID in message
        assert stop_and_search.PINNED_RELEASE in message
        assert stop_and_search.FALLBACK_CSV_URL in message
        assert "allow_fallback=True" in message
        assert downloads.urls == []

    def test_opt_in_serves_the_pinned_csv_for_each_failure_mode(self, broken_api, downloads):
        with pytest.warns(FallbackWarning):
            df = stop_and_search.get_latest_stop_and_search(allow_fallback=True)
        assert downloads.urls == [stop_and_search.FALLBACK_CSV_URL]
        assert list(df.columns) == [*BASE.columns, *FALLBACK_COLUMNS]
        assert set(df["served_period"]) == {stop_and_search.PINNED_RELEASE}
        assert df.attrs["fallback"]["served_url"] == stop_and_search.FALLBACK_CSV_URL

    def test_discovered_csv_is_unmarked_whatever_the_flag(self, monkeypatch, downloads):
        payload = {"success": True, "result": {"resources": [{"format": "csv", "url": DISCOVERED}]}}
        monkeypatch.setattr(stop_and_search.session, "get", lambda *a, **k: _Response(payload))
        for flag in (False, True):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                _assert_unmarked(stop_and_search.get_latest_stop_and_search(allow_fallback=flag))
        assert downloads.urls == [DISCOVERED, DISCOVERED]


class _Page:
    def __init__(self, html):
        self.content = html.encode()

    def raise_for_status(self):
        pass


def _pages(workbook_hrefs):
    index = '<a href="/statistics/work-quality/pub-2025">Work Quality in Northern Ireland 2025</a>'
    publication = "".join(f'<a href="{href}">file</a>' for href in workbook_hrefs)
    return {
        work_quality.WORK_QUALITY_INDEX_URL: _Page(index),
        "https://www.nisra.gov.uk/statistics/work-quality/pub-2025": _Page(publication),
    }


class TestWorkQuality:
    LOOSE = "/system/files/2026-04/job-quality-tables.xlsx"
    LOOSE_URL = "https://www.nisra.gov.uk/system/files/2026-04/job-quality-tables.xlsx"
    STRICT_URL = "https://www.nisra.gov.uk/system/files/2026-04/work-quality-2025.xlsx"

    @pytest.fixture(autouse=True)
    def fakes(self, monkeypatch, downloads):
        monkeypatch.setattr(work_quality, "download_file", downloads)
        monkeypatch.setattr(work_quality, "parse_work_quality_file", lambda path, year: BASE.copy())

    def _serve(self, monkeypatch, hrefs):
        pages = _pages(hrefs)
        monkeypatch.setattr(work_quality.session, "get", lambda url, **k: pages[url])

    def test_default_raises_naming_the_unmatched_workbooks_and_never_downloads(self, monkeypatch, downloads):
        self._serve(monkeypatch, [self.LOOSE])
        with pytest.raises(NISRADataNotFoundError) as excinfo:
            work_quality.get_latest_work_quality()
        message = str(excinfo.value)
        assert "Could not find the Work Quality 2025 workbook." in message
        assert "work-quality" in message
        assert self.LOOSE_URL in message
        assert "allow_fallback=True" in message
        assert downloads.urls == []

    def test_opt_in_takes_the_first_workbook_and_marks_the_result(self, monkeypatch, downloads):
        self._serve(monkeypatch, [self.LOOSE])
        with pytest.warns(FallbackWarning):
            df = work_quality.get_latest_work_quality(allow_fallback=True)
        assert downloads.urls == [self.LOOSE_URL]
        assert list(df.columns) == [*BASE.columns, *FALLBACK_COLUMNS]
        assert set(df["served_period"]) == {self.LOOSE_URL}
        assert "work-quality" in df.attrs["fallback"]["reason"]

    @pytest.mark.parametrize("flag", [False, True])
    def test_matching_workbook_is_preferred_and_unmarked(self, monkeypatch, downloads, flag):
        self._serve(monkeypatch, [self.LOOSE, "/system/files/2026-04/work-quality-2025.xlsx"])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _assert_unmarked(work_quality.get_latest_work_quality(allow_fallback=flag))
        assert downloads.urls == [self.STRICT_URL]

    def test_no_workbook_at_all_raises_even_with_the_flag(self, monkeypatch, downloads):
        self._serve(monkeypatch, [])
        with pytest.raises(NISRADataNotFoundError, match="Could not find Excel file"):
            work_quality.get_latest_work_quality(allow_fallback=True)
        assert downloads.urls == []

    def test_publication_url_helper_follows_the_flag(self, monkeypatch):
        self._serve(monkeypatch, [self.LOOSE])
        with pytest.raises(NISRADataNotFoundError):
            work_quality.get_work_quality_publication_url()
        assert work_quality.get_work_quality_publication_url(allow_fallback=True) == (self.LOOSE_URL, 2025)
