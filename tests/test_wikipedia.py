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
    assert result["Established"].dtype == "datetime64[ns]"
    assert result["Dissolved"].dtype == "datetime64[ns]"
    assert result["Duration"].dtype == "timedelta64[ns]"
    assert result["Interregnum"].dtype == "timedelta64[ns]"
