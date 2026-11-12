"""Data integrity tests for the NISRA Racial Equality Indicators.

Live tests read the PxStat ``*REI`` cubes; the validation tests at the end run
on small hand-built frames and need no network.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import racial_equality_indicators as rei
from bolster.data_sources.nisra import school_leavers
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError
from bolster.data_sources.nisra.pxstat import read_dataset


class TestAllIndicators:
    """Every indicator, loaded together (one PxStat request per cube)."""

    @pytest.fixture(scope="class")
    def all_data(self):
        return rei.get_latest_racial_equality_indicators()

    def test_columns(self, all_data):
        assert list(all_data.columns) == rei.OUTPUT_COLUMNS

    def test_every_indicator_present(self, all_data):
        assert set(all_data["indicator"]) == set(rei.INDICATORS)

    def test_cube_matches_indicator(self, all_data):
        pairs = all_data[["indicator", "cube"]].drop_duplicates()
        assert {row.indicator: row.cube for row in pairs.itertuples()} == {
            name: spec.cube for name, spec in rei.INDICATORS.items()
        }

    def test_validates(self, all_data):
        assert rei.validate_racial_equality_data(all_data) is True

    def test_consistency_validates(self, all_data):
        assert rei.validate_racial_equality_consistency(all_data) is True

    def test_survey_indicators_cover_twelve_years(self, all_data):
        survey = [
            "prejudice",
            "prejudice_increase",
            "acceptance",
            "culture_richness",
            "traveller_culture_respect",
            "friends",
            "public_life_participation",
            "public_life_encouragement",
            "public_bodies_needs",
            "belonging_neighbourhood",
            "belonging_ni",
        ]
        for name in survey:
            years = all_data.loc[all_data["indicator"] == name, "year"]
            assert (years.min(), years.max()) == (2014, 2025), name

    def test_recent_data(self, all_data):
        assert all_data["year"].max() >= 2025

    def test_percentages_are_percentages(self, all_data):
        pct = all_data[all_data["unit"] == "%"]["value"].dropna()
        assert pct.between(0, 100).all()

    def test_counts_are_non_negative(self, all_data):
        counts = all_data[all_data["unit"] == "Number"]["value"].dropna()
        assert (counts >= 0).all()

    def test_year_is_integer(self, all_data):
        assert str(all_data["year"].dtype) == "Int64"
        assert all_data["year"].notna().all()

    def test_labels_have_no_stray_whitespace(self, all_data):
        for column in ("group", "category", "measure"):
            labels = all_data[column].dropna()
            assert (labels == labels.str.strip()).all(), column
            assert not labels.str.contains(r"\s{2,}").any(), column


class TestSurveyIndicator:
    @pytest.fixture(scope="class")
    def prejudice(self):
        return rei.get_latest_racial_equality_indicators("prejudice")

    def test_northern_ireland_row_per_year(self, prejudice):
        ni = prejudice[prejudice["group"] == "Northern Ireland"]
        assert ni["year"].tolist() == list(range(2014, 2026))

    def test_ni_between_the_sexes(self, prejudice):
        """The NI figure lies between the female and male figures, within rounding."""
        wide = prejudice.pivot_table(index="year", columns="group", values="value")
        low = wide[["Sex - Female", "Sex - Male"]].min(axis=1) - 1
        high = wide[["Sex - Female", "Sex - Male"]].max(axis=1) + 1
        assert wide["Northern Ireland"].between(low, high).all()

    def test_ni_within_age_range(self, prejudice):
        ages = prejudice[prejudice["group"].str.startswith("Age -")]
        by_year = ages.groupby("year")["value"].agg(["min", "max"])
        ni = prejudice[prejudice["group"] == "Northern Ireland"].set_index("year")["value"]
        assert ((by_year["min"] - 1 <= ni) & (ni <= by_year["max"] + 1)).all()

    def test_group_labels_by_label_not_position(self, prejudice):
        assert {"Northern Ireland", "Sex - Female", "Sex - Male", "Religion - Catholic"} <= set(prejudice["group"])

    def test_no_category_dimension(self, prejudice):
        assert prejudice["category"].isna().all()


class TestPoliceRecorded:
    @pytest.fixture(scope="class")
    def police(self):
        return rei.get_latest_racial_equality_indicators("racist_incidents_crimes")

    def test_statistics(self, police):
        assert set(police["statistic"]) == {"RACEINREI", "RACECRREI"}

    def test_financial_year_periods(self, police):
        assert police["period"].str.fullmatch(r"\d{4}/\d{2}").all()
        assert police["year"].min() == 2013

    def test_crimes_never_exceed_incidents(self, police):
        wide = police.pivot_table(index="period", columns="statistic", values="value")
        assert (wide["RACECRREI"] <= wide["RACEINREI"]).all()

    def test_plausible_counts(self, police):
        assert police["value"].between(100, 10000).all()


class TestSchoolLeavers:
    @pytest.fixture(scope="class")
    def destinations(self):
        return rei.get_latest_racial_equality_indicators("school_destinations")

    def test_destinations_add_up_to_total(self, destinations):
        counts = destinations[destinations["unit"] == "Number"].pivot_table(
            index=["period", "group"], columns="category", values="value", aggfunc="sum"
        )
        parts = [c for c in counts.columns if c != "Total leavers"]
        assert (counts[parts].sum(axis=1) == counts["Total leavers"]).all()

    def test_two_ethnic_groups(self, destinations):
        assert set(destinations["group"]) == {"White", "Minority ethnic group"}

    def test_totals_match_school_leavers_module(self, destinations):
        """Total leavers by ethnic group sum to the all-leavers NI total in the school_leavers module."""
        ours = (
            destinations[(destinations["unit"] == "Number") & (destinations["category"] == "Total leavers")]
            .groupby("period")["value"]
            .sum()
        )
        theirs = school_leavers.get_latest_school_leavers("destination", "settlement")
        theirs = theirs[
            (theirs["geography"] == "Northern Ireland")
            & (theirs["fsm_entitlement"] == "all")
            & (theirs["category"] == "Total leavers")
        ].set_index("academic_year")["count"]
        joined = pd.concat([ours.rename("ours"), theirs.rename("theirs")], axis=1).dropna()
        assert len(joined) >= 10
        assert (joined["ours"] == joined["theirs"]).all()

    def test_gcse_rates_match_school_leavers_equality(self):
        """5+ GCSEs A*-C by ethnic group agrees with the school_leavers equality-group breakdown."""
        ours = rei.get_latest_racial_equality_indicators("school_leavers_gcse")
        ours = ours[ours["unit"] == "%"].pivot_table(index="period", columns="group", values="value")
        theirs = school_leavers.get_attainment_by_equality_group()
        theirs = theirs[
            (theirs["equality_type"] == "Ethnic group")
            & (theirs["category"] == "At least 5 GCSEs at grades A*-C (incl. equivalent qualifications)")
        ].pivot_table(index="academic_year", columns="equality_group", values="percentage")
        joined = ours.add_suffix("_destrei").join(theirs.add_suffix("_slsaeq"), how="inner")
        assert len(joined) >= 5
        assert (joined["Minority ethnic group_destrei"] - joined["Other_slsaeq"]).abs().max() < 0.05
        assert (joined["White_destrei"] - joined["White_slsaeq"]).abs().max() < 0.05


class TestHateCubesAgree:
    """The racist-motivation counts also appear in the PxStat ``HATE*`` cubes (not part of this module)."""

    @pytest.fixture(scope="class")
    def police(self):
        frame = rei.get_latest_racial_equality_indicators("racist_incidents_crimes")
        return frame.pivot_table(index="period", columns="statistic", values="value")

    @pytest.mark.parametrize(
        ("matrix", "geography", "statistic", "ours"),
        [
            ("HATELGD", "Local Government District", "allraccrm", "RACECRREI"),
            ("HATELGD", "Local Government District", "allracinc", "RACEINREI"),
            ("HATEHSCT", "Health and Social Care Trust", "allraccrm", "RACECRREI"),
        ],
    )
    def test_northern_ireland_row_matches(self, police, matrix, geography, statistic, ours):
        cube = read_dataset(matrix)
        rows = cube[(cube["STATISTIC"] == statistic) & (cube[geography] == "Northern Ireland")]
        theirs = rows.set_index("Financial year")["VALUE"]
        joined = pd.concat([police[ours].rename("ours"), theirs.rename("theirs")], axis=1).dropna()
        assert len(joined) == len(police)
        assert (joined["ours"] == joined["theirs"]).all()

    def test_districts_add_up_to_northern_ireland(self):
        cube = read_dataset("HATELGD")
        crimes = cube[cube["STATISTIC"] == "allraccrm"]
        ni = crimes[crimes["Local Government District"] == "Northern Ireland"].set_index("Financial year")["VALUE"]
        parts = (
            crimes[crimes["Local Government District"] != "Northern Ireland"].groupby("Financial year")["VALUE"].sum()
        )
        assert (parts == ni).all()


class TestPublicAppointments:
    @pytest.fixture(scope="class")
    def appointments(self):
        return rei.get_latest_racial_equality_indicators("public_appointments")

    def test_applications_nested(self, appointments):
        counts = appointments[appointments["unit"] == "Number"].pivot_table(
            index="period", columns="category", values="value"
        )
        assert (
            counts["Applications from minority ethnic people"] <= counts["Total applications where ethnicity is known"]
        ).all()
        assert (counts["Total applications where ethnicity is known"] <= counts["Total applications"]).all()


class TestAccessors:
    def test_list_indicators(self):
        listing = rei.list_indicators()
        assert list(listing.columns) == ["indicator", "cube", "title"]
        assert len(listing) == len(rei.INDICATORS)
        assert listing["cube"].is_unique

    def test_unknown_indicator_raises(self):
        with pytest.raises(ValueError, match="indicator must be one of"):
            rei.get_latest_racial_equality_indicators("not-an-indicator")

    def test_unknown_indicator_in_tidy_cube_raises(self):
        with pytest.raises(ValueError, match="indicator must be one of"):
            rei.tidy_cube("nope", pd.DataFrame())

    def test_missing_column_raises_not_found(self):
        raw = pd.DataFrame({"STATISTIC": ["PREJUDREI"], "VALUE": [1]})
        with pytest.raises(NISRADataNotFoundError, match="PREJUDREI"):
            rei.tidy_cube("prejudice", raw)

    def test_missing_dimension_column_raises_not_found(self):
        raw = pd.DataFrame(
            {
                "STATISTIC": ["PREJUDREI"],
                "Statistic Label": ["x"],
                "TLIST(A1)": [2014],
                "UNIT": ["%"],
                "VALUE": [1],
            }
        )
        with pytest.raises(NISRADataNotFoundError, match="EQGRP"):
            rei.tidy_cube("prejudice", raw)

    def test_force_refresh_is_ignored(self):
        assert len(rei.get_latest_racial_equality_indicators("racist_incidents_crimes", force_refresh=True)) == 26


def _frame(**overrides):
    base = {
        "indicator": "prejudice",
        "cube": "PREJUDREI",
        "statistic": "PREJUDREI",
        "measure": "m",
        "period": ["2014", "2015"],
        "year": pd.array([2014, 2015], dtype="Int64"),
        "group_code": "N92000002",
        "group": "Northern Ireland",
        "category_code": pd.NA,
        "category": pd.NA,
        "unit": "%",
        "value": [10.0, 12.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)[rei.OUTPUT_COLUMNS]


class TestValidation:
    """Unit tests for validation edge cases (no network)."""

    def test_valid_frame_passes(self):
        assert rei.validate_racial_equality_data(_frame()) is True

    def test_empty_frame(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            rei.validate_racial_equality_data(_frame().iloc[0:0])

    def test_missing_columns(self):
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            rei.validate_racial_equality_data(_frame().drop(columns=["value"]))

    def test_negative_value(self):
        with pytest.raises(NISRAValidationError, match="Negative"):
            rei.validate_racial_equality_data(_frame(value=[-1.0, 12.0]))

    def test_percentage_above_100(self):
        with pytest.raises(NISRAValidationError, match="above 100"):
            rei.validate_racial_equality_data(_frame(value=[101.0, 12.0]))

    def test_count_above_100_is_fine(self):
        assert rei.validate_racial_equality_data(_frame(unit="Number", value=[500.0, 600.0])) is True

    def test_duplicate_observation(self):
        with pytest.raises(NISRAValidationError, match="Duplicate"):
            rei.validate_racial_equality_data(_frame(period=["2014", "2014"]))

    def test_series_missing_a_period(self):
        extra = _frame(group_code="EQ201", group="Sex - Female", period=["2014", "2015"])
        frame = pd.concat([_frame(), extra.iloc[:1]], ignore_index=True)
        with pytest.raises(NISRAValidationError, match="lack observations"):
            rei.validate_racial_equality_data(frame)

    def test_non_consecutive_years(self):
        frame = _frame(period=["2014", "2016"], year=pd.array([2014, 2016], dtype="Int64"))
        with pytest.raises(NISRAValidationError, match="not consecutive"):
            rei.validate_racial_equality_data(frame)

    def test_nan_values_allowed(self):
        assert rei.validate_racial_equality_data(_frame(value=[float("nan"), 12.0])) is True


class TestConsistencyValidation:
    def test_missing_indicator_column(self):
        with pytest.raises(NISRAValidationError, match="indicator"):
            rei.validate_racial_equality_consistency(pd.DataFrame({"x": [1]}))

    def test_frame_without_checked_indicators_passes(self):
        assert rei.validate_racial_equality_consistency(_frame()) is True

    def test_crimes_exceeding_incidents(self):
        frame = _frame(
            indicator="racist_incidents_crimes",
            statistic=["RACEINREI", "RACECRREI"],
            period="2025/26",
            unit="Number",
            value=[10.0, 20.0],
        )
        with pytest.raises(NISRAValidationError, match="exceed"):
            rei.validate_racial_equality_consistency(frame)

    def test_police_cube_missing_statistic(self):
        frame = _frame(indicator="racist_incidents_crimes", statistic="RACEINREI", unit="Number")
        with pytest.raises(NISRAValidationError, match="RACECRREI"):
            rei.validate_racial_equality_consistency(frame)

    def test_destinations_that_do_not_sum(self):
        frame = _frame(
            indicator="school_destinations",
            period="2024/25",
            group="White",
            category=["Employment", "Total leavers"],
            unit="Number",
            value=[5.0, 10.0],
        )
        with pytest.raises(NISRAValidationError, match="total leavers"):
            rei.validate_racial_equality_consistency(frame)

    def test_destination_percentages_that_do_not_sum(self):
        frame = pd.concat(
            [
                _frame(
                    indicator="school_destinations",
                    period="2024/25",
                    group="White",
                    category=["Employment", "Total leavers"],
                    unit="Number",
                    value=[10.0, 10.0],
                ),
                _frame(
                    indicator="school_destinations",
                    period="2024/25",
                    group="White",
                    category=["Employment", "Total leavers"],
                    unit="%",
                    value=[50.0, 100.0],
                ),
            ],
            ignore_index=True,
        )
        with pytest.raises(NISRAValidationError, match="add up to 100"):
            rei.validate_racial_equality_consistency(frame)

    def test_destinations_missing_total(self):
        frame = _frame(indicator="school_destinations", category="Employment", unit="Number")
        with pytest.raises(NISRAValidationError, match="Total leavers"):
            rei.validate_racial_equality_consistency(frame)

    def test_appointments_not_nested(self):
        frame = _frame(
            indicator="public_appointments",
            period="2021/22",
            year=pd.array([2021, 2021, 2021], dtype="Int64"),
            category=[
                "Total applications",
                "Total applications where ethnicity is known",
                "Applications from minority ethnic people",
            ],
            unit="Number",
            value=[10.0, 5.0, 8.0],
        )
        with pytest.raises(NISRAValidationError, match="not nested"):
            rei.validate_racial_equality_consistency(frame)

    def test_appointments_missing_category(self):
        frame = _frame(indicator="public_appointments", category="Total applications", unit="Number")
        with pytest.raises(NISRAValidationError, match="Applications from minority"):
            rei.validate_racial_equality_consistency(frame)
