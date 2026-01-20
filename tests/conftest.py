"""Pytest configuration and fixtures for bolster tests."""

import ssl
import urllib.request

import pytest

# Check if SSL certificates are properly configured
_SSL_AVAILABLE = None


def _check_ssl_available():
    """Check if SSL certificate verification works."""
    global _SSL_AVAILABLE
    if _SSL_AVAILABLE is None:
        try:
            # Try to connect to a known HTTPS site
            urllib.request.urlopen("https://www.google.com", timeout=5)
            _SSL_AVAILABLE = True
        except (ssl.SSLError, urllib.error.URLError):
            _SSL_AVAILABLE = False
        except Exception:
            # Other errors (network unavailable, etc.) - assume SSL would work
            _SSL_AVAILABLE = True
    return _SSL_AVAILABLE


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "network: marks tests requiring network access")


def pytest_collection_modifyitems(config, items):
    """Skip network tests if SSL certificates are not configured."""
    if _check_ssl_available():
        return

    skip_ssl = pytest.mark.skip(
        reason="SSL certificate verification failed - run 'Install Certificates.command' on macOS"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_ssl)
