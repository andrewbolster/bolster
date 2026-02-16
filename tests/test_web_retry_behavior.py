"""Tests for web.py retry behavior and configuration."""

import time
from unittest.mock import Mock, patch

import pytest
import requests
from requests.adapters import HTTPAdapter
from requests import exceptions as requests_exceptions
from waybackpy import exceptions as wayback_exceptions

from bolster.utils.web import _retry_strategy, session, RateLimitAwareRetry, resilient_get, get_last_valid


class TestRetryConfiguration:
    """Test the retry strategy configuration."""

    def test_retry_configuration(self):
        """Test that retry strategy is configured correctly."""
        assert _retry_strategy.total == 4  # Updated for enhanced rate limit handling
        assert _retry_strategy.backoff_factor == 1
        assert _retry_strategy.status_forcelist == [429, 500, 502, 503, 504]  # Added 429 for rate limiting
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
        # These are the status codes that should trigger retries (including rate limiting)
        expected_status_codes = {429, 500, 502, 503, 504}  # Added 429 for rate limiting
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


class TestRateLimitAwareRetry:
    """Test the custom RateLimitAwareRetry class to cover missing lines."""

    def test_get_backoff_time_normal_error(self):
        """Test normal backoff calculation for non-429 errors."""
        retry = RateLimitAwareRetry(total=3, backoff_factor=1)

        # With no history, should use parent backoff
        backoff_time = retry.get_backoff_time()
        assert backoff_time >= 0  # Should be a valid backoff time

    def test_get_backoff_time_rate_limited(self):
        """Test extended backoff calculation for 429 errors."""
        retry = RateLimitAwareRetry(total=3, backoff_factor=1)

        # Mock a 429 response in history
        mock_response = Mock()
        mock_response.status = 429
        retry.history = [mock_response]

        # Should use extended backoff for 429
        backoff_time = retry.get_backoff_time()
        assert backoff_time >= 30  # Should be at least 30 seconds for rate limiting

    def test_get_backoff_time_empty_history(self):
        """Test backoff with empty history."""
        retry = RateLimitAwareRetry(total=3, backoff_factor=1)
        retry.history = []

        backoff_time = retry.get_backoff_time()
        assert backoff_time >= 0

    def test_increment_with_429_response(self):
        """Test increment method with 429 response to cover logging."""
        retry = RateLimitAwareRetry(total=3, backoff_factor=1)

        # Mock a 429 response
        mock_response = Mock()
        mock_response.status = 429

        # This should trigger the warning log and set _last_status
        with patch('bolster.utils.web.logger.warning') as mock_logger:
            # Call increment - this covers lines 51-53
            new_retry = retry.increment(
                method='GET',
                url='https://example.com/test',
                response=mock_response
            )

            # Should have logged the 429 warning
            mock_logger.assert_called_once()
            assert "429 Too Many Requests" in mock_logger.call_args[0][0]
            assert "rate limiting" in mock_logger.call_args[0][0]

    def test_increment_with_non_429_response(self):
        """Test increment method with normal response."""
        retry = RateLimitAwareRetry(total=3, backoff_factor=1)

        # Mock a normal error response
        mock_response = Mock()
        mock_response.status = 500

        # Should not trigger 429-specific logging
        with patch('bolster.utils.web.logger.warning') as mock_logger:
            new_retry = retry.increment(
                method='GET',
                url='https://example.com/test',
                response=mock_response
            )

            # Should not log 429-specific warnings
            mock_logger.assert_not_called()


class TestResilientGet:
    """Test resilient_get function to cover wayback machine error handling."""

    def test_resilient_get_wayback_fallback_failure(self):
        """Test resilient_get when both direct and wayback requests fail."""
        test_url = "https://example.com/nonexistent"

        # Mock session.get to fail on direct request
        with patch.object(session, 'get') as mock_get:
            mock_get.side_effect = requests_exceptions.HTTPError("Direct request failed")

            # Mock get_last_valid to raise NoCDXRecordFound
            with patch('bolster.utils.web.get_last_valid') as mock_wayback:
                mock_wayback.side_effect = wayback_exceptions.NoCDXRecordFound("No wayback record")

                # Should raise the original HTTP error with wayback error as cause
                with pytest.raises(requests_exceptions.HTTPError, match="Direct request failed"):
                    resilient_get(test_url)

                # Verify wayback was attempted (covers line 95)
                mock_wayback.assert_called_once_with(test_url)

    def test_resilient_get_successful_wayback_fallback(self):
        """Test resilient_get successfully falling back to wayback machine."""
        test_url = "https://example.com/content"
        wayback_url = "https://web.archive.org/web/20230101000000/https://example.com/content"

        # Mock successful response for wayback URL
        mock_wayback_response = Mock()
        mock_wayback_response.raise_for_status.return_value = None

        with patch.object(session, 'get') as mock_get:
            # First call (direct) fails, second call (wayback) succeeds
            mock_get.side_effect = [
                requests_exceptions.HTTPError("Direct failed"),
                mock_wayback_response
            ]

            with patch('bolster.utils.web.get_last_valid') as mock_wayback:
                mock_wayback.return_value = wayback_url

                with patch('bolster.utils.web.logger.warning') as mock_logger:
                    result = resilient_get(test_url)

                    # Should return the wayback response
                    assert result == mock_wayback_response

                    # Should log the fallback warning (covers line 100)
                    mock_logger.assert_called_once()
                    assert "Failed to get" in mock_logger.call_args[0][0]
                    assert "waybackmachine" in mock_logger.call_args[0][0]
                    assert wayback_url in mock_logger.call_args[0][0]


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
