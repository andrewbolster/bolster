"""Integrity and validation tests for nisra.drug_related_deaths.

Network tests use real data from NISRA. Validation unit tests run entirely
in-process (no network calls).
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import drug_related_deaths as drd


class TestSummaryIntegrity:
    """Integration tests against the live/cached drug deaths summary table."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return drd.get_latest_data(dimension="summary")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"year", "gender", "measure", "metric", "value"}
        assert required <= set(latest_data.columns), f"Missing columns: {required - set(latest_data.columns)}"

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0

    def test_value_ranges(self, latest_data: pd.DataFrame) -> None:
        """All values are non-negative; annual death counts are within plausible NI bounds."""
        assert (latest_data["value"] >= 0).all()
        deaths = latest_data[latest_data["metric"] == "deaths"]["value"]
        assert deaths.max() < 1000, "Annual drug deaths implausibly high for NI"

    def test_measures_present(self, latest_data: pd.DataFrame) -> None:
        assert {"drug_related", "drug_misuse"} <= set(latest_data["measure"].unique())

    def test_genders_present(self, latest_data: pd.DataFrame) -> None:
        assert {"Persons", "Males", "Females"} <= set(latest_data["gender"].unique())

    def test_historical_coverage(self, latest_data: pd.DataFrame) -> None:
        """Data should cover at least 2014 onward (current 11-year window)."""
        assert latest_data["year"].min() <= 2014
        assert latest_data["year"].nunique() >= 10

    def test_2024_record_high(self, latest_data: pd.DataFrame) -> None:
        """2024 saw a record 251 drug-related deaths (Persons)."""
        row = latest_data[
            (latest_data["year"] == 2024)
            & (latest_data["gender"] == "Persons")
            & (latest_data["measure"] == "drug_related")
            & (latest_data["metric"] == "deaths")
        ]
        assert len(row) == 1
        assert int(row["value"].iloc[0]) == 251

    def test_2024_crude_rate(self, latest_data: pd.DataFrame) -> None:
        """2024 crude rate for drug-related deaths is ~13.0 per 100,000."""
        row = latest_data[
            (latest_data["year"] == 2024)
            & (latest_data["gender"] == "Persons")
            & (latest_data["measure"] == "drug_related")
            & (latest_data["metric"] == "crude_rate")
        ]
        assert len(row) == 1
        assert abs(float(row["value"].iloc[0]) - 13.0) < 0.5

    def test_males_exceed_females(self, latest_data: pd.DataFrame) -> None:
        """Drug-related deaths are consistently higher among males in NI."""
        deaths = latest_data[(latest_data["metric"] == "deaths") & (latest_data["measure"] == "drug_related")]
        males = deaths[deaths["gender"] == "Males"]["value"].sum()
        females = deaths[deaths["gender"] == "Females"]["value"].sum()
        assert males > females

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert drd.validate_data(latest_data) is True


class TestAgeIntegrity:
    """Integration tests against the age-band breakdown."""

    @pytest.fixture(scope="class")
    def age_data(self) -> pd.DataFrame:
        return drd.get_latest_data(dimension="age")

    def test_required_columns(self, age_data: pd.DataFrame) -> None:
        required = {"year", "measure", "gender", "age_band", "deaths"}
        assert required <= set(age_data.columns)

    def test_age_bands_present(self, age_data: pd.DataFrame) -> None:
        bands = set(age_data["age_band"].unique())
        assert {"Under 25", "25-34", "35-44"} <= bands

    def test_no_all_row(self, age_data: pd.DataFrame) -> None:
        """The 'All' summary row is excluded to avoid double-counting."""
        assert "All" not in age_data["age_band"].unique()

    def test_non_negative(self, age_data: pd.DataFrame) -> None:
        assert (age_data["deaths"] >= 0).all()


class TestSubstancesIntegrity:
    """Integration tests against the selected-substances breakdown."""

    @pytest.fixture(scope="class")
    def substance_data(self) -> pd.DataFrame:
        return drd.get_latest_data(dimension="substances")

    def test_required_columns(self, substance_data: pd.DataFrame) -> None:
        required = {"year", "substance", "deaths"}
        assert required <= set(substance_data.columns)

    def test_key_substances_present(self, substance_data: pd.DataFrame) -> None:
        subs = set(substance_data["substance"].unique())
        assert "Heroin/Morphine" in subs
        assert "Cocaine" in subs

    def test_cocaine_rose_in_2024(self, substance_data: pd.DataFrame) -> None:
        """Cocaine mentions hit a record 71 in 2024, up sharply from prior years."""
        row = substance_data[(substance_data["year"] == 2024) & (substance_data["substance"] == "Cocaine")]
        assert len(row) == 1
        assert int(row["deaths"].iloc[0]) == 71


class TestParseAll:
    """The 'all' dimension returns a dict of all three tables."""

    @pytest.fixture(scope="class")
    def all_data(self) -> dict:
        return drd.get_latest_data(dimension="all")

    def test_keys(self, all_data: dict) -> None:
        assert sorted(all_data.keys()) == ["age", "substances", "summary"]

    def test_all_non_empty(self, all_data: dict) -> None:
        assert all(len(df) > 0 for df in all_data.values())


class TestPublicationDiscovery:
    """Verify the live publication URL discovery."""

    def test_returns_xlsx_url(self) -> None:
        url = drd.get_latest_publication_url()
        assert url.endswith(".xlsx")
        assert "nisra.gov.uk" in url


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def _good_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "year": list(range(2014, 2025)),
                "gender": ["Persons"] * 11,
                "measure": ["drug_related"] * 11,
                "metric": ["deaths"] * 11,
                "value": list(range(110, 121)),
            }
        )

    def test_validate_empty_dataframe(self) -> None:
        assert drd.validate_data(pd.DataFrame()) is False

    def test_validate_none(self) -> None:
        assert drd.validate_data(None) is False

    def test_validate_missing_columns(self) -> None:
        df = pd.DataFrame({"year": [2014], "value": [110]})
        assert drd.validate_data(df) is False

    def test_validate_negative_values(self) -> None:
        df = self._good_df()
        df.loc[0, "value"] = -5
        assert drd.validate_data(df) is False

    def test_validate_too_few_records(self) -> None:
        df = self._good_df().head(3)
        assert drd.validate_data(df) is False

    def test_validate_good_data(self) -> None:
        assert drd.validate_data(self._good_df()) is True


class TestParseErrors:
    """parse_data raises on invalid dimension."""

    def test_invalid_dimension(self) -> None:
        with pytest.raises(ValueError):
            drd.parse_data("ignored.xlsx", dimension="bogus")
