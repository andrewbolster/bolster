"""Integrity tests for the adult and youth reoffending statistics module.

Tests use real data downloaded from justice-ni.gov.uk (no mocks). Network calls are made once
per class via ``scope="class"`` fixtures. Parsing and validation edge cases are covered by
network-free unit tests that feed rows in the same layout as the real workbook straight to the
parsers, plus a small ODS written to a temporary path for the workbook reader.
"""

import math

import pandas as pd
import pytest
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P

from bolster.data_sources.justice import reoffending
from bolster.data_sources.justice.reoffending import (
    ReoffendingDataError,
    ReoffendingDataNotFoundError,
    ReoffendingValidationError,
)

# The 2023/24 cohort workbook (published November 2026) is pinned by ``cohort=2023`` so the
# expected counts stay stable when a newer cohort is published.
PINNED_COHORT = 2023
PINNED_2023_24 = {
    "all": (20887, 3606),
    "adult": (19984, 3398),
    "youth": (903, 208),
}


class TestDiscovery:
    """Discovery of the workbook from the DoJ publication pages."""

    @pytest.fixture(scope="class")
    def latest_url(self):
        return reoffending.get_data_file_url()

    def test_latest_is_tables_workbook(self, latest_url):
        assert latest_url.startswith("https://www.justice-ni.gov.uk/")
        assert reoffending._is_tables_workbook(latest_url)

    def test_earlier_cohort_resolves_to_its_own_workbook(self, latest_url):
        earlier = reoffending.get_data_file_url(2022)
        assert reoffending._is_tables_workbook(earlier)
        assert earlier != latest_url

    def test_unpublished_cohort_raises_naming_it(self):
        with pytest.raises(ReoffendingDataNotFoundError, match="1990/91"):
            reoffending.get_data_file_url(1990)


class TestAnnualRates:
    """Integrity tests for the annual rates series."""

    @pytest.fixture(scope="class")
    def rates(self):
        return reoffending.get_reoffending_rates()

    @pytest.fixture(scope="class")
    def rates_2023_24(self):
        return reoffending.get_reoffending_rates(cohort=PINNED_COHORT)

    def test_required_columns(self, rates):
        assert list(rates.columns) == ["cohort", "cohort_start", "group", "cohort_size", "reoffenders", "rate_pct"]

    def test_three_groups_with_full_history(self, rates):
        assert set(rates.group) == {"all", "adult", "youth"}
        for _, rows in rates.groupby("group"):
            assert rows.cohort_start.min() == 2010
            assert len(rows) >= 14

    def test_series_is_current(self, rates):
        """Cohorts trail publication by over two years, but the newest should be 2023/24 or later."""
        assert rates.cohort_start.max() >= 2023

    def test_validates(self, rates):
        assert reoffending.validate_reoffending_rates(rates) is True

    def test_value_ranges(self, rates):
        assert rates.rate_pct.between(0, 100).all()
        assert (rates.cohort_size > 0).all()
        assert (rates.reoffenders <= rates.cohort_size).all()

    def test_youth_rate_exceeds_adult_rate_every_cohort(self, rates):
        wide = rates.pivot(index="cohort_start", columns="group", values="rate_pct")
        assert (wide.youth > wide.adult).all()

    def test_pinned_cohort_matches_published_figures(self, rates_2023_24):
        latest = rates_2023_24[rates_2023_24.cohort == "2023/24"].set_index("group")
        for group, (size, reoffenders) in PINNED_2023_24.items():
            assert (latest.loc[group, "cohort_size"], latest.loc[group, "reoffenders"]) == (size, reoffenders)
        assert latest.loc["all", "rate_pct"] == 17.3

    def test_pinned_cohort_series_ends_at_that_cohort(self, rates_2023_24):
        assert rates_2023_24.cohort_start.max() == PINNED_COHORT

    def test_earlier_workbook_returns_series_ending_at_its_cohort(self):
        earlier = reoffending.get_reoffending_rates(cohort=2022)
        assert earlier.cohort_start.max() == 2022

    def test_get_latest_data_is_the_rates_series(self, rates):
        pd.testing.assert_frame_equal(reoffending.get_latest_data(), rates)


