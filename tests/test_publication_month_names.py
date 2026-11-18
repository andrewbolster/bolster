"""Offline tests: publication discovery must accept full and abbreviated month names.

NISRA switched a labour market filename from ``July-September`` to ``Jul-Sep``, which broke
discovery until its regex was widened. The same assumption (full lower-case month names in a
publication slug or filename) sat in several other modules; these tests pin the tolerant behaviour
for each of them without touching the network.
"""

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from bolster.data_sources.dfc import child_maintenance, employment_vacancies
from bolster.data_sources.health_ni import _base as health_base
from bolster.data_sources.justice import nicts_quarterly

# (token as it might appear in a slug, month number)
MONTH_SPELLINGS = [
    ("november", 11),
    ("nov", 11),
    ("Nov", 11),
    ("NOVEMBER", 11),
    ("september", 9),
    ("sept", 9),
    ("sep", 9),
    ("march", 3),
    ("mar", 3),
    ("may", 5),
    ("june", 6),
    ("jun", 6),
]


def _soup(*hrefs: str) -> BeautifulSoup:
    return BeautifulSoup("".join(f'<a href="{h}">link</a>' for h in hrefs), "html.parser")


class TestEmploymentVacanciesSlugs:
    @pytest.mark.parametrize(("token", "month"), MONTH_SPELLINGS)
    def test_factsheet_slug_month_spellings(self, monkeypatch, token, month):
        href = f"/publications/vacancies-statistical-factsheet-{token}-2026"
        monkeypatch.setattr(employment_vacancies, "fetch_soup", lambda *a, **k: _soup(href))
        (publication,) = employment_vacancies.list_publications()
        assert publication["month"] == month
        assert publication["year"] == 2026
        assert publication["release"] == f"2026-{month:02d}"

    def test_month_inside_another_word_is_not_a_factsheet(self, monkeypatch):
        href = "/publications/vacancies-statistical-factsheet-mayhem-2026"
        monkeypatch.setattr(employment_vacancies, "fetch_soup", lambda *a, **k: _soup(href))
        with pytest.raises(employment_vacancies.VacanciesDataNotFoundError):
            employment_vacancies.list_publications()


class TestChildMaintenanceSlugs:
    @pytest.mark.parametrize(("token", "month"), MONTH_SPELLINGS)
    def test_slug_month_spellings(self, monkeypatch, token, month):
        href = f"/publications/child-maintenance-service-statistics-data-{token}-2025"
        monkeypatch.setattr(child_maintenance, "fetch_soup", lambda *a, **k: _soup(href))
        (publication,) = child_maintenance.list_publications()
        assert publication["month"] == month
        assert publication["year"] == 2025
        assert publication["quarter"] == (month - 1) // 3 + 1


class TestNictsFilenames:
    @pytest.mark.parametrize(
        ("start", "end", "quarter"),
        [
            ("january", "march", 1),
            ("jan", "mar", 1),
            ("April", "June", 2),
            ("apr", "jun", 2),
            ("july", "september", 3),
            ("jul", "sep", 3),
            ("july", "sept", 3),
            ("october", "december", 4),
            ("OCT", "DEC", 4),
        ],
    )
    def test_filename_period_spellings(self, monkeypatch, start, end, quarter):
        url = f"https://example.test/files/nicts-quarterly-provisional-figures-{start}-to-{end}-2025.ods"
        monkeypatch.setattr(nicts_quarterly, "scrape_file_links", lambda *a, **k: [{"url": url}])
        (publication,) = nicts_quarterly.list_publications()
        assert publication["quarter"] == quarter
        assert publication["year"] == 2025
        assert publication["url"] == url

    def test_non_quarter_month_range_is_not_a_bulletin(self, monkeypatch):
        url = "https://example.test/files/nicts-quarterly-provisional-figures-feb-to-apr-2025.ods"
        monkeypatch.setattr(nicts_quarterly, "scrape_file_links", lambda *a, **k: [{"url": url}])
        with pytest.raises(nicts_quarterly.NICTSDataNotFoundError):
            nicts_quarterly.list_publications()


class _FakeResponse:
    def __init__(self, html: str):
        self.content = html.encode()

    def raise_for_status(self) -> None:
        return None


class TestHealthNiDatedPublications:
    PATTERN = r"active-recruitment-statistics-([a-z]+)-(\d{4})"

    @pytest.mark.parametrize(("token", "month"), [("march", 3), ("mar", 3), ("sept", 9), ("december", 12)])
    def test_month_spellings(self, monkeypatch, token, month):
        html = f'<a href="/publications/active-recruitment-statistics-{token}-2026">title</a>'
        monkeypatch.setattr(health_base.session, "get", lambda *a, **k: _FakeResponse(html))
        frame = health_base.list_dated_publications("https://example.test/series", self.PATTERN)
        assert list(frame["period"]) == [pd.Timestamp(year=2026, month=month, day=1)]

    def test_non_month_slug_is_skipped_not_a_crash(self, monkeypatch):
        html = (
            '<a href="/publications/active-recruitment-statistics-quarter-2026">skip</a>'
            '<a href="/publications/active-recruitment-statistics-mar-2026">keep</a>'
        )
        monkeypatch.setattr(health_base.session, "get", lambda *a, **k: _FakeResponse(html))
        frame = health_base.list_dated_publications("https://example.test/series", self.PATTERN)
        assert list(frame["period"]) == [pd.Timestamp(year=2026, month=3, day=1)]
