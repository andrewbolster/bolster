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