class TestBreakdowns:
    """Integrity tests for the breakdown tables, including agreement with the annual series."""

    @pytest.fixture(scope="class")
    def rates(self):
        return reoffending.get_reoffending_rates(cohort=PINNED_COHORT)

    @pytest.fixture(scope="class")
    def age_gender(self):
        return reoffending.get_reoffending_by_age_gender(cohort=PINNED_COHORT)

    @pytest.fixture(scope="class")
    def disposal(self):
        return reoffending.get_reoffending_by_disposal(cohort=PINNED_COHORT)

    @pytest.fixture(scope="class")
    def offence(self):
        return reoffending.get_reoffending_by_offence_category(cohort=PINNED_COHORT)

    @staticmethod
    def _headline(rates: pd.DataFrame, group: str) -> tuple[int, int]:
        row = rates[(rates.cohort_start == PINNED_COHORT) & (rates.group == group)].iloc[0]
        return int(row.cohort_size), int(row.reoffenders)

    def test_age_gender_columns_and_groups(self, age_gender):
        assert list(age_gender.columns) == ["age_band", "group", "reoffenders", "cohort_size", "rate_pct"]
        assert set(age_gender.group) == {"all", "male", "female"}
        assert age_gender.age_band.nunique() == 12
        assert not age_gender.age_band.str.lower().eq("total").any()

    def test_age_bands_sum_to_the_annual_series(self, age_gender, rates):
        everyone = age_gender[age_gender.group == "all"]
        assert (int(everyone.cohort_size.sum()), int(everyone.reoffenders.sum())) == self._headline(rates, "all")

    def test_males_plus_females_make_everyone_in_each_band(self, age_gender):
        wide = age_gender.pivot(index="age_band", columns="group", values="cohort_size")
        assert (wide.male + wide.female == wide["all"]).all()

    def test_small_cohorts_have_suppressed_rates_but_kept_counts(self, age_gender):
        small = age_gender[age_gender.cohort_size < 50]
        assert not small.empty
        assert small.rate_pct.isna().all()
        assert small.reoffenders.notna().all()

    def test_offence_categories_sum_to_the_annual_series(self, offence, rates):
        for group in ("all", "adult", "youth"):
            rows = offence[offence.group == group]
            assert (int(rows.cohort_size.sum()), int(rows.reoffenders.sum())) == self._headline(rates, group)

    def test_offence_categories_present(self, offence):
        assert {"VAP", "Theft", "Drugs", "Motoring"} <= set(offence.offence_category)

    def test_disposal_overall_total_matches_the_annual_series(self, disposal, rates):
        overall = disposal[disposal.disposal_group == "Overall total"].set_index("group")
        for group in ("all", "adult", "youth"):
            assert (int(overall.loc[group, "cohort_size"]), int(overall.loc[group, "reoffenders"])) == self._headline(
                rates, group
            )

    def test_disposals_never_sum_to_less_than_their_group_total(self, disposal):
        """A person is counted once per group, so individual disposals add up to at least the subtotal."""
        grouped = disposal[disposal.disposal_group != "Overall total"]
        for (_, _), rows in grouped.groupby(["disposal_group", "group"]):
            total = rows[rows.disposal == "Total"].cohort_size.iloc[0]
            assert rows[rows.disposal != "Total"].cohort_size.sum() >= total

    def test_disposal_has_the_four_groups(self, disposal):
        assert set(disposal.disposal_group) == {
            "Custody release",
            "Community supervision",
            "Community other",
            "Diversionary disposal",
            "Overall total",
        }

    def test_custody_release_reoffends_more_than_a_monetary_penalty(self, disposal):
        everyone = disposal[disposal.group == "all"].set_index("disposal")
        assert everyone.loc["Imprisonment", "rate_pct"] > everyone.loc["Monetary Penalty", "rate_pct"]


# ---------------------------------------------------------------------------
# Network-free unit tests
# ---------------------------------------------------------------------------

RATES_HEADER = [
    "Year",
    "Total number in cohort",
    "Total number who reoffended within one year",
    "Overall one-year proven reoffending rate (%)",
    "",
    "Year",
    "Number of adults in cohort",
    "Number of adults who reoffended within one year",
    "Adult one-year proven reoffending rate (%)",
    "",
    "Year",
    "Number of youths in cohort",
    "Number of youths who reoffended within one year",
    "Youth one-year proven reoffending rate (%)",
]


