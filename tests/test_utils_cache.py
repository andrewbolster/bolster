"""Tests for bolster.utils.cache module."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import shutil

import pytest
import requests

from bolster.utils.cache import (
    CachedDownloader,
    DownloadError,
    CacheError,
    hash_url,
    CACHE_BASE,
)


class TestHashUrl:
    """Test the hash_url utility function."""

    def test_hash_url_consistent(self):
        """Test that hash_url returns consistent results."""
        url = "https://example.com/data.csv"
        hash1 = hash_url(url)
        hash2 = hash_url(url)

        assert hash1 == hash2
        assert len(hash1) == 32  # MD5 hex digest length
        assert isinstance(hash1, str)

    def test_hash_url_different_for_different_urls(self):
        """Test that different URLs produce different hashes."""
        hash1 = hash_url("https://example.com/data1.csv")
        hash2 = hash_url("https://example.com/data2.csv")

        assert hash1 != hash2

    def test_hash_url_handles_unicode(self):
        """Test that hash_url handles Unicode URLs."""
        url = "https://example.com/café.csv"
        result = hash_url(url)

        assert len(result) == 32
        assert isinstance(result, str)


class TestCacheExceptions:
    """Test cache exception classes."""

    def test_cache_error_inheritance(self):
        """Test that CacheError inherits from Exception."""
        error = CacheError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_download_error_inheritance(self):
        """Test that DownloadError inherits from CacheError."""
        error = DownloadError("download failed")
        assert isinstance(error, CacheError)
        assert isinstance(error, Exception)
        assert str(error) == "download failed"


class TestCachedDownloader:
    """Test CachedDownloader class."""

    def setup_method(self):
        """Set up test fixtures."""
        # Use a temporary directory for testing
        self.test_cache_dir = Path(tempfile.mkdtemp())
        self.original_cache_base = CACHE_BASE

        # Patch CACHE_BASE to use our test directory
        self.cache_patcher = patch('bolster.utils.cache.CACHE_BASE', self.test_cache_dir)
        self.cache_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.cache_patcher.stop()
        if self.test_cache_dir.exists():
            shutil.rmtree(self.test_cache_dir)

    def test_init_creates_cache_directory(self):
        """Test that CachedDownloader creates its cache directory."""
        downloader = CachedDownloader("test_namespace")

        expected_dir = self.test_cache_dir / "test_namespace"
        assert expected_dir.exists()
        assert expected_dir.is_dir()
        assert downloader.cache_dir == expected_dir
        assert downloader.namespace == "test_namespace"
        assert downloader.timeout == 60  # default

    def test_init_with_custom_timeout(self):
        """Test CachedDownloader with custom timeout."""
        downloader = CachedDownloader("test", timeout=30)

        assert downloader.timeout == 30

    def test_get_cached_file_fresh_file_exists(self):
        """Test get_cached_file returns path when fresh file exists."""
        downloader = CachedDownloader("test")
        url = "https://example.com/data.csv"

        # Create a mock cached file
        url_hash = hash_url(url)
        cache_path = downloader.cache_dir / f"{url_hash}.csv"
        cache_path.write_text("test data")

        # Should return the cached file since it's fresh
        result = downloader.get_cached_file(url, cache_ttl_hours=24)
        assert result == cache_path

    def test_get_cached_file_stale_file_ignored(self):
        """Test get_cached_file returns None when file is stale."""
        downloader = CachedDownloader("test")
        url = "https://example.com/data.csv"

        # Create a cached file
        url_hash = hash_url(url)
        cache_path = downloader.cache_dir / f"{url_hash}.csv"
        cache_path.write_text("test data")

        # Set the file's modification time to 2 days ago
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        import os
        os.utime(cache_path, (old_time, old_time))

        # Should return None since file is stale (>24 hours old)
        result = downloader.get_cached_file(url, cache_ttl_hours=24)
        assert result is None

    def test_get_cached_file_no_file_returns_none(self):
        """Test get_cached_file returns None when no cached file exists - covers line 109."""
        downloader = CachedDownloader("test")
        url = "https://example.com/nonexistent.csv"

        # No cached file should exist
        result = downloader.get_cached_file(url, cache_ttl_hours=24)
        assert result is None

    def test_get_cached_file_handles_missing_extension(self):
        """Test get_cached_file works with URLs that have no file extension."""
        downloader = CachedDownloader("test")
        url = "https://example.com/api/data"

        # Create a cached file with .bin extension (default)
        url_hash = hash_url(url)
        cache_path = downloader.cache_dir / f"{url_hash}.bin"
        cache_path.write_text("api response")

        result = downloader.get_cached_file(url, cache_ttl_hours=24)
        assert result == cache_path

    @patch('bolster.utils.cache.web_session')
    def test_download_success_caches_file(self, mock_session):
        """Test successful download creates cached file - covers lines 135-151."""
        # Mock successful response
        mock_response = Mock()
        mock_response.content = b"test file content"
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        downloader = CachedDownloader("test")
        url = "https://example.com/data.csv"

        result = downloader.download(url)

        # Should return path to cached file
        url_hash = hash_url(url)
        expected_path = downloader.cache_dir / f"{url_hash}.csv"
        assert result == expected_path

        # File should exist with correct content
        assert expected_path.exists()
        assert expected_path.read_bytes() == b"test file content"

        # Should have made the HTTP request
        mock_session.get.assert_called_once_with(url, timeout=60)
        mock_response.raise_for_status.assert_called_once()

    @patch('bolster.utils.cache.web_session')
    def test_download_uses_custom_timeout(self, mock_session):
        """Test download uses custom timeout."""
        mock_response = Mock()
        mock_response.content = b"test content"
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        downloader = CachedDownloader("test", timeout=30)
        downloader.download("https://example.com/data.csv")

        mock_session.get.assert_called_once_with("https://example.com/data.csv", timeout=30)

    @patch('bolster.utils.cache.web_session')
    def test_download_network_error_raises_download_error(self, mock_session):
        """Test download raises DownloadError on network failure - covers lines 150-151."""
        mock_session.get.side_effect = requests.exceptions.RequestException("Network error")

        downloader = CachedDownloader("test")

        with pytest.raises(DownloadError, match="Failed to download.*Network error"):
            downloader.download("https://example.com/data.csv")

    @patch('bolster.utils.cache.web_session')
    def test_download_http_error_raises_download_error(self, mock_session):
        """Test download raises DownloadError on HTTP error."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_session.get.return_value = mock_response

        downloader = CachedDownloader("test")

        with pytest.raises(DownloadError, match="Failed to download.*404 Not Found"):
            downloader.download("https://example.com/data.csv")

    @patch('bolster.utils.cache.web_session')
    def test_download_returns_cached_when_available(self, mock_session):
        """Test download returns cached file when available instead of downloading."""
        downloader = CachedDownloader("test")
        url = "https://example.com/data.csv"

        # Create a fresh cached file
        url_hash = hash_url(url)
        cache_path = downloader.cache_dir / f"{url_hash}.csv"
        cache_path.write_text("cached content")

        result = downloader.download(url)

        # Should return cached file without making HTTP request
        assert result == cache_path
        mock_session.get.assert_not_called()

    @patch('bolster.utils.cache.web_session')
    def test_download_force_refresh_bypasses_cache(self, mock_session):
        """Test download with force_refresh=True bypasses cache."""
        # Mock successful response
        mock_response = Mock()
        mock_response.content = b"new content"
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        downloader = CachedDownloader("test")
        url = "https://example.com/data.csv"

        # Create a cached file
        url_hash = hash_url(url)
        cache_path = downloader.cache_dir / f"{url_hash}.csv"
        cache_path.write_text("old content")

        result = downloader.download(url, force_refresh=True)

        # Should download new content despite cache existing
        assert result == cache_path
        assert cache_path.read_bytes() == b"new content"
        mock_session.get.assert_called_once()

    def test_clear_all_files(self):
        """Test clear() removes all cached files - covers lines 162-172."""
        downloader = CachedDownloader("test")

        # Create several test files
        file1 = downloader.cache_dir / "test1.csv"
        file2 = downloader.cache_dir / "test2.xlsx"
        file3 = downloader.cache_dir / "test3.pdf"
        subdir = downloader.cache_dir / "subdir"
        subdir.mkdir()

        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")

        result = downloader.clear()

        # Should delete all files but not directories
        assert result == 3
        assert not file1.exists()
        assert not file2.exists()
        assert not file3.exists()
        assert subdir.exists()  # Directories should remain

    def test_clear_with_pattern(self):
        """Test clear() with glob pattern removes only matching files."""
        downloader = CachedDownloader("test")

        # Create test files with different extensions
        file1 = downloader.cache_dir / "test1.csv"
        file2 = downloader.cache_dir / "test2.xlsx"
        file3 = downloader.cache_dir / "test3.csv"

        file1.write_text("content1")
        file2.write_text("content2")
        file3.write_text("content3")

        result = downloader.clear("*.csv")

        # Should delete only .csv files
        assert result == 2
        assert not file1.exists()
        assert file2.exists()  # xlsx file should remain
        assert not file3.exists()

    def test_clear_empty_directory(self):
        """Test clear() on empty directory."""
        downloader = CachedDownloader("test")

        result = downloader.clear()

        assert result == 0

    def test_clear_no_matching_files(self):
        """Test clear() with pattern that matches no files."""
        downloader = CachedDownloader("test")

        # Create a file that won't match the pattern
        test_file = downloader.cache_dir / "test.csv"
        test_file.write_text("content")

        result = downloader.clear("*.txt")

        # Should delete no files
        assert result == 0
        assert test_file.exists()

    @patch('bolster.utils.cache.logger')
    def test_logging_behavior(self, mock_logger):
        """Test that appropriate log messages are generated."""
        downloader = CachedDownloader("test")

        # Test cache hit logging
        url = "https://example.com/data.csv"
        url_hash = hash_url(url)
        cache_path = downloader.cache_dir / f"{url_hash}.csv"
        cache_path.write_text("cached content")

        downloader.get_cached_file(url)

        # Should log cache hit
        mock_logger.info.assert_called_with(f"Using cached file: {cache_path}")
