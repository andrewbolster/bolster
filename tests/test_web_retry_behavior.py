"""Tests for web.py retry behavior and configuration."""

import time

import pytest
import requests
from requests.adapters import HTTPAdapter

from bolster.utils.web import _retry_strategy, session


class TestRetryConfiguration:
    """Test the retry strategy configuration."""

    def test_retry_configuration(self):
        """Test that retry strategy is configured correctly."""
        assert _retry_strategy.total == 3
        assert _retry_strategy.backoff_factor == 1
        assert _retry_strategy.status_forcelist == [500, 502, 503, 504]
        assert _retry_strategy.allowed_methods == ["HEAD", "GET", "OPTIONS"]
        assert _retry_strategy.raise_on_status is True  # Critical fix

    def test_session_adapter_mounted(self):
        """Test that session has retry adapter mounted."""
        http_adapter = session.get_adapter("http://example.com")
        https_adapter = session.get_adapter("https://example.com")

        assert isinstance(http_adapter, HTTPAdapter)
        assert isinstance(https_adapter, HTTPAdapter)

        # Verify the adapter has our retry strategy
        assert http_adapter.max_retries is _retry_strategy
        assert https_adapter.max_retries is _retry_strategy


class TestRetryBehavior:
    """Test actual retry behavior with simplified tests."""

    def test_retry_configuration_is_correct(self):
        """Test that the critical fix is applied - raise_on_status=True."""
        # This is the core fix that enables proper exponential backoff for 503 errors
        # instead of immediate failures that cause tests to run for 56+ minutes
        assert _retry_strategy.raise_on_status is True
        assert _retry_strategy.respect_retry_after_header is True

    def test_session_uses_retry_adapter(self):
        """Test that session is configured with retry adapter."""
        # Get the adapter for HTTP and HTTPS
        http_adapter = session.get_adapter("http://example.com")
        https_adapter = session.get_adapter("https://example.com")

        # Both should be HTTPAdapter instances with our retry strategy
        assert isinstance(http_adapter, HTTPAdapter)
        assert isinstance(https_adapter, HTTPAdapter)
        assert http_adapter.max_retries == _retry_strategy
        assert https_adapter.max_retries == _retry_strategy

    @pytest.mark.skipif(True, reason="Integration test - requires network connectivity")
    def test_successful_request_no_retries(self):
        """Test that successful requests don't trigger retries."""
        # This would be an integration test with a real successful endpoint
        # Skip by default to avoid network dependencies
        pass

    @pytest.mark.skipif(True, reason="Integration test - requires controlled failure endpoint")
    def test_503_error_handling(self):
        """Test that 503 errors trigger retries and eventually raise."""
        # This would require a controlled test endpoint that returns 503
        # Skip by default to avoid network dependencies
        pass


class TestNetworkResilience:
    """Configuration and resilience tests."""

    def test_session_has_user_agent(self):
        """Test that session has proper user agent set."""
        assert "User-Agent" in session.headers
        assert "@Bolster/" in session.headers["User-Agent"]
        assert "bolster.online" in session.headers["User-Agent"]

    def test_status_forcelist_contains_server_errors(self):
        """Test that retry strategy targets appropriate server errors."""
        # These are the status codes that should trigger retries
        expected_status_codes = {500, 502, 503, 504}
        actual_status_codes = set(_retry_strategy.status_forcelist)
        assert actual_status_codes == expected_status_codes

    def test_allowed_methods_are_safe(self):
        """Test that only safe HTTP methods are allowed for retries."""
        safe_methods = {"HEAD", "GET", "OPTIONS"}
        actual_methods = set(_retry_strategy.allowed_methods)
        assert actual_methods == safe_methods

    def test_retry_strategy_immutable(self):
        """Test that retry strategy object is not accidentally modified."""
        original_total = _retry_strategy.total
        original_backoff = _retry_strategy.backoff_factor
        original_status_list = _retry_strategy.status_forcelist.copy()
        original_methods = _retry_strategy.allowed_methods.copy()
        original_raise_on_status = _retry_strategy.raise_on_status

        # Simulate some usage
        session.get_adapter("http://example.com")

        # Verify configuration unchanged
        assert _retry_strategy.total == original_total
        assert _retry_strategy.backoff_factor == original_backoff
        assert _retry_strategy.status_forcelist == original_status_list
        assert _retry_strategy.allowed_methods == original_methods
        assert _retry_strategy.raise_on_status == original_raise_on_status


@pytest.mark.integration
class TestRealNetworkBehavior:
    """Optional integration tests with real network calls.

    These tests are marked with @pytest.mark.integration and won't run
    by default. Run with: pytest -m integration
    """

    @pytest.mark.skipif(True, reason="Requires network connectivity and external service")
    def test_real_timeout_behavior(self):
        """Test real timeout behavior with a slow endpoint."""
        # This test is intentionally marked as integration only
        # httpbin.org/delay/10 takes 10 seconds to respond
        start_time = time.time()

        with pytest.raises((requests.Timeout, requests.ConnectionError)):
            session.get("https://httpbin.org/delay/10", timeout=2)

        elapsed = time.time() - start_time
        # Should timeout in ~2 seconds, not hang forever
        assert elapsed < 5, f"Expected quick timeout, took {elapsed:.2f}s"