def _rates_rows(*cohorts: tuple[str, list[str], list[str], list[str]]) -> list[list[str]]:
    """Build the three side-by-side tables from (cohort, overall, adult, youth) triples."""
    rows = [
        ["Worksheet 1: Annual reoffending rates"],
        ["This worksheet contains three tables placed side by side."],
        ["Return to table of contents"],
        ["Source: Adult and Youth Reoffending in Northern Ireland"],
        ["Table 1a: Overall reoffending rates", "", "", "", "", "Table 1b: Adult reoffending rates"],
        RATES_HEADER,
    ]
    for cohort, overall, adult, youth in cohorts:
        rows.append([cohort, *overall, "", cohort, *adult, "", cohort, *youth])
    return rows


GOOD_RATES = _rates_rows(
    ("2021/22", ["1,000", "170", "17.0%"], ["900", "144", "16.0%"], ["100", "26", "26.0%"]),
    ("2022/23", ["1,100", "187", "17.0%"], ["1,000", "160", "16.0%"], ["100", "27", "27.0%"]),
)


class TestHelpers:
    def test_cohort_label(self):
        assert reoffending.cohort_label(2023) == "2023/24"
        assert reoffending.cohort_label(1999) == "1999/00"

    def test_cohort_start(self):
        assert reoffending._cohort_start("2010/11") == 2010
        with pytest.raises(ReoffendingDataError, match="Unrecognised cohort label"):
            reoffending._cohort_start("Total")

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("Total number who reoffended", ("reoffenders", "all")),
            ("Total number who reoffended within one year", ("reoffenders", "all")),
            ("Number of adults who reoffended", ("reoffenders", "adult")),
            ("Number of youths in cohort", ("cohort_size", "youth")),
            ("Number of females in cohort", ("cohort_size", "female")),
            ("Overall one-year proven reoffending rate (%)", ("rate_pct", "all")),
            ("One-year proven reoffending rate (%)", ("rate_pct", "all")),
            ("Male one-year proven reoffending rate (%)", ("rate_pct", "male")),
            ("Age", None),
            ("Disposal group", None),
        ],
    )
    def test_measure_of(self, header, expected):
        assert reoffending._measure_of(header) == expected

    def test_unknown_group_raises(self):
        with pytest.raises(ReoffendingDataError, match="Unrecognised population group"):
            reoffending._measure_of("Number of pensioners who reoffended")

    def test_parse_rate_suppression_and_percent(self):
        assert reoffending._parse_rate("17.3%") == 17.3
        assert math.isnan(reoffending._parse_rate("x"))

    def test_clean_strips_all_note_forms(self):
        assert reoffending._clean("Rate by age and gender [notes 1] [note 2]") == "Rate by age and gender"
        assert reoffending._clean("Disposal group\xa0") == "Disposal group"

    def test_is_tables_workbook(self):
        assert reoffending._is_tables_workbook("/f/Adult%20and%20Youth%20-%20Tables.ods")
        assert not reoffending._is_tables_workbook("/f/infographic.pdf")
        assert not reoffending._is_tables_workbook("/f/Adult%20and%20Youth%20-%20Other.ods")

    def test_header_index_skips_table_captions(self):
        assert reoffending._header_index(GOOD_RATES) == 5


class TestTidyRates:
    def test_shape_and_values(self):
        df = reoffending._tidy_rates(GOOD_RATES)
        assert df.shape == (6, 6)
        latest = df[df.cohort == "2022/23"].set_index("group")
        assert latest.loc["all", "cohort_size"] == 1100
        assert latest.loc["adult", "reoffenders"] == 160
        assert latest.loc["youth", "rate_pct"] == 27.0
        assert list(df.cohort_start.unique()) == [2021, 2022]

    def test_counts_are_nullable_integers(self):
        df = reoffending._tidy_rates(GOOD_RATES)
        assert str(df.cohort_size.dtype) == "Int64"
        assert str(df.reoffenders.dtype) == "Int64"

    def test_no_year_column_raises(self):
        rows = [row[:] for row in GOOD_RATES]
        rows[5] = ["Period" if cell == "Year" else cell for cell in RATES_HEADER]
        with pytest.raises(ReoffendingDataError, match="No 'Year' column"):
            reoffending._tidy_rates(rows)

    def test_no_cohort_rows_raises(self):
        with pytest.raises(ReoffendingDataError, match="No cohort rows"):
            reoffending._tidy_rates(GOOD_RATES[:6])


