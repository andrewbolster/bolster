"""Tests for bolster.utils.web HTTP session and retry configuration."""

import pytest
from urllib3.util.retry import RequestHistory

from bolster.utils.web import RateLimitAwareRetry, _retry_strategy, session


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
