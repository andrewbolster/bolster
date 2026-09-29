"""Data integrity tests for FE Outcomes (DfE, NISRA datavis report).

Runs against the live publication; each figure embeds a real .xlsx file.
"""

import pandas as pd
import pytest

from bolster.data_sources.dfe import further_education_outcomes as feo
from bolster.data_sources.dfe._base import DfEDataNotFoundError, DfEValidationError
from bolster.utils.datavis import DatavisTable

LGDS = {
    "Belfast City",
    "Antrim and Newtownabbey",
    "Armagh City, Banbridge and Craigavon",
    "Derry City and Strabane",
    "Newry, Mourne and Down",
    "Mid Ulster",
    "Ards and North Down",
    "Fermanagh and Omagh",
    "Causeway Coast and Glens",
    "Lisburn and Castlereagh",
    "Mid and East Antrim",
}


class TestReport:
    def test_url_is_the_report_not_the_dashboard(self):
        url = feo.get_latest_publication_url()
        assert url.startswith("https://datavis.nisra.gov.uk/economy/Further-Education-Outcomes-")
        assert "dashboard" not in url.lower()
        assert "methodology" not in url.lower()

    def test_report_embeds_three_figures(self):
        tables = feo.get_tables()
        assert len(tables) >= 3
        assert not [label for label, t in tables.items() if t.data.empty]


class TestLeaverOutcomes:
    @pytest.fixture(scope="class")
    def df(self):
        return feo.get_leaver_outcomes()

    def test_shape(self, df):
        assert list(df.columns) == ["outcome", "pct", "academic_year"]
        assert set(df["outcome"]) == {"employed", "learning", "unemployed", "other"}
        assert df["academic_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_sums_to_about_100(self, df):
        assert 97 <= df["pct"].sum() <= 103

    def test_most_leavers_are_employed_or_learning(self, df):
        share = df.set_index("outcome")["pct"]
        assert share["employed"] + share["learning"] > 70
        assert share["unemployed"] < 20

    def test_validates(self, df):
        assert feo.validate_data(df) is True


class TestWorkingByLGD:
    @pytest.fixture(scope="class")
    def df(self):
        return feo.get_leavers_working_by_lgd()

    def test_covers_every_lgd(self, df):
        assert set(df["lgd"]) >= LGDS

    def test_percentages(self, df):
        assert df["pct"].between(0, 100).all()
        assert 95 <= df["pct"].sum() <= 105

    def test_belfast_is_largest(self, df):
        assert df.loc[df["pct"].idxmax(), "lgd"] == "Belfast City"


class TestWorkQuality:
    def test_indicators(self):
        df = feo.get_work_quality_indicators()
        assert list(df.columns) == ["indicator", "pct", "academic_year"]
        assert len(df) >= 3
        assert df["pct"].between(0, 100).all()
        assert df["indicator"].str.contains("permanent", case=False).any()


class TestHelpers:
    """Unit tests for parsing, lookup and validation edge cases - no network calls needed."""

    def test_school_year_slug(self):
        assert feo._school_year_slug(2024) == "202425"
        assert feo._school_year_slug(1999) == "199900"

    @pytest.mark.parametrize(
        ("text", "href", "expected"),
        [
            (
                "FE Outcomes report 2024/25 - NISRA website",
                "https://datavis.nisra.gov.uk/economy/Further-Education-Outcomes-2024-25.html",
                True,
            ),
            (
                "The FE Outcomes Dashboard - NISRA website",
                "https://datavis.nisra.gov.uk/economy/Further-Education-Outcomes-Dashboard-2024-25.html",
                False,
            ),
            (
                "Methodology",
                "https://datavis.nisra.gov.uk/economy/Further-Education-Outcomes-Methodology-2024-25.html",
                False,
            ),
            ("Something else", "https://www.economy-ni.gov.uk/x", False),
        ],
    )
    def test_is_report_link(self, text, href, expected):
        assert feo._is_report_link(text, href) is expected

    def test_academic_year_from_url(self):
        assert feo._academic_year("https://x/Further-Education-Outcomes-2024-25.html") == "2024/25"
        with pytest.raises(DfEValidationError):
            feo._academic_year("https://x/no-year.html")

    def test_find_table_missing_raises(self):
        tables = {"Figure 1": DatavisTable("Figure 1", "Figure 1: Something", pd.DataFrame({"a": [1]}))}
        with pytest.raises(DfEDataNotFoundError):
            feo._find_table(tables, "work quality")

    @staticmethod
    def _valid():
        return pd.DataFrame(
            {
                "outcome": ["employed", "learning", "unemployed", "other"],
                "pct": [57.0, 33.0, 5.0, 4.0],
                "academic_year": ["2024/25"] * 4,
            }
        )

    def test_validate_accepts_rounded_sum(self):
        assert feo.validate_data(self._valid()) is True

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            (lambda df: df.drop(columns=["pct"]), "Missing expected columns"),
            (lambda df: df[df["outcome"] != "other"], "Missing outcomes"),
            (lambda df: df.assign(pct=[57.0, 33.0, None, 4.0]), "within 0-100"),
            (lambda df: df.assign(pct=[157.0, 33.0, 5.0, 4.0]), "within 0-100"),
            (lambda df: df.assign(pct=[50.0, 20.0, 5.0, 4.0]), "sum"),
        ],
    )
    def test_validate_rejects_bad_frames(self, mutate, message):
        with pytest.raises(DfEValidationError, match=message):
            feo.validate_data(mutate(self._valid()))
