"""Offline tests for emergency care waiting times data-link discovery.

The integrity tests exercise the live site; these pin the link-selection logic
in ``get_latest_url`` against canned HTML, including the host check.
"""

from unittest.mock import MagicMock, patch

import pytest

from bolster.data_sources.health_ni import emergency_care_waiting_times as ecwt
from bolster.data_sources.health_ni._base import NISRADataNotFoundError

LANDING_HTML = b'<a href="https://www.health-ni.gov.uk/publications/emergency-care-waiting-times-2026">pub</a>'
DATA_URL = "https://datavis.nisra.gov.uk/health/emergency-care-data-2026.html"
OTHER_URL = "https://datavis.nisra.gov.uk/health/emergency-care-2026.html"


def _response(html: bytes) -> MagicMock:
    resp = MagicMock()
    resp.content = html
    return resp


def _latest_url_for(publication_hrefs: list[str]) -> str:
    pub_html = "".join(f'<a href="{href}">x</a>' for href in publication_hrefs).encode()
    with patch.object(ecwt, "session") as mock_session:
        mock_session.get.side_effect = [_response(LANDING_HTML), _response(pub_html)]
        return ecwt.get_latest_url()


class TestGetLatestUrl:
    """Link selection on the publication page."""

    def test_prefers_data_page_over_other_datavis_links(self):
        assert _latest_url_for([OTHER_URL, DATA_URL]) == DATA_URL

    def test_falls_back_to_any_non_interactive_datavis_link(self):
        assert _latest_url_for([OTHER_URL]) == OTHER_URL

    def test_fallback_skips_interactive_publication(self):
        interactive = "https://datavis.nisra.gov.uk/health/emergency-care-interactive.html"
        assert _latest_url_for([interactive, OTHER_URL]) == OTHER_URL

    @pytest.mark.parametrize(
        "href",
        [
            "https://evil.example/datavis.nisra.gov.uk/emergency-care-data-2026.html",
            "https://datavis.nisra.gov.uk.evil.example/emergency-care-data-2026.html",
        ],
    )
    def test_rejects_hosts_that_only_mention_datavis(self, href):
        with pytest.raises(NISRADataNotFoundError):
            _latest_url_for([href])
