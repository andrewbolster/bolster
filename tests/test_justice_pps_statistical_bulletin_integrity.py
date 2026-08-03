"""Integrity tests for the PPS Statistical Bulletin module.

Tests use real workbooks downloaded from ppsni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures and cached for
the duration of the test session. Parsing and validation edge cases are
covered by network-free unit tests.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import pps_statistical_bulletin as pps
from bolster.data_sources.justice.pps_statistical_bulletin import (
    PPSDataNotFoundError,
    PPSValidationError,
)

# The oldest bulletin published with machine-readable tables; everything
# earlier is PDF-only.
OLDEST_XLSX_PUBLICATION = "https://www.ppsni.gov.uk/node/208"


class TestPublicationDiscovery:
    """Discovery of bulletins from the PPS publication listing page."""

    @pytest.fixture(scope="class")
    def publications(self):
        return pps.list_publications()

    def test_publications_found(self, publications):
        assert len(publications) >= 20

    def test_required_keys(self, publications):
        expected = {"title", "url", "financial_year", "year", "quarters"}
        assert all(expected.issubset(p) for p in publications)

    def test_financial_year_format(self, publications):
        assert all(pps._FINANCIAL_YEAR_RE.fullmatch(p["financial_year"]) for p in publications)

    def test_year_matches_financial_year(self, publications):
        assert all(p["year"] == int(p["financial_year"][:4]) for p in publications)

    def test_years_plausible(self, publications):
        assert all(2012 <= p["year"] <= 2100 for p in publications)

    def test_sorted_newest_first(self, publications):
        keys = [(p["year"], p["quarters"] or "zzz") for p in publications]
        assert keys == sorted(keys, reverse=True)

    def test_urls_unique(self, publications):
        urls = [p["url"] for p in publications]
        assert len(urls) == len(set(urls))

    def test_urls_absolute(self, publications):
        assert all(p["url"].startswith("https://") for p in publications)

    def test_latest_is_recent(self, publications):
        """The most recent bulletin should be no more than ~2 years stale."""
        assert publications[0]["year"] >= 2024

    def test_annual_bulletins_exist(self, publications):
        """Annual bulletins carry no quarter qualifier."""
        assert any(p["quarters"] is None for p in publications)

    def test_quarterly_bulletins_exist(self, publications):
        assert any(p["quarters"] is not None for p in publications)

    def test_bad_base_url_raises(self):
        with pytest.raises(PPSDataNotFoundError):
            pps.list_publications("https://www.ppsni.gov.uk/this-page-does-not-exist")


class TestLatestBulletinIntegrity:
    """Integrity of the most recent annual bulletin."""

    @pytest.fixture(scope="class")
    def latest(self):
        return pps.get_latest_data()

    def test_required_columns(self, latest):
        expected = {
            "table",
            "title",
            "financial_year",
            "year",
            "dimension",
            "category",
            "breakdown",
            "value",
            "marker",
        }
        assert expected.issubset(set(latest.columns))

    def test_not_empty(self, latest):
        assert len(latest) > 500

    def test_core_tables_present(self, latest):
        """Files received, decisions, timeliness and court outcomes."""
        assert {"1a", "3a", "3c", "5a"}.issubset(set(latest["table"]))

    def test_every_table_has_data(self, latest):
        assert (latest.groupby("table")["value"].count() > 3).all()

    def test_year_dtype_integer(self, latest):
        assert pd.api.types.is_integer_dtype(latest["year"])

    def test_year_matches_financial_year(self, latest):
        assert (latest["financial_year"].str[:4].astype(int) == latest["year"]).all()

    def test_financial_year_format(self, latest):
        assert latest["financial_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_recent_coverage(self, latest):
        assert latest["year"].max() >= 2024

    def test_labels_always_present(self, latest):
        assert latest["category"].notna().all()
        assert latest["breakdown"].notna().all()

    def test_labels_stripped(self, latest):
        for column in ("category", "breakdown"):
            assert (latest[column] == latest[column].str.strip()).all()

    def test_footnote_digits_stripped(self, latest):
        """Footnote references are glued to labels in the source workbooks."""
        assert not latest["category"].str.fullmatch(r".*[a-zA-Z]\d+").any()

    def test_values_non_negative(self, latest):
        assert (latest["value"].dropna() >= 0).all()

    def test_values_mostly_populated(self, latest):
        """Suppressed cells exist but should be a small minority."""
        assert latest["value"].isna().mean() < 0.10

    def test_every_missing_value_is_suppressed(self, latest):
        """A NaN value must come from a suppression marker, not a parse failure."""
        assert latest.loc[latest["value"].isna(), "marker"].notna().all()

    def test_markers_recognised(self, latest):
        markers = set(latest["marker"].dropna())
        assert markers <= pps._SUPPRESSION_MARKERS

    def test_all_pps_totals_present(self, latest):
        """Region-broken tables always carry an ``All PPS`` total column."""
        assert (latest["breakdown"] == "All PPS").any()

    def test_no_derived_change_columns(self, latest):
        """Change and % change columns are computable, so they are dropped."""
        assert not latest["breakdown"].str.contains("change", case=False).any()

    def test_no_duplicate_observations(self, latest):
        keys = ["table", "financial_year", "dimension", "category", "breakdown"]
        assert not latest.duplicated(subset=keys).any()

    def test_validate_passes(self, latest):
        assert pps.validate_data(latest) is True

    def test_table_filter(self, latest):
        subset = pps.get_latest_data(table="1a")
        assert set(subset["table"]) == {"1a"}
        assert len(subset) == len(latest[latest["table"] == "1a"])

    def test_unknown_table_raises(self):
        with pytest.raises(PPSDataNotFoundError, match="Unknown table"):
            pps.get_latest_data(table="99z")

    def test_list_tables(self, latest):
        assert set(pps.list_tables()) == set(latest["table"])


class TestAccessors:
    """Convenience accessors for the headline tables."""

    def test_files_received(self):
        df = pps.get_files_received()
        assert set(df["table"]) == {"1a"}
        assert df.index[0] == 0

    def test_files_received_volume_plausible(self):
        """PPS receives roughly 30,000-60,000 files a year."""
        df = pps.get_files_received()
        totals = df[(df["category"] == "All Files") & (df["breakdown"] == "All PPS")]
        assert totals["value"].between(20000, 80000).all()

    def test_decisions(self):
        df = pps.get_decisions()
        assert set(df["table"]) == {"3a"}

    def test_timeliness_reports_days(self):
        """Table 3c is measured in days, not counts."""
        df = pps.get_timeliness()
        assert set(df["table"]) == {"3c"}
        assert df["value"].max() < 2000

    def test_court_outcomes(self):
        df = pps.get_court_outcomes()
        assert set(df["table"]) == {"5a"}

    def test_conviction_rate_is_a_fraction(self):
        """Rate rows are stored as fractions, not percentages."""
        df = pps.get_court_outcomes()
        rates = df[df["category"].str.contains("Conviction Rate", case=False)]
        assert not rates.empty
        assert rates["value"].between(0, 1).all()


class TestOldestMachineReadableBulletin:
    """The 2017/18 workbook uses an older layout with a two-row header."""

    @pytest.fixture(scope="class")
    def oldest(self):
        path = pps.download_file(pps.find_publication_xlsx(OLDEST_XLSX_PUBLICATION))
        return pps.parse_data(path)

    def test_not_empty(self, oldest):
        assert len(oldest) > 200

    def test_covers_2017_18(self, oldest):
        assert "2017/18" in set(oldest["financial_year"])

    def test_includes_prior_year_comparison(self, oldest):
        assert "2016/17" in set(oldest["financial_year"])

    def test_period_columns_split_by_year(self, oldest):
        """``Q1-4 2017/18`` headers become the year, not the breakdown."""
        comparison = oldest[oldest["table"] == "1b"]
        assert set(comparison["breakdown"]) == {"Number", "% Share"}
        assert set(comparison["financial_year"]) == {"2016/17", "2017/18"}

    def test_units_row_resolved_to_region(self, oldest):
        """The header row reads ``Number``; real labels sit one row above."""
        files = oldest[oldest["table"] == "1a"]
        assert "All PPS" in set(files["breakdown"])
        assert not files["breakdown"].str.fullmatch("Number").any()

    def test_older_region_names(self, oldest):
        """PPS reorganised its regions, so old names must survive parsing."""
        assert "Belfast and Eastern" in set(oldest["breakdown"])

    def test_percent_change_footers_excluded(self, oldest):
        assert not oldest["category"].str.contains("% Change", case=False).any()

    def test_validate_passes(self, oldest):
        assert pps.validate_data(oldest) is True


class TestHistoricalSeries:
    """Stitching several annual bulletins into one series."""

    @pytest.fixture(scope="class")
    def historical(self):
        return pps.get_historical_data(max_publications=3)

    def test_not_empty(self, historical):
        assert len(historical) > 1000

    def test_multiple_years(self, historical):
        assert historical["year"].nunique() >= 3

    def test_years_contiguous(self, historical):
        years = sorted(historical["year"].unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_no_duplicate_observations(self, historical):
        keys = ["table", "financial_year", "category", "breakdown"]
        assert not historical.duplicated(subset=keys).any()

    def test_sorted_by_year(self, historical):
        assert historical["year"].is_monotonic_increasing

    def test_validate_passes(self, historical):
        assert pps.validate_data(historical) is True

    def test_files_received_trend_plausible(self, historical):
        """Annual file receipts should stay within a stable band."""
        totals = historical[
            (historical["table"] == "1a") & (historical["category"] == "All Files") & (historical["breakdown"] == "All PPS")
        ]
        assert totals["value"].between(20000, 80000).all()


class TestLabelParsing:
    """Network-free unit tests for label normalisation."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Type of Decision 3  ", "Type of Decision"),
            ("Unknown/Not Applicable1,3", "Unknown/Not Applicable"),
            ("  All   PPS ", "All PPS"),
            ("18-25", "18-25"),
            ("76 over", "76 over"),
            ("2025/26", "2025/26"),
            ("", ""),
        ],
    )
    def test_clean_label(self, raw, expected):
        assert pps._clean_label(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2025/26", "2025/26"),
            ("Q1-4 2017/18", "2017/18"),
            ("2024 / 25 1", "2024/25"),
            ("Financial Year", None),
            ("", None),
        ],
    )
    def test_parse_financial_year(self, raw, expected):
        assert pps._parse_financial_year(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2025/26 (% Share)", ("2025/26", "% Share")),
            ("Q1-4 2017/18", ("2017/18", "Number")),
            ("2024/25 (Number)", ("2024/25", "Number")),
            ("Belfast Region", (None, "Belfast Region")),
            ("% Share", (None, "% Share")),
        ],
    )
    def test_split_year_measure(self, raw, expected):
        assert pps._split_year_measure(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "is_footer"),
        [
            ("% Change (2024/25 to 2025/26)", True),
            ("Contents", True),
            ("Source: PPS", True),
            ("All Files", False),
            ("", False),
        ],
    )
    def test_is_footer(self, raw, is_footer):
        assert pps._is_footer(raw) is is_footer


