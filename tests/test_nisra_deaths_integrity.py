"""Data integrity tests for NISRA deaths statistics.

Validates internal consistency of the PxStat API-backed deaths module
across all four dimensions: totals, demographics, geography, place.

Key validations:
- Total deaths == sum of male + female deaths per week
- Total deaths == sum of all LGDs per week
- Total deaths == sum of all places of death per week
- Age breakdowns sum to "All ages" total for each sex
- All 11 NI LGDs present each week
- COVID/flu deaths do not exceed total deaths
"""

import pytest

from bolster.data_sources.nisra import deaths


class TestDeathsDataIntegrity:
    """Internal consistency checks across all dimensions."""

    @pytest.fixture(scope="class")
    def all_dims(self):
        return deaths.get_latest_deaths(dimension="all")

    @pytest.fixture(scope="class")
    def totals(self):
        return deaths.get_latest_deaths(dimension="totals")

    def test_demographics_schema(self, all_dims):
        assert sorted(all_dims["demographics"].columns.tolist()) == [
            "age_range",
            "deaths",
            "sex",
            "week_ending",
        ]

    def test_totals_schema(self, totals):
        for col in ("week_ending", "observed_deaths", "flu_pneumonia_deaths", "covid_deaths"):
            assert col in totals.columns, f"Missing column: {col}"

    def test_sex_categories_present(self, all_dims):
        sexes = set(all_dims["demographics"]["sex"].unique())
        assert "All persons" in sexes, f"Missing 'All persons'. Got: {sexes}"
        assert "Males" in sexes, f"Missing 'Males'. Got: {sexes}"
        assert "Females" in sexes, f"Missing 'Females'. Got: {sexes}"

    def test_age_ranges_present(self, all_dims):
        ages = set(all_dims["demographics"]["age_range"].unique())
        assert "All ages" in ages, f"Missing 'All ages'. Got: {ages}"
        specific = [a for a in ages if a != "All ages"]
        assert len(specific) >= 5, f"Expected ≥5 specific age bands, got {len(specific)}: {specific}"

    def test_place_categories_present(self, all_dims):
        places = {str(p).lower() for p in all_dims["place"]["place_of_death"].unique()}
        for keyword in ("hospital", "home", "hospice"):
            assert any(keyword in p for p in places), (
                f"Missing place containing '{keyword}'. Found: {places}"
            )

    def test_all_lgds_present_each_week(self, all_dims):
        geo = all_dims["geography"]
        for week, grp in geo.groupby("week_ending"):
            count = grp["lgd_name"].nunique()
            assert count == 11, f"Week {week}: expected 11 LGDs, got {count}"

    def test_demographics_male_female_sum_to_all_persons(self, all_dims):
        # Allow ±1 for rounding artefacts in pre-rounded official statistics
        demo = all_dims["demographics"]
        all_ages = demo[demo["age_range"] == "All ages"]
        for week, grp in all_ages.groupby("week_ending"):
            total = grp[grp["sex"] == "All persons"]["deaths"].sum()
            males = grp[grp["sex"] == "Males"]["deaths"].sum()
            females = grp[grp["sex"] == "Females"]["deaths"].sum()
            assert total > 0, f"Week {week}: All persons total is 0"
            assert abs(total - (males + females)) <= 1, (
                f"Week {week}: All persons ({total}) != Males ({males}) + Females ({females})"
            )

    def test_age_breakdowns_sum_to_all_ages(self, all_dims):
        # Allow ±1 for rounding artefacts in pre-rounded official statistics
        demo = all_dims["demographics"]
        for (week, sex), grp in demo.groupby(["week_ending", "sex"]):
            all_ages_total = grp[grp["age_range"] == "All ages"]["deaths"].sum()
            specific_sum = grp[grp["age_range"] != "All ages"]["deaths"].sum()
            if all_ages_total > 0:
                assert abs(all_ages_total - specific_sum) <= 1, (
                    f"Week {week}, {sex}: All ages ({all_ages_total}) != sum of bands ({specific_sum})"
                )

    def test_geography_sums_to_total(self, all_dims, totals):
        geo = all_dims["geography"]
        geo_weekly = geo.groupby("week_ending")["deaths"].sum()
        for week, geo_total in geo_weekly.items():
            row = totals[totals["week_ending"] == week]
            if not row.empty:
                obs = row["observed_deaths"].iloc[0]
                assert geo_total == obs, (
                    f"Week {week}: LGD sum ({geo_total}) != observed total ({obs})"
                )

    def test_place_sums_to_total(self, all_dims, totals):
        place = all_dims["place"]
        place_weekly = place.groupby("week_ending")["deaths"].sum()
        for week, place_total in place_weekly.items():
            row = totals[totals["week_ending"] == week]
            if not row.empty:
                obs = row["observed_deaths"].iloc[0]
                assert place_total == obs, (
                    f"Week {week}: Place sum ({place_total}) != observed total ({obs})"
                )

    def test_no_negative_deaths(self, all_dims, totals):
        assert (totals["observed_deaths"] >= 0).all()
        assert (all_dims["demographics"]["deaths"] >= 0).all()
        assert (all_dims["geography"]["deaths"] >= 0).all()
        assert (all_dims["place"]["deaths"] >= 0).all()

    def test_covid_deaths_not_exceed_total(self, totals):
        invalid = totals[totals["covid_deaths"] > totals["observed_deaths"]]
        assert len(invalid) == 0, (
            f"{len(invalid)} weeks where COVID > total: "
            f"{invalid[['week_ending', 'covid_deaths', 'observed_deaths']].to_dict('records')}"
        )

    def test_flu_deaths_not_exceed_total(self, totals):
        invalid = totals[totals["flu_pneumonia_deaths"] > totals["observed_deaths"]]
        assert len(invalid) == 0, (
            f"{len(invalid)} weeks where flu > total: "
            f"{invalid[['week_ending', 'flu_pneumonia_deaths', 'observed_deaths']].to_dict('records')}"
        )

    def test_weeks_chronological(self, totals):
        assert totals["week_ending"].is_monotonic_increasing

    def test_no_duplicate_weeks_in_totals(self, totals):
        assert not totals.duplicated(subset=["week_ending"]).any()

    def test_no_duplicate_records_in_demographics(self, all_dims):
        dupes = all_dims["demographics"].duplicated(subset=["week_ending", "sex", "age_range"])
        assert not dupes.any(), f"{dupes.sum()} duplicate records in demographics"

    def test_no_duplicate_records_in_geography(self, all_dims):
        dupes = all_dims["geography"].duplicated(subset=["week_ending", "lgd_name"])
        assert not dupes.any(), f"{dupes.sum()} duplicate records in geography"

    def test_no_duplicate_records_in_place(self, all_dims):
        dupes = all_dims["place"].duplicated(subset=["week_ending", "place_of_death"])
        assert not dupes.any(), f"{dupes.sum()} duplicate records in place"

    def test_cross_dimension_totals_match(self, all_dims, totals):
        """Demographics 'All persons'/'All ages' should match observed_deaths in totals."""
        demo = all_dims["demographics"]
        demo_totals = demo[(demo["sex"] == "All persons") & (demo["age_range"] == "All ages")]
        merged = demo_totals.merge(
            totals[["week_ending", "observed_deaths"]], on="week_ending", how="inner"
        )
        for _, row in merged.iterrows():
            assert row["deaths"] == row["observed_deaths"], (
                f"Week {row['week_ending'].date()}: "
                f"demographics total ({row['deaths']}) != observed ({row['observed_deaths']})"
            )

    def test_reasonable_data_coverage(self, totals):
        """Should have at least 52 weeks of data."""
        assert len(totals) >= 52, f"Only {len(totals)} weeks — expected at least 52"
