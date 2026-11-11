"""Data integrity tests for the health visiting reviews module.

They run against the real publications (no mocks) with ``scope="class"`` fixtures so each workbook is
fetched once per class.

Key validations:
- Every published release (2018/19 onwards) is read, with every review for Northern Ireland and each Trust
- Trust counts sum to Northern Ireland, and each row's outcomes sum to its cohort
- The annual figures agree with the quarterly series, which comes from a different table
- A year with no release raises, and no other year is returned in its place
- The cohort tracks registered births, and the Trust names match the child protection module
"""

from datetime import date

import pandas as pd
import pytest

from bolster.data_sources.health_ni import child_protection as cp
from bolster.data_sources.health_ni import health_visiting_reviews as hvr
from bolster.data_sources.health_ni._base import NISRADataNotFoundError
from bolster.data_sources.nisra import births


class TestReleases:
    @pytest.fixture(scope="class")
    def publications(self) -> pd.DataFrame:
        return hvr.list_publications()

    def test_newest_first(self, publications: pd.DataFrame) -> None:
        assert publications["year"].is_monotonic_decreasing

    def test_covers_every_year_from_the_first_supported(self, publications: pd.DataFrame) -> None:
        years = sorted(publications["year"])
        assert years[0] == hvr.FIRST_RELEASE_YEAR
        assert years == list(range(years[0], years[-1] + 1)), f"Missing release years in {years}"

    def test_includes_a_recent_release(self, publications: pd.DataFrame) -> None:
        # The hub article trails the newest page, so this guards the per-year discovery.
        assert publications["year"].max() >= date.today().year - 2

    def test_workbooks_are_xlsx_links(self, publications: pd.DataFrame) -> None:
        assert publications["workbook_url"].str.lower().str.endswith(".xlsx").all()

    def test_a_year_without_a_release_raises_and_names_it(self) -> None:
        future = date.today().year + 5
        with pytest.raises(NISRADataNotFoundError, match=f"{future}/"):
            hvr.get_health_review_outcomes(year=future)

    def test_a_year_without_a_release_does_not_return_another_year(self) -> None:
        with pytest.raises(NISRADataNotFoundError):
            hvr.get_quarterly_on_time(year=date.today().year + 5)


class TestLatestOutcomes:
    @pytest.fixture(scope="class")
    def latest(self) -> pd.DataFrame:
        return hvr.get_health_review_outcomes()

    def test_required_columns(self, latest: pd.DataFrame) -> None:
        assert set(latest.columns) >= hvr.OUTCOMES_COLUMNS

    def test_is_the_newest_release(self, latest: pd.DataFrame) -> None:
        assert latest["year"].nunique() == 1
        assert int(latest["year"].iloc[0]) == int(hvr.list_publications()["year"].max())

    def test_every_review_for_ni_and_each_trust(self, latest: pd.DataFrame) -> None:
        assert len(latest) == len(hvr.REVIEWS) * (len(hvr.TRUSTS) + 1)
        assert set(latest["trust"]) == {hvr.NORTHERN_IRELAND, *hvr.TRUSTS}
        assert set(latest["review"]) == set(hvr.REVIEWS)

    def test_validates(self, latest: pd.DataFrame) -> None:
        assert hvr.validate_outcomes(latest)

    def test_count_dtypes_are_integer(self, latest: pd.DataFrame) -> None:
        for column in (*hvr.OUTCOME_COLUMNS, "cohort"):
            assert pd.api.types.is_integer_dtype(latest[column]), column

    def test_on_time_percentage_is_a_percentage(self, latest: pd.DataFrame) -> None:
        values = latest["on_time_pct"].astype(float)
        assert ((values > 0) & (values <= 100)).all()

    def test_trust_cohorts_sum_to_northern_ireland(self, latest: pd.DataFrame) -> None:
        for review, rows in latest.groupby("review"):
            trusts = rows[rows["trust"].isin(hvr.TRUSTS)]["cohort"].sum()
            ni = rows[rows["trust"] == hvr.NORTHERN_IRELAND]["cohort"].iloc[0]
            assert trusts == ni, review

    def test_cohorts_grow_with_age_at_review(self, latest: pd.DataFrame) -> None:
        """A cohort is the children reaching the review age in the year, so older reviews cover more of them."""
        ni = latest[latest["trust"] == hvr.NORTHERN_IRELAND].set_index("review")["cohort"]
        ordered = [int(ni[r]) for r in hvr.REVIEWS]
        assert ordered == sorted(ordered)