class TestValueParsing:
    """Network-free unit tests for cell value coercion."""

    def test_plain_integer(self):
        assert pps._parse_value("1234") == (1234.0, None)

    def test_thousands_separator(self):
        assert pps._parse_value("41,571") == (41571.0, None)

    def test_fraction(self):
        value, marker = pps._parse_value("0.362")
        assert marker is None
        assert value == pytest.approx(0.362)

    @pytest.mark.parametrize("marker", ["*", "-", "#"])
    def test_suppression_markers(self, marker):
        value, parsed = pps._parse_value(marker)
        assert pd.isna(value)
        assert parsed == marker

    def test_blank(self):
        value, marker = pps._parse_value("")
        assert pd.isna(value)
        assert marker is None

    def test_unparseable_text(self):
        value, marker = pps._parse_value("not a number")
        assert pd.isna(value)
        assert marker is None


class TestValidation:
    """Network-free unit tests for ``validate_data``."""

    @pytest.fixture
    def valid(self):
        return pd.DataFrame(
            {
                "table": ["1a"] * 3,
                "title": ["Table 1a"] * 3,
                "financial_year": ["2025/26"] * 3,
                "year": [2025] * 3,
                "dimension": ["File Type"] * 3,
                "category": ["Indictable", "Hybrid", "Summary"],
                "breakdown": ["All PPS"] * 3,
                "value": [1.0, 2.0, 3.0],
                "marker": [None] * 3,
            }
        )

    def test_valid_frame_passes(self, valid):
        assert pps.validate_data(valid, min_records=3) is True

    def test_empty_frame_rejected(self):
        with pytest.raises(PPSValidationError, match="empty"):
            pps.validate_data(pd.DataFrame())

    def test_missing_column_rejected(self, valid):
        with pytest.raises(PPSValidationError, match="column"):
            pps.validate_data(valid.drop(columns=["breakdown"]), min_records=3)

    def test_too_few_records_rejected(self, valid):
        with pytest.raises(PPSValidationError, match="records"):
            pps.validate_data(valid, min_records=100)

    def test_implausible_year_rejected(self, valid):
        valid.loc[0, "year"] = 1899
        with pytest.raises(PPSValidationError, match="Year range"):
            pps.validate_data(valid, min_records=3)

    def test_malformed_financial_year_rejected(self, valid):
        valid.loc[0, "financial_year"] = "2025-2026"
        with pytest.raises(PPSValidationError, match="Malformed financial years"):
            pps.validate_data(valid, min_records=3)

    def test_negative_value_rejected(self, valid):
        valid.loc[0, "value"] = -1.0
        with pytest.raises(PPSValidationError, match="[Nn]egative"):
            pps.validate_data(valid, min_records=3)


class TestErrorHandling:
    """Failure modes that do not need a successful download."""

    def test_missing_xlsx_raises(self):
        with pytest.raises(PPSDataNotFoundError):
            pps.find_publication_xlsx("https://www.ppsni.gov.uk/this-page-does-not-exist")

    def test_parse_missing_file_raises(self, tmp_path):
        with pytest.raises(PPSDataNotFoundError):
            pps.parse_data(tmp_path / "absent.xlsx")
