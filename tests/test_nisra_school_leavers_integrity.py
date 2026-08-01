"""Data integrity tests for the NISRA School Leavers Survey module."""

import pandas as pd
import pytest

from bolster.data_sources.nisra import school_leavers


def _good_df() -> pd.DataFrame:
    """Minimal frame that passes validation, for mutating in unit tests."""
    return pd.DataFrame(
        {
            "academic_year": [f"20{y:02d}/{y + 1:02d}" for y in range(10, 20)],
            "year_ending": range(2011, 2021),
            "category": ["At least 5 GCSEs"] * 10,
            "count": [1000.0] * 10,
            "percentage": [55.5] * 10,
        }
    )


class TestAttainmentIntegrity:
    @pytest.fixture(scope="class")
    def data(self):
        return school_leavers.get_latest_school_leavers("attainment", "settlement")

    def test_required_columns(self, data):
        expected = {
            "academic_year",
            "year_ending",
            "geography_code",
            "geography",
            "category",
            "fsm_entitlement",
            "count",
            "percentage",
        }
        assert expected == set(data.columns)

    def test_settlement_geographies(self, data):
        assert set(data["geography"]) == {"Northern Ireland", "Urban", "Rural"}

    def test_fsme_breakdown(self, data):
        assert set(data["fsm_entitlement"]) == {"all", "entitled", "not_entitled"}

    def test_value_ranges(self, data):
        assert (data["count"].dropna() >= 0).all()
        percentages = data["percentage"].dropna()
        assert percentages.between(0, 100).all()

    def test_historical_coverage(self, data):
        assert data["academic_year"].nunique() >= 13
        assert data["year_ending"].min() <= 2013

    def test_year_ending_derivation(self, data):
        sample = data.iloc[0]
        assert int(sample["academic_year"][:4]) + 1 == sample["year_ending"]

    def test_no_cartesian_expansion(self, data):
        """Each observation appears exactly once after the count/percentage merge."""
        keys = ["academic_year", "geography", "category", "fsm_entitlement"]
        assert not data.duplicated(subset=keys).any()

    def test_validates(self, data):
        assert school_leavers.validate_data(data)


class TestDestinationIntegrity:
    @pytest.fixture(scope="class")
    def data(self):
        return school_leavers.get_latest_school_leavers("destination", "lgd")

    def test_lgd_coverage(self, data):
        # 11 local government districts plus a Northern Ireland total.
        assert data["geography"].nunique() == 12
        assert "Northern Ireland" in set(data["geography"])

    def test_destination_prefix_stripped(self, data):
        assert not data["category"].str.startswith("School leavers with destination: ").any()

    def test_destination_categories(self, data):
        categories = set(data["category"])
        assert "higher education" in categories
        assert "employment" in categories

    def test_validates(self, data):
        assert school_leavers.validate_data(data)


class TestDeaWithoutFsme:
    """The DEA destination matrix omits the free school meal dimension entirely."""

    @pytest.fixture(scope="class")
    def data(self):
        return school_leavers.get_latest_school_leavers("destination", "dea")

    def test_fsme_defaults_to_all(self, data):
        assert set(data["fsm_entitlement"]) == {"all"}

    def test_dea_coverage(self, data):
        # 80 district electoral areas plus a Northern Ireland total.
        assert data["geography"].nunique() == 81

    def test_validates(self, data):
        assert school_leavers.validate_data(data)


class TestEqualityGroups:
    @pytest.fixture(scope="class")
    def data(self):
        return school_leavers.get_attainment_by_equality_group()

    def test_required_columns(self, data):
        expected = {
            "academic_year",
            "year_ending",
            "equality_type",
            "equality_group",
            "category",
            "count",
            "percentage",
        }
        assert expected == set(data.columns)

    def test_equality_types(self, data):
        assert set(data["equality_type"]) == {"Sex", "Religion", "Ethnic group", "Total"}

    def test_group_paired_with_type(self, data):
        pairs = data[["equality_type", "equality_group"]].drop_duplicates()
        sexes = set(pairs[pairs["equality_type"] == "Sex"]["equality_group"])
        assert sexes == {"Male", "Female"}
        assert set(pairs[pairs["equality_type"] == "Total"]["equality_group"]) == {"Northern Ireland"}

    def test_value_ranges(self, data):
        assert (data["count"].dropna() >= 0).all()
        assert data["percentage"].dropna().between(0, 100).all()

    def test_historical_coverage(self, data):
        assert data["academic_year"].nunique() >= 6
        assert "2018/19" in set(data["academic_year"])

    def test_validates(self, data):
        assert school_leavers.validate_data(data)


class TestGetLatestData:
    def test_default_dimension(self):
        data = school_leavers.get_latest_data()
        assert not data.empty
        assert "fsm_entitlement" in data.columns

    def test_equality_dimension(self):
        data = school_leavers.get_latest_data("equality")
        assert "equality_type" in data.columns

    def test_all_dimension(self):
        result = school_leavers.get_latest_data("all", "settlement")
        assert set(result) == {"attainment", "destination", "equality"}
        for frame in result.values():
            assert not frame.empty
            assert school_leavers.validate_data(frame)


class TestArgumentErrors:
    def test_bad_dimension(self):
        with pytest.raises(ValueError, match="dimension must be one of"):
            school_leavers.get_latest_data("nonsense")

    def test_bad_measure(self):
        with pytest.raises(ValueError, match="measure must be one of"):
            school_leavers.get_latest_school_leavers("nonsense")

    def test_bad_geography(self):
        with pytest.raises(ValueError, match="geography must be one of"):
            school_leavers.get_latest_school_leavers("attainment", "nonsense")


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def test_validate_none(self):
        assert not school_leavers.validate_data(None)

    def test_validate_empty_dataframe(self):
        assert not school_leavers.validate_data(pd.DataFrame())

    def test_validate_missing_columns(self):
        df = _good_df().drop(columns=["percentage"])
        assert not school_leavers.validate_data(df)

    def test_validate_negative_counts(self):
        df = _good_df()
        df.loc[0, "count"] = -1.0
        assert not school_leavers.validate_data(df)

    def test_validate_percentage_out_of_range(self):
        df = _good_df()
        df.loc[0, "percentage"] = 101.0
        assert not school_leavers.validate_data(df)

    def test_validate_too_few_years(self):
        assert not school_leavers.validate_data(_good_df().head(3))

    def test_validate_good_dataframe(self):
        assert school_leavers.validate_data(_good_df())

    def test_validate_tolerates_missing_values(self):
        df = _good_df()
        df.loc[0, ["count", "percentage"]] = None
        assert school_leavers.validate_data(df)
