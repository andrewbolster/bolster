"""Shared utilities for health-ni.gov.uk data sources.

The Department of Health (DoH) publishes data at https://www.health-ni.gov.uk.
Pages follow a consistent two-step pattern: an article page links to a
publications page, which links to the actual Excel workbook.

This module centralises the base URL constant, shared exceptions, and the
common scraping helpers so individual modules don't duplicate them.
"""

from bolster.data_sources.nisra._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    make_absolute_url,
)
from bolster.utils.web import session

__all__ = [
    "HEALTH_NI_BASE_URL",
    "NISRADataNotFoundError",
    "NISRAValidationError",
    "download_file",
    "make_absolute_url",
    "find_latest_xlsx",
    "search_publications_xlsx",
]

HEALTH_NI_BASE_URL = "https://www.health-ni.gov.uk"


def find_latest_xlsx(article_url: str, keyword: str | None = None) -> str:
    """Return the .xlsx URL found by following an article → publications → file path.

    Fetches *article_url*, finds the first link whose href contains
    ``"/publications/"`` (and optionally *keyword*), fetches that page, then
    returns the first ``.xlsx`` href found there.

    Args:
        article_url: The health-ni article landing page URL.
        keyword: Optional substring that must appear in the publications href
            (e.g. ``"inpatient-and-day-case"``).  If ``None``, the first
            ``/publications/`` link is used.

    Returns:
        Absolute URL of the Excel workbook.

    Raises:
        NISRADataNotFoundError: If either page fetch fails or no xlsx is found.
    """
    from bs4 import BeautifulSoup

    try:
        resp = session.get(article_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {article_url}: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    pub_url: str | None = None
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "/publications/" in href and (keyword is None or keyword in href):
            pub_url = make_absolute_url(href, HEALTH_NI_BASE_URL)
            break

    if pub_url is None:
        detail = f" containing '{keyword}'" if keyword else ""
        raise NISRADataNotFoundError(f"No publications link{detail} found on {article_url}")

    try:
        pub_resp = session.get(pub_url, timeout=30)
        pub_resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {pub_url}: {exc}") from exc

    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx"):
            return make_absolute_url(href, HEALTH_NI_BASE_URL)

    raise NISRADataNotFoundError(f"No .xlsx link found on {pub_url}")


def search_publications_xlsx(keywords: str) -> str:
    """Return the .xlsx URL from the first health-ni publication matching *keywords*.

    Searches ``/publications?keywords=<keywords>``, follows the first result
    link that contains the keywords in its path, then returns the first
    ``.xlsx`` href on that page.

    More robust than :func:`find_latest_xlsx` when the article landing page
    URL is liable to change year-on-year.

    Args:
        keywords: Search terms (URL-encoded automatically), e.g.
            ``"disease prevalence"``.

    Returns:
        Absolute URL of the Excel workbook.

    Raises:
        NISRADataNotFoundError: If no matching publication or xlsx is found.
    """
    from urllib.parse import quote_plus

    from bs4 import BeautifulSoup

    search_url = f"{HEALTH_NI_BASE_URL}/publications?keywords={quote_plus(keywords)}"
    try:
        resp = session.get(search_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {search_url}: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    pub_url: str | None = None
    slug = keywords.replace(" ", "-").lower()
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "/publications/" in href and any(w in href for w in slug.split("-")):
            pub_url = make_absolute_url(href, HEALTH_NI_BASE_URL)
            break

    if pub_url is None:
        raise NISRADataNotFoundError(f"No publication matching '{keywords}' found on {search_url}")

    try:
        pub_resp = session.get(pub_url, timeout=30)
        pub_resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {pub_url}: {exc}") from exc

    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx"):
            return make_absolute_url(href, HEALTH_NI_BASE_URL)

    raise NISRADataNotFoundError(f"No .xlsx link found on {pub_url}")
