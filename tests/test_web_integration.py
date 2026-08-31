#!/usr/bin/env python
"""Integration tests for web utility functions.

These tests exercise real HTTP behavior (a genuine socket round-trip,
real gzip/chunked transfer, a real ZIP archive) against a local
`http.server` fixture rather than third-party services — deterministic
and fast, but without mocking `requests`/`session` itself.
"""

import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd
import pytest

from bolster.utils.web import download_extract_zip, get_excel_dataframe


def _make_xlsx_bytes() -> bytes:
    """Build a minimal real .xlsx file in memory."""
    buf = io.BytesIO()
    pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def _make_zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class _Handler(BaseHTTPRequestHandler):
    """Serves fixed responses for a few known paths; 404s everything else.

    Records the headers of the last /file.xlsx request received, so tests
    can assert that requests_kwargs actually reached the real request
    get_excel_dataframe made — not just that the call didn't raise.
    """

    xlsx_bytes: bytes
    zip_bytes: bytes
    last_xlsx_request_headers: dict[str, str] | None = None

    def do_GET(self):  # noqa: N802
        if self.path == "/file.xlsx":
            _Handler.last_xlsx_request_headers = dict(self.headers)
            body = self.xlsx_bytes
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/archive.zip":
            body = self.zip_bytes
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/ok":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass  # silence request logging in test output


@pytest.fixture(scope="module")
def local_server():
    """A real HTTP server on a local socket for the duration of the module."""
    _Handler.xlsx_bytes = _make_xlsx_bytes()
    _Handler.zip_bytes = _make_zip_bytes({"a.txt": b"hello", "b.txt": b"world"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{server.server_address[0]}:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


class TestGetExcelDataframe:
    def test_reads_real_xlsx_file(self, local_server):
        df = get_excel_dataframe(f"{local_server}/file.xlsx")
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 3

    def test_passes_requests_kwargs_through(self, local_server):
        """requests_kwargs (e.g. custom headers) actually reach the request
        get_excel_dataframe makes — verified against what the server itself
        recorded receiving, not just that the call didn't raise."""
        get_excel_dataframe(
            f"{local_server}/file.xlsx",
            requests_kwargs={"headers": {"X-Test-Header": "present"}},
        )
        assert _Handler.last_xlsx_request_headers.get("X-Test-Header") == "present"

    def test_raises_on_404(self, local_server):
        import requests

        with pytest.raises(requests.HTTPError):
            get_excel_dataframe(f"{local_server}/does-not-exist.xlsx")


class TestDownloadExtractZip:
    def test_extracts_all_files_with_correct_content(self, local_server):
        # Each yielded file object is only valid within its own iteration —
        # the generator closes it before yielding the next one — so read
        # eagerly rather than collecting handles to read afterward.
        results = {name: file_obj.read() for name, file_obj in download_extract_zip(f"{local_server}/archive.zip")}
        assert results == {"a.txt": b"hello", "b.txt": b"world"}

    def test_raises_on_404(self, local_server):
        import requests

        with pytest.raises(requests.HTTPError):
            list(download_extract_zip(f"{local_server}/does-not-exist.zip"))