class TestTidy:
    HEADER = [
        "Age",
        "Total number who reoffended",
        "Total number in cohort",
        "Overall one-year proven reoffending rate (%)",
        "Number of males who reoffended",
        "Number of males in cohort",
        "Male one-year proven reoffending rate (%)",
    ]

    def test_suppressed_rate_becomes_nan_and_keeps_counts(self):
        df = reoffending._tidy(self.HEADER, [["18-19", "20", "40", "x", "15", "30", "x"]], ["age_band"])
        assert df.rate_pct.isna().all()
        assert set(df.reoffenders) == {20, 15}

    def test_short_rows_are_padded(self):
        df = reoffending._tidy(self.HEADER, [["18-19", "60", "100", "60.0%"]], ["age_band"])
        assert set(df.group) == {"all", "male"}
        male = df[df.group == "male"].iloc[0]
        assert pd.isna(male.reoffenders)

    def test_no_measure_columns_raises(self):
        with pytest.raises(ReoffendingDataError, match="No reoffending measure columns"):
            reoffending._tidy(["Age", "Notes"], [["18-19", "see note"]], ["age_band"])

    def test_group_missing_a_measure_raises(self):
        header = ["Age", "Total number who reoffended", "Number of males who reoffended"]
        with pytest.raises(ReoffendingDataError, match="lacks columns"):
            reoffending._tidy(header, [["18-19", "5", "3"]], ["age_band"])


class TestChecks:
    @staticmethod
    def _frame(**overrides) -> pd.DataFrame:
        row = {"group": "all", "reoffenders": 17, "cohort_size": 100, "rate_pct": 17.0}
        return pd.DataFrame([{**row, **overrides}]).astype({"reoffenders": "Int64", "cohort_size": "Int64"})

    def test_consistent_rate_passes(self):
        reoffending._check_rates(self._frame(), "test")

    def test_rate_within_rounding_passes(self):
        reoffending._check_rates(self._frame(reoffenders=173, cohort_size=1000, rate_pct=17.3), "test")

    def test_rate_disagreeing_with_counts_raises(self):
        with pytest.raises(ReoffendingValidationError, match="disagrees with its counts"):
            reoffending._check_rates(self._frame(rate_pct=25.0), "test")

    def test_rate_shown_for_tiny_cohort_raises(self):
        with pytest.raises(ReoffendingValidationError, match="under 50"):
            reoffending._check_rates(self._frame(reoffenders=10, cohort_size=40, rate_pct=25.0), "test")

    def test_suppressed_rate_is_not_checked(self):
        reoffending._check_rates(self._frame(reoffenders=10, cohort_size=40, rate_pct=float("nan")), "test")

    @staticmethod
    def _bands(total_size: int) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "age_band": ["18-24", "25-39", "Total"],
                "group": ["all"] * 3,
                "reoffenders": [10, 20, 30],
                "cohort_size": [40, 60, total_size],
                "rate_pct": [25.0, 33.3, 30.0],
            }
        )
        return frame.astype({"reoffenders": "Int64", "cohort_size": "Int64"})

    def test_totals_drop_the_total_row_when_bands_sum(self):
        df = self._bands(100)
        out = reoffending._check_totals(df, df.age_band == "Total", "test")
        assert list(out.age_band) == ["18-24", "25-39"]

    def test_totals_mismatch_raises(self):
        df = self._bands(105)
        with pytest.raises(ReoffendingValidationError, match="sums to 100, total row says 105"):
            reoffending._check_totals(df, df.age_band == "Total", "test")

    def test_missing_total_row_raises(self):
        df = self._bands(100)
        with pytest.raises(ReoffendingValidationError, match="no total row"):
            reoffending._check_totals(df, df.age_band == "nonexistent", "test")


