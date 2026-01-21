"""Tests for NI House Price Index data module."""

import warnings
from urllib.parse import urlparse

import pandas as pd
import pytest

from bolster.data_sources import ni_house_price_index as hpi

pytestmark = pytest.mark.network  # All tests in this module require network access


class TestSourceDiscovery:
    """Tests for source URL discovery."""

    def test_source_url_valid(self):
        """Source URL should be valid HTTPS from finance-ni.gov.uk."""
        url = hpi.get_source_url()
        assert url is not None
        parsed_url = urlparse(url)
        assert parsed_url.scheme == "https"
        assert parsed_url.netloc == "www.finance-ni.gov.uk"
        assert url.endswith(".xlsx")

    def test_source_url_invalid_base(self):
        """Invalid base URL should raise NIHPIDataNotFoundError."""
        with pytest.raises(hpi.NIHPIDataNotFoundError):
            hpi.get_source_url("https://example.com/invalid")


class TestRawDataPull:
    """Tests for raw data retrieval."""

    def test_pull_sources_sheet_count(self):
        """Pull sources should return 36 sheets."""
        dfs = hpi.pull_sources()
        assert len(dfs) == 36

    def test_pull_sources_expected_sheets(self):
        """Pull sources should contain expected sheet names."""
        dfs = hpi.pull_sources()
        expected_sheets = ["Table 1", "Table 2", "Table 4", "Table 5", "Table 9"]
        for sheet in expected_sheets:
            assert sheet in dfs


