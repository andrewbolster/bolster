import pandas as pd
import pytest
import requests

from bolster.data_sources.wikipedia import get_ni_executive_basic_table
from bolster.exceptions import ParseError
from bolster.utils.web import session


def test_get_ni_executive_basic_table():
    """Test the main function that fetches and processes NI Executive data."""
    # Call the function under test
    result = get_ni_executive_basic_table()

    # Verify the structure of the returned DataFrame
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["Established", "Dissolved", "Duration", "Interregnum"]
    assert list(result.index.names) == ["Executive"]

    # Verify data types
    assert pd.api.types.is_datetime64_any_dtype(result["Established"])
    assert pd.api.types.is_datetime64_any_dtype(result["Dissolved"])
    assert pd.api.types.is_timedelta64_dtype(result["Duration"])
    assert pd.api.types.is_timedelta64_dtype(result["Interregnum"])


def test_get_ni_executive_basic_table_raises_parse_error_on_tableless_page(monkeypatch):
    """A 200 response with no <table> elements (e.g. a Wikipedia interstitial
    or rate-limit page — these don't always surface as a non-2xx status)
    should raise a clear ParseError, not an opaque pandas ImportError/
    FileNotFoundError from deep inside pd.read_html."""
    fake_response = requests.Response()
    fake_response.status_code = 200
    fake_response._content = b"<!DOCTYPE html><html><body>Rate limited</body></html>"

    monkeypatch.setattr(session, "get", lambda *args, **kwargs: fake_response)

    with pytest.raises(ParseError, match="No HTML tables found"):
        get_ni_executive_basic_table()