class TestValidateRates:
    @staticmethod
    def _good() -> pd.DataFrame:
        return reoffending._tidy_rates(GOOD_RATES)

    def test_good_passes(self):
        assert reoffending.validate_reoffending_rates(self._good()) is True

    def test_empty_raises(self):
        with pytest.raises(ReoffendingValidationError, match="Empty frame"):
            reoffending.validate_reoffending_rates(self._good().iloc[0:0])

    def test_missing_columns_raise(self):
        with pytest.raises(ReoffendingValidationError, match="Missing columns"):
            reoffending.validate_reoffending_rates(self._good().drop(columns=["rate_pct"]))

    def test_unexpected_groups_raise(self):
        df = self._good()
        df.loc[df.group == "youth", "group"] = "male"
        with pytest.raises(ReoffendingValidationError, match="Unexpected groups"):
            reoffending.validate_reoffending_rates(df)

    def test_gap_in_cohorts_raises(self):
        df = self._good()
        df.loc[df.cohort_start == 2022, "cohort_start"] = 2024
        with pytest.raises(ReoffendingValidationError, match="not contiguous"):
            reoffending.validate_reoffending_rates(df)

    def test_rate_disagreeing_with_counts_raises(self):
        df = self._good()
        df.loc[(df.group == "all") & (df.cohort_start == 2022), "rate_pct"] = 40.0
        with pytest.raises(ReoffendingValidationError, match="disagrees with its counts"):
            reoffending.validate_reoffending_rates(df)

    def test_groups_exceeding_overall_by_a_tiny_overlap_pass(self):
        """The published 2010/11 cohort has adults + youths nine above the overall cohort (0.03%)."""
        rows = _rates_rows(
            ("2010/11", ["33,815", "5,646", "16.7%"], ["30,576", "4,875", "15.9%"], ["3,248", "772", "23.8%"]),
            ("2011/12", ["31,343", "5,869", "18.7%"], ["28,751", "5,116", "17.8%"], ["2,592", "753", "29.1%"]),
        )
        assert reoffending.validate_reoffending_rates(reoffending._tidy_rates(rows)) is True

    def test_groups_falling_short_of_overall_raise(self):
        rows = _rates_rows(
            ("2021/22", ["1,000", "170", "17.0%"], ["890", "142", "16.0%"], ["100", "26", "26.0%"]),
        )
        with pytest.raises(ReoffendingValidationError, match="cohort_size is not within"):
            reoffending.validate_reoffending_rates(reoffending._tidy_rates(rows))

    def test_groups_exceeding_overall_by_more_than_the_overlap_raise(self):
        rows = _rates_rows(
            ("2021/22", ["1,000", "170", "17.0%"], ["950", "152", "16.0%"], ["100", "26", "26.0%"]),
        )
        with pytest.raises(ReoffendingValidationError, match="cohort_size is not within"):
            reoffending.validate_reoffending_rates(reoffending._tidy_rates(rows))


def _make_ods(path, sheets: dict[str, list[list[str]]]) -> None:
    """Write a workbook whose cells are plain strings, as in the DoJ layout."""
    doc = OpenDocumentSpreadsheet()
    for name, rows in sheets.items():
        table = Table(name=name)
        for cells in rows:
            row = TableRow()
            for text in cells:
                cell = TableCell(valuetype="string")
                cell.addElement(P(text=text))
                row.addElement(cell)
            table.addElement(row)
        doc.spreadsheet.addElement(table)
    doc.save(str(path))


class TestReadWorkbook:
    def test_sheets_keyed_by_cleaned_lower_case_title(self, tmp_path):
        path = tmp_path / "tables.ods"
        _make_ods(
            path,
            {
                "Cover_Sheet": [["Adult and Youth Reoffending"]],
                "1": GOOD_RATES,
                "2": [["Worksheet 2: Reoffending rate by age and gender [notes 1] [note 2]"], ["x"]],
            },
        )
        sheets = reoffending.read_workbook(path)
        assert set(sheets) == {"annual reoffending rates", "reoffending rate by age and gender"}
        assert reoffending._tidy_rates(reoffending._sheet(sheets, "annual reoffending rates")).shape == (6, 6)

    def test_unreadable_workbook_raises(self, tmp_path):
        bad = tmp_path / "bad.ods"
        bad.write_text("not an ods file")
        with pytest.raises(ReoffendingDataError, match="Failed to read workbook"):
            reoffending.read_workbook(bad)

    def test_workbook_without_numbered_worksheets_raises(self, tmp_path):
        path = tmp_path / "empty.ods"
        _make_ods(path, {"Cover_Sheet": [["Just a cover"]]})
        with pytest.raises(ReoffendingDataError, match="No numbered worksheets"):
            reoffending.read_workbook(path)

    def test_missing_worksheet_names_what_is_missing(self):
        with pytest.raises(ReoffendingDataNotFoundError, match="reoffending rate by disposal"):
            reoffending._sheet({"annual reoffending rates": GOOD_RATES}, "reoffending rate by disposal")