class TestTransformedData:
    """Tests for data transformation."""

    def test_get_all_tables_count(self):
        """get_all_tables should return 33 transformed tables."""
        tables = hpi.get_all_tables()
        assert len(tables) == 33

    def test_build_deprecation_warning(self):
        """build() should emit deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            hpi.build()
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "get_all_tables" in str(w[0].message)


class TestHPITrends:
    """Tests for HPI trends data (Table 1)."""

    def test_get_hpi_trends_returns_dataframe(self):
        """get_hpi_trends should return a DataFrame."""
        hpi_df = hpi.get_hpi_trends()
        assert isinstance(hpi_df, pd.DataFrame)

    def test_get_hpi_trends_has_expected_columns(self):
        """HPI trends should have expected columns."""
        hpi_df = hpi.get_hpi_trends()
        expected_cols = ["Period", "Year", "Quarter", "NI House Price Index"]
        for col in expected_cols:
            assert col in hpi_df.columns

    def test_get_hpi_trends_has_quarterly_data(self):
        """HPI trends should have at least 80 quarters of data (2005-2025)."""
        hpi_df = hpi.get_hpi_trends()
        assert len(hpi_df) >= 80

    def test_get_hpi_trends_period_is_period_index(self):
        """Period column should be PeriodIndex."""
        hpi_df = hpi.get_hpi_trends()
        assert hpi_df["Period"].dtype == "period[Q-DEC]"

    def test_get_hpi_trends_starts_2005(self):
        """Data should start from Q1 2005."""
        hpi_df = hpi.get_hpi_trends()
        assert hpi_df.iloc[0]["Year"] == 2005
        assert hpi_df.iloc[0]["Quarter"] == "Q1"


class TestSalesVolumes:
    """Tests for sales volumes data (Table 4)."""

    def test_get_sales_volumes_returns_dataframe(self):
        """get_sales_volumes should return a DataFrame."""
        sales = hpi.get_sales_volumes()
        assert isinstance(sales, pd.DataFrame)

    def test_get_sales_volumes_has_property_types(self):
        """Sales volumes should have property type columns."""
        sales = hpi.get_sales_volumes()
        expected_cols = ["Detached", "Semi-Detached", "Terrace", "Apartment", "Total"]
        for col in expected_cols:
            assert col in sales.columns

    def test_get_sales_volumes_total_is_sum(self):
        """Total should equal sum of property types."""
        sales = hpi.get_sales_volumes()
        # Check a few rows - accounting for potential data issues
        for idx in [0, len(sales) // 2, -1]:
            row = sales.iloc[idx]
            calculated_total = row["Detached"] + row["Semi-Detached"] + row["Terrace"] + row["Apartment"]
            assert row["Total"] == calculated_total


class TestAveragePrices:
    """Tests for average prices data (Table 9)."""

    def test_get_average_prices_returns_dataframe(self):
        """get_average_prices should return a DataFrame."""
        prices = hpi.get_average_prices()
        assert isinstance(prices, pd.DataFrame)

    def test_get_average_prices_has_price_columns(self):
        """Average prices should have price columns."""
        prices = hpi.get_average_prices()
        expected_cols = ["Simple Mean", "Simple Median"]
        for col in expected_cols:
            assert col in prices.columns

    def test_get_average_prices_positive_values(self):
        """All prices should be positive."""
        prices = hpi.get_average_prices()
        assert (prices["Simple Mean"] > 0).all()
        assert (prices["Simple Median"] > 0).all()


class TestHPIByLGD:
    """Tests for HPI by Local Government District (Table 5)."""

    def test_get_hpi_by_lgd_returns_dataframe(self):
        """get_hpi_by_lgd should return a DataFrame."""
        lgd = hpi.get_hpi_by_lgd()
        assert isinstance(lgd, pd.DataFrame)

    def test_get_hpi_by_lgd_has_period_columns(self):
        """LGD data should have period columns."""
        lgd = hpi.get_hpi_by_lgd()
        assert "Period" in lgd.columns
        assert "Year" in lgd.columns
        assert "Quarter" in lgd.columns


class TestHPIByPropertyType:
    """Tests for HPI by property type (Table 2)."""

    def test_get_hpi_by_property_type_returns_dataframe(self):
        """get_hpi_by_property_type should return a DataFrame."""
        by_type = hpi.get_hpi_by_property_type()
        assert isinstance(by_type, pd.DataFrame)

    def test_get_hpi_by_property_type_has_property_types(self):
        """Should have rows for different property types."""
        by_type = hpi.get_hpi_by_property_type()
        # This is a summary table, should have 4-5 rows
        assert len(by_type) >= 4


class TestDataIntegrity:
    """Tests for data quality and integrity."""

    def test_hpi_trends_no_period_gaps(self):
        """HPI trends should have no gaps in quarterly data."""
        hpi_df = hpi.get_hpi_trends()
        periods = hpi_df["Period"].sort_values()

        # Check each consecutive pair
        for i in range(len(periods) - 1):
            current = periods.iloc[i]
            next_period = periods.iloc[i + 1]
            # Next period should be exactly 1 quarter after current
            expected_next = current + 1
            assert next_period == expected_next, f"Gap found: {current} -> {next_period}, expected {expected_next}"

    def test_sales_volumes_no_period_gaps(self):
        """Sales volumes should have no gaps in quarterly data."""
        sales = hpi.get_sales_volumes()
        periods = sales["Period"].sort_values()

        for i in range(len(periods) - 1):
            current = periods.iloc[i]
            next_period = periods.iloc[i + 1]
            expected_next = current + 1
            assert next_period == expected_next, f"Gap found: {current} -> {next_period}"

    def test_average_prices_no_period_gaps(self):
        """Average prices should have no gaps in quarterly data."""
        prices = hpi.get_average_prices()
        periods = prices["Period"].sort_values()

        for i in range(len(periods) - 1):
            current = periods.iloc[i]
            next_period = periods.iloc[i + 1]
            expected_next = current + 1
            assert next_period == expected_next, f"Gap found: {current} -> {next_period}"

    def test_all_time_series_tables_have_consistent_columns(self):
        """All time-series tables should have Period, Year, Quarter columns."""
        tables = hpi.get_all_tables()

        # Tables that should have time series columns
        time_series_tables = [
            "Table 1",
            "Table 4",
            "Table 5",
            "Table 5a",
            "Table 6",
            "Table 7",
            "Table 8",
            "Table 9",
        ]

        for table_name in time_series_tables:
            df = tables.get(table_name)
            assert df is not None, f"{table_name} is missing"
            assert "Period" in df.columns, f"{table_name} missing Period column"
            assert "Year" in df.columns, f"{table_name} missing Year column"
            assert "Quarter" in df.columns, f"{table_name} missing Quarter column"


class TestCaching:
    """Tests for caching functionality."""

    def test_cache_directory_exists(self):
        """Cache directory should be created."""
        assert hpi.CACHE_DIR.exists()
        assert hpi.CACHE_DIR.is_dir()

    def test_clear_cache_runs(self):
        """clear_cache should run without error."""
        hpi.clear_cache()  # Should not raise
