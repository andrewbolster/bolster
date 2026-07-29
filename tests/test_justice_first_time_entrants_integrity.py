"""Integrity tests for the first time entrants module.

Tests use the real Department of Justice bulletin discovered through GOV.UK (no
mocks). Network calls are made once per class via ``scope="class"`` fixtures.
Parsing, labelling and validation edge cases are covered by network-free unit
tests built from small in-memory frames.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import first_time_entrants as fte
from bolster.data_sources.justice.first_time_entrants import (
    FirstTimeEntrantsDataNotFoundError,
)


@pytest.mark.network
class TestDiscovery:
    """The publication and workbook are located through the GOV.UK APIs."""

    @pytest.fixture(scope="class")
    def publication_url(self):
        return fte.find_latest_publication()

    def test_publication_is_on_justice_ni(self, publication_url):
        assert publication_url.startswith("https://www.justice-ni.gov.uk/publications/")

    def test_publication_is_the_right_series(self, publication_url):
        assert "first-time-entrants" in publication_url

    def test_data_url_is_an_ods_workbook(self, publication_url):
        assert fte.find_data_url(publication_url).endswith(".ods")


@pytest.mark.network
class TestAnnualSeriesIntegrity:
    """Integrity tests for the ten-year headline series (worksheet 6)."""

    @pytest.fixture(scope="class")
    def series(self):
        return fte.get_annual_series()

    def test_required_columns(self, series):
        assert {"financial_year", "year", "first_time_offender_pct"}.issubset(series.columns)

    def test_not_empty(self, series):
        assert not series.empty

    def test_ten_years_of_history(self, series):
        assert len(series) >= 10

    def test_years_ascending_and_unique(self, series):
        assert series["year"].is_monotonic_increasing
        assert series["year"].is_unique

    def test_no_gaps_in_the_series(self, series):
        assert (series["year"].diff().dropna() == 1).all()

    def test_starts_in_2015_16(self, series):
        assert series.iloc[0]["financial_year"] == "2015-16"

    def test_recent_coverage(self, series):
        assert series["year"].max() >= 2024

    def test_percentages_in_plausible_range(self, series):
        assert series["first_time_offender_pct"].between(15, 45).all()

    def test_financial_year_matches_year(self, series):
        assert (series["financial_year"].str[:4].astype(int) == series["year"]).all()

    def test_published_2015_16_figure(self, series):
        """The first year of the series is published to full precision."""
        row = series.set_index("financial_year").loc["2015-16"]
        assert row["first_time_offender_pct"] == pytest.approx(30.423271, abs=1e-5)

    def test_published_2024_25_figure(self, series):
        row = series.set_index("financial_year").loc["2024-25"]
        assert row["first_time_offender_pct"] == pytest.approx(26.3, abs=0.05)

    def test_rate_has_fallen_since_2015(self, series):
        """The long-run direction of travel is downward, from ~30% to ~26%."""
        assert series.iloc[-1]["first_time_offender_pct"] < series.iloc[0]["first_time_offender_pct"]


@pytest.mark.network
class TestBreakdownIntegrity:
    """Integrity tests shared across the four published breakdowns."""

    @pytest.fixture(scope="class")
    def breakdowns(self):
        return {dimension: fte.get_breakdown(dimension) for dimension in fte.DIMENSIONS}

    def test_required_columns(self, breakdowns):
        expected = {"measure", "category", "financial_year", "count", "denominator", "percentage"}
        for frame in breakdowns.values():
            assert expected.issubset(frame.columns)

    def test_none_empty(self, breakdowns):
        for dimension, frame in breakdowns.items():
            assert not frame.empty, dimension

    def test_all_four_measures_present(self, breakdowns):
        for frame in breakdowns.values():
            assert set(frame["measure"]) == set(fte.MEASURES)

    def test_two_financial_years_present(self, breakdowns):
        for frame in breakdowns.values():
            assert len(frame["financial_year"].unique()) == 2

    def test_prior_year_has_no_counts(self, breakdowns):
        """Only the latest year is published with counts and denominators."""
        for frame in breakdowns.values():
            prior = frame[frame["financial_year"] == frame["financial_year"].min()]
            assert prior["count"].isna().all()
            assert prior["denominator"].isna().all()

    def test_every_breakdown_has_a_total(self, breakdowns):
        for dimension, frame in breakdowns.items():
            assert "Total" in set(frame["category"]), dimension

    def test_percentages_within_bounds(self, breakdowns):
        for frame in breakdowns.values():
            percentages = frame["percentage"].dropna()
            assert percentages.between(0, 100).all()

    def test_counts_never_exceed_denominators(self, breakdowns):
        for frame in breakdowns.values():
            rows = frame.dropna(subset=["count", "denominator"])
            assert (rows["count"] <= rows["denominator"]).all()

    def test_percentage_matches_count_over_denominator(self, breakdowns):
        """Published percentages are recomputable from the published counts."""
        for dimension, frame in breakdowns.items():
            rows = frame.dropna(subset=["count", "denominator", "percentage"])
            rows = rows[rows["denominator"] > 0]
            implied = 100 * rows["count"] / rows["denominator"]
            assert (implied - rows["percentage"]).abs().max() < 0.6, dimension

    def test_no_note_markers_left_in_categories(self, breakdowns):
        for frame in breakdowns.values():
            assert not frame["category"].str.contains(r"\[note", case=False).any()

    def test_age_bands_as_published(self, breakdowns):
        age = breakdowns["age"]
        assert {"10 to 17", "18 to 24", "60 & over", "Total"}.issubset(set(age["category"]))

    def test_age_typo_is_repaired(self, breakdowns):
        """The workbook prints the 40-49 band as "40 t0 49"."""
        categories = set(breakdowns["age"]["category"])
        assert "40 to 49" in categories
        assert "40 t0 49" not in categories

    def test_gender_categories(self, breakdowns):
        assert set(breakdowns["gender"]["category"]) == {"Male", "Female", "Total"}

    def test_offence_categories(self, breakdowns):
        offences = set(breakdowns["offence"]["category"])
        assert {"Violence Against the Person", "Motoring", "Drugs", "Sexual"}.issubset(offences)

    def test_disposal_categories(self, breakdowns):
        disposals = set(breakdowns["disposal"]["category"])
        assert {"Imprisonment", "Monetary Penalty", "Community sentence"}.issubset(disposals)


@pytest.mark.network
class TestPublishedFigures:
    """Anchors against figures published in the 2024-25 bulletin."""

    @pytest.fixture(scope="class")
    def latest(self):
        frames = {dimension: fte.get_breakdown(dimension) for dimension in fte.DIMENSIONS}
        return {k: v[v["financial_year"] == "2024-25"] for k, v in frames.items()}

    @staticmethod
    def _row(frame, measure, category):
        match = frame[(frame["measure"] == measure) & (frame["category"] == category)]
        assert len(match) == 1, f"expected one row for {measure}/{category}, got {len(match)}"
        return match.iloc[0]

    def test_headline_total(self, latest):
        """7,409 of 28,188 convictions and diversions were first offences (26.3%)."""
        row = self._row(latest["age"], "all", "Total")
        assert row["count"] == 7409
        assert row["denominator"] == 28188
        assert row["percentage"] == pytest.approx(26.3, abs=0.05)

    def test_first_convictions_total(self, latest):
        row = self._row(latest["age"], "convictions", "Total")
        assert row["count"] == 6583
        assert row["denominator"] == 24564
        assert row["percentage"] == pytest.approx(26.8, abs=0.05)

    def test_first_offences_at_court_total(self, latest):
        row = self._row(latest["age"], "court", "Total")
        assert row["count"] == 5667
        assert row["denominator"] == 24564
        assert row["percentage"] == pytest.approx(23.1, abs=0.05)

    def test_diversions_total(self, latest):
        """Nearly half of all diversionary disposals go to first offenders."""
        row = self._row(latest["age"], "diversions", "Total")
        assert row["count"] == 1742
        assert row["denominator"] == 3624
        assert row["percentage"] == pytest.approx(48.1, abs=0.05)

    def test_youngest_age_band(self, latest):
        """41% of 10-17 year olds dealt with had no prior record."""
        row = self._row(latest["age"], "all", "10 to 17")
        assert row["count"] == 599
        assert row["denominator"] == 1462
        assert row["percentage"] == pytest.approx(41.0, abs=0.05)

    def test_gender_split(self, latest):
        male = self._row(latest["gender"], "all", "Male")
        female = self._row(latest["gender"], "all", "Female")
        assert male["count"] == 5141
        assert male["denominator"] == 22017
        assert female["count"] == 2268
        assert female["denominator"] == 6171

    def test_women_more_likely_to_be_first_offenders(self, latest):
        """36.8% of women dealt with were first offenders against 23.4% of men."""
        male = self._row(latest["gender"], "all", "Male")
        female = self._row(latest["gender"], "all", "Female")
        assert female["percentage"] - male["percentage"] > 10

    def test_imprisonment_rarely_a_first_offence(self, latest):
        """Only 5.7% of custodial sentences went to first offenders."""
        row = self._row(latest["disposal"], "all", "Imprisonment")
        assert row["count"] == 202
        assert row["denominator"] == 3573
        assert row["percentage"] == pytest.approx(5.7, abs=0.05)

    def test_monetary_penalty_is_the_largest_disposal(self, latest):
        row = self._row(latest["disposal"], "all", "Monetary Penalty")
        assert row["count"] == 4551
        assert row["denominator"] == 13375

    def test_motoring_dominates_offences(self, latest):
        row = self._row(latest["offence"], "all", "Motoring")
        assert row["count"] == 4464
        assert row["denominator"] == 11751

    def test_suppressed_cells_become_nan(self, latest):
        """Robbery first convictions are withheld as too small to publish."""
        row = self._row(latest["offence"], "convictions", "Robbery")
        assert pd.isna(row["count"])
        assert pd.isna(row["denominator"])


@pytest.mark.network
class TestOffenceDisposalSplitIntegrity:
    """Integrity tests for the offence-by-disposal table (worksheet 4)."""

    @pytest.fixture(scope="class")
    def split(self):
        return fte.get_offence_disposal_split()

    def test_required_columns(self, split):
        expected = {
            "offence",
            "first_offence_convictions",
            "first_offence_diversions",
            "all_convictions_and_diversions",
            "convictions_pct",
            "diversions_pct",
        }
        assert expected.issubset(split.columns)

    def test_not_empty(self, split):
        assert not split.empty

    def test_has_a_total_row(self, split):
        assert "Total" in set(split["offence"])

    def test_offences_unique(self, split):
        assert split["offence"].is_unique

    def test_published_total_row(self, split):
        row = split.set_index("offence").loc["Total"]
        assert row["first_offence_convictions"] == 5667
        assert row["first_offence_diversions"] == 1742
        assert row["all_convictions_and_diversions"] == 28188

    def test_shares_over_a_common_denominator(self, split):
        """Both routes are expressed over the same denominator, so they sum."""
        rows = split.dropna(subset=["convictions_pct", "diversions_pct"])
        assert (rows["convictions_pct"] + rows["diversions_pct"] <= 100).all()

    def test_convictions_pct_recomputable(self, split):
        rows = split.dropna(subset=["first_offence_convictions", "all_convictions_and_diversions"])
        implied = 100 * rows["first_offence_convictions"] / rows["all_convictions_and_diversions"]
        assert (implied - rows["convictions_pct"]).abs().max() < 0.6

    def test_motoring_is_overwhelmingly_court_business(self, split):
        """Motoring first offences reach court 17x more often than diversion."""
        row = split.set_index("offence").loc["Motoring"]
        assert row["first_offence_convictions"] > 10 * row["first_offence_diversions"]

    def test_typo_suppression_marker_becomes_nan(self, split):
        """One robbery cell is marked "[d}" rather than "[d]"."""
        row = split.set_index("offence").loc["Robbery"]
        assert pd.isna(row["convictions_pct"])


class TestValidation:
    """Argument validation - no network calls needed."""

    def test_unknown_dimension_raises(self):
        with pytest.raises(ValueError, match="dimension must be one of"):
            fte.get_breakdown("height")

    def test_unknown_measure_raises(self):
        with pytest.raises(ValueError, match="measure must be one of"):
            fte.get_breakdown("age", measure="everything")

    def test_dimensions_and_measures_are_distinct(self):
        assert len(fte.MEASURES) == 4
        assert len({letter for letter, _ in fte.MEASURES.values()}) == 4
        assert len(fte.DIMENSIONS) == 4


class TestParsing:
    """Unit tests for workbook parsing built from in-memory frames."""

    @staticmethod
    def _sheet():
        return pd.DataFrame(
            [
                ["Table 1a: First offences by age band, 2024-25", None, None, None, None],
                [
                    "Age band",
                    "2023-24 First offences as % of all",
                    "2024-25 First offences",
                    "2024-25 All convictions",
                    "2024-25 First offences as %",
                ],
                ["10 to 17 [note 2]", 41.8, 599, 1462, 41.0],
                ["40 t0 49", 23.8, 1167, 5182, 22.5],
                ["Robbery", "[low]", "[c]", "[d]", "[d}"],
                [None, None, None, None, None],
            ]
        )

    def test_parse_table_emits_both_years(self):
        frame = fte._parse_table(self._sheet(), 1)
        assert set(frame["financial_year"]) == {"2023-24", "2024-25"}
        assert len(frame) == 6

    def test_parse_table_strips_note_markers(self):
        frame = fte._parse_table(self._sheet(), 1)
        assert "10 to 17" in set(frame["category"])

    def test_parse_table_repairs_age_typo(self):
        frame = fte._parse_table(self._sheet(), 1)
        assert "40 to 49" in set(frame["category"])

    def test_parse_table_suppresses_non_numeric_cells(self):
        frame = fte._parse_table(self._sheet(), 1)
        robbery = frame[(frame["category"] == "Robbery") & (frame["financial_year"] == "2024-25")].iloc[0]
        assert pd.isna(robbery["count"])
        assert pd.isna(robbery["percentage"])

    def test_parse_table_stops_at_blank_row(self):
        sheet = self._sheet()
        sheet.loc[6] = ["Trailing junk", 1, 2, 3, 4]
        frame = fte._parse_table(sheet, 1)
        assert "Trailing junk" not in set(frame["category"])

    def test_find_table_locates_header_row(self):
        assert fte._find_table(self._sheet(), 1, "a") == 1

    def test_find_table_missing_raises(self):
        with pytest.raises(FirstTimeEntrantsDataNotFoundError, match="Table 9d not found"):
            fte._find_table(self._sheet(), 9, "d")

    def test_parse_table_without_years_raises(self):
        sheet = pd.DataFrame([["Age band", "First offences", "Count", "Denominator", "Percent"], ["Total", 1, 2, 3, 4]])
        with pytest.raises(FirstTimeEntrantsDataNotFoundError, match="Could not read financial years"):
            fte._parse_table(sheet, 0)

    def test_parse_table_without_rows_raises(self):
        sheet = self._sheet().iloc[:2]
        with pytest.raises(FirstTimeEntrantsDataNotFoundError, match="No data rows"):
            fte._parse_table(sheet, 1)

    def test_missing_worksheet_raises(self):
        with pytest.raises(FirstTimeEntrantsDataNotFoundError, match="Worksheet '9' not found"):
            fte._sheet({"1": pd.DataFrame()}, "9")

    def test_clean_label_handles_notes_and_whitespace(self):
        assert fte._clean_label("Male  [note 4]") == "Male"
        assert fte._clean_label(" Total ") == "Total"

    def test_to_number_maps_markers_to_nan(self):
        for marker in ("[low]", "[c]", "[d]", "[d}", "n.a.", None):
            assert pd.isna(fte._to_number(marker))

    def test_to_number_parses_values(self):
        assert fte._to_number("26.3") == pytest.approx(26.3)
        assert fte._to_number(7409) == 7409