class TestOutcomesSeries:
    @pytest.fixture(scope="class")
    def series(self) -> pd.DataFrame:
        return hvr.get_health_review_outcomes_series()

    def test_every_release_year_is_read(self, series: pd.DataFrame) -> None:
        years = sorted(series["year"].unique())
        assert years == list(hvr.list_publications()["year"].sort_values()), "a release was skipped as unreadable"

    def test_each_year_is_complete(self, series: pd.DataFrame) -> None:
        sizes = series.groupby("year").size()
        assert (sizes == len(hvr.REVIEWS) * (len(hvr.TRUSTS) + 1)).all()

    def test_validates_each_year(self, series: pd.DataFrame) -> None:
        for _, year in series.groupby("year"):
            assert hvr.validate_outcomes(year)

    def test_2022_23_northern_ireland_new_baby_row_is_the_summary_tables(self, series: pd.DataFrame) -> None:
        """The 2022/23 new baby table's own Northern Ireland row disagrees with the summary and its Trust rows."""
        rows = series[(series["year"] == 2022) & (series["review"] == "new_baby")]
        ni = rows[rows["trust"] == hvr.NORTHERN_IRELAND].iloc[0]
        assert [int(ni[c]) for c in (*hvr.OUTCOME_COLUMNS, "cohort")] == [89, 18706, 1213, 233, 20241]
        trusts = rows[rows["trust"].isin(hvr.TRUSTS)]
        assert [int(trusts[c].sum()) for c in (*hvr.OUTCOME_COLUMNS, "cohort")] == [89, 18706, 1213, 233, 20241]

    def test_one_year_review_fell_in_2020_21_and_has_recovered(self, series: pd.DataFrame) -> None:
        one_year = series[(series["review"] == "1_year") & (series["trust"] == hvr.NORTHERN_IRELAND)].set_index("year")
        on_time = one_year["on_time_pct"].astype(float)
        assert on_time[2019] - on_time[2020] > 10, "the 2020/21 drop is no longer visible"
        assert on_time.iloc[-1] > on_time[2020]

    def test_new_baby_cohort_has_shrunk_since_2018_19(self, series: pd.DataFrame) -> None:
        cohort = series[(series["review"] == "new_baby") & (series["trust"] == hvr.NORTHERN_IRELAND)].set_index("year")[
            "cohort"
        ]
        assert cohort.iloc[-1] < cohort.iloc[0]


class TestQuarterlySeries:
    @pytest.fixture(scope="class")
    def quarterly(self) -> pd.DataFrame:
        return hvr.get_quarterly_on_time_series()

    def test_validates(self, quarterly: pd.DataFrame) -> None:
        assert hvr.validate_quarterly(quarterly)

    def test_starts_in_2017_18_and_runs_to_the_newest_release(self, quarterly: pd.DataFrame) -> None:
        assert quarterly["quarter_start"].min() == pd.Timestamp("2017-04-01")
        newest = int(hvr.list_publications()["year"].max())
        assert quarterly["quarter_start"].max() == pd.Timestamp(year=newest + 1, month=1, day=1)

    def test_is_contiguous_for_every_review(self, quarterly: pd.DataFrame) -> None:
        expected = len(pd.date_range(quarterly["quarter_start"].min(), quarterly["quarter_start"].max(), freq="3MS"))
        assert (quarterly.groupby("review").size() == expected).all()

    def test_no_missing_values(self, quarterly: pd.DataFrame) -> None:
        assert quarterly["on_time_pct"].notna().all()

    def test_stitched_values_equal_the_newest_release_where_windows_overlap(self, quarterly: pd.DataFrame) -> None:
        newest = hvr.get_quarterly_on_time()
        merged = newest.merge(quarterly, on=["quarter_start", "review"], suffixes=("_release", "_series"))
        assert len(merged) == len(newest)
        pd.testing.assert_series_equal(
            merged["on_time_pct_release"].astype(float),
            merged["on_time_pct_series"].astype(float),
            check_names=False,
        )

    def test_annual_figures_agree_with_the_quarterly_series(self, quarterly: pd.DataFrame) -> None:
        """Table 1's annual on-time figure is the mean of Table 8's four quarters, to within rounding."""
        annual = hvr.get_health_review_outcomes_series()
        annual = annual[annual["trust"] == hvr.NORTHERN_IRELAND][["financial_year", "review", "on_time_pct"]]
        quarterly_mean = (
            quarterly.groupby(["financial_year", "review"])["on_time_pct"].agg(["mean", "count"]).reset_index()
        )
        merged = annual.merge(quarterly_mean, on=["financial_year", "review"])
        assert len(merged) == len(annual), "a release year has no quarterly figures"
        assert (merged["count"] == 4).all()
        gap = (merged["on_time_pct"].astype(float) - merged["mean"].astype(float)).abs()
        assert gap.max() < 1.0, merged.assign(gap=gap).sort_values("gap").tail(3)


class TestCrossDataset:
    def test_new_baby_cohort_tracks_registered_births(self) -> None:
        """The new baby cohort is children reaching the review age in the financial year, so it is near, not equal to, births."""
        registered = births.get_latest_births()["registration"]
        registered = registered[registered["sex"] == "Persons"].copy()
        registered["month"] = pd.to_datetime(registered["month"])
        registered["year"] = registered["month"].apply(lambda d: d.year if d.month >= 4 else d.year - 1)
        by_year = registered.groupby("year")["births"].agg(["sum", "count"])

        series = hvr.get_health_review_outcomes_series()
        cohort = series[(series["review"] == "new_baby") & (series["trust"] == hvr.NORTHERN_IRELAND)].set_index("year")[
            "cohort"
        ]
        complete = by_year[by_year["count"] == 12]["sum"]
        common = cohort.index.intersection(complete.index)
        assert len(common) >= 6, "too few financial years with twelve months of births to compare"
        ratio = cohort.loc[common].astype(float) / complete.loc[common].astype(float)
        assert ratio.between(0.9, 1.05).all(), ratio
        assert cohort.loc[common].astype(float).corr(complete.loc[common].astype(float)) > 0.9

    def test_trust_names_match_child_protection(self) -> None:
        cp_data = cp.get_latest_child_protection()
        cp_trusts = set(cp_data[cp_data["measure"] == "referrals_by_trust"]["subcategory"])
        assert cp_trusts == set(hvr.TRUSTS)

    def test_child_protection_year_is_the_financial_year_end(self) -> None:
        """The two modules label the same financial year differently, so a join must add one to ``year``."""
        cp_data = cp.get_latest_child_protection()
        referrals = cp_data[cp_data["measure"] == "referrals_by_trust"]
        row = referrals[referrals["year"] == 2019].iloc[0]
        assert row["notes"] == f"Financial year {hvr.financial_year_label(2018)}"
