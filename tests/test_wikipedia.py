import pandas as pd

from bolster.data_sources.wikipedia import get_ni_executive_basic_table


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
