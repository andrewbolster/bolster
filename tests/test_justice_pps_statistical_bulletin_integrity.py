"""Integrity tests for the PPS Statistical Bulletin module.

Tests use the real bulletins published on ppsni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures. Label cleaning,
cell coercion and validation edge cases are covered by network-free unit tests.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import pps_statistical_bulletin as pps
from bolster.data_sources.justice.pps_statistical_bulletin import (
    PPSDataError,
    PPSDataNotFoundError,
    PPSValidationError,
)


@pytest.mark.network
class TestEditionDiscovery:
    """The listing page must expose annual editions with workbooks attached."""

    @pytest.fixture(scope="class")
    def editions(self):
        return pps.get_available_editions()

    def test_editions_found(self, editions):
        assert len(editions) >= 4

    def test_years_well_formed(self, editions):
        for year in editions:
            assert pd.Series([year]).str.fullmatch(r"\d{4}/\d{2}").all()

    def test_urls_absolute(self, editions):
        assert all(url.startswith("https://") for url in editions.values())

    def test_quarterly_editions_excluded(self, editions):
        """PPS moved to annual production; quarterly bulletins are out of scope."""
        assert all("quarter" not in url.lower() for url in editions.values())

    def test_recent_edition_present(self, editions):
        assert max(editions) >= "2024/25"

    def test_workbook_url_is_xlsx(self):
        assert pps.get_workbook_url().lower().endswith(".xlsx")

    def test_unknown_edition_raises(self):
        with pytest.raises(PPSDataNotFoundError):
            pps.get_workbook_url("1999/00")


@pytest.mark.network
class TestFilesReceivedIntegrity:
    """Table 1a: files arriving from police by file type and region."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pps.get_files_received()

    def test_required_columns(self, latest_data):
        assert {"financial_year", "file_type", "region", "files"}.issubset(latest_data.columns)

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_two_years_reported(self, latest_data):
        assert latest_data["financial_year"].nunique() == 2

    def test_expected_file_types(self, latest_data):
        assert {"Indictable", "Hybrid", "Summary", "All Files"} == set(latest_data["file_type"])

    def test_all_pps_present(self, latest_data):
        assert (latest_data["region"] == pps.ALL_PPS).any()

    def test_counts_non_negative(self, latest_data):
        assert (latest_data["files"].dropna() >= 0).all()

    def test_counts_are_integers(self, latest_data):
        assert latest_data["files"].dtype == "Int64"

    def test_all_files_is_the_largest_type(self, latest_data):
        """The 'All Files' subtotal must dominate each component type."""
        totals = latest_data[latest_data["region"] == pps.ALL_PPS]
        pivot = totals.pivot(index="financial_year", columns="file_type", values="files")
        for component in ("Indictable", "Hybrid", "Summary"):
            assert (pivot["All Files"] >= pivot[component]).all()

    def test_caseload_plausible_magnitude(self, latest_data):
        """PPS handles tens of thousands of files a year, not millions."""
        totals = latest_data[(latest_data["region"] == pps.ALL_PPS) & (latest_data["file_type"] == "All Files")]
        assert totals["files"].between(10_000, 200_000).all()


@pytest.mark.network
class TestFilesByOffenceIntegrity:
    """Table 1b: police files by offence classification, with shares."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pps.get_files_by_offence()

    def test_required_columns(self, latest_data):
        assert {"financial_year", "offence_classification", "files", "share_pct"}.issubset(latest_data.columns)

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_two_years_reported(self, latest_data):
        assert latest_data["financial_year"].nunique() == 2

    def test_shares_are_percentages(self, latest_data):
        assert latest_data["share_pct"].dropna().between(0, 100).all()

    def test_shares_sum_to_one_hundred(self, latest_data):
        """Every file is classified exactly once, so shares must be exhaustive."""
        for _, group in latest_data.groupby("financial_year"):
            assert group["share_pct"].sum() == pytest.approx(100, abs=1.0)

    def test_motoring_offences_covered(self, latest_data):
        """The largest single classification in every recent bulletin."""
        assert "Motoring Offences" in set(latest_data["offence_classification"])

    def test_counts_non_negative(self, latest_data):
        assert (latest_data["files"].dropna() >= 0).all()


@pytest.mark.network
class TestFilesFromAgenciesIntegrity:
    """Table 1c: files submitted by bodies other than the police."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pps.get_files_from_agencies()

    def test_required_columns(self, latest_data):
        assert {"financial_year", "agency", "files", "share_pct"}.issubset(latest_data.columns)

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_multiple_agencies(self, latest_data):
        assert latest_data["agency"].nunique() >= 3

    def test_shares_are_percentages(self, latest_data):
        assert latest_data["share_pct"].dropna().between(0, 100).all()

    def test_volume_below_police_caseload(self, latest_data):
        """Non-police referrals are a small fraction of the police caseload."""
        police = pps.get_files_received()
        police_total = police[(police["region"] == pps.ALL_PPS) & (police["file_type"] == "All Files")]["files"].max()
        assert latest_data["files"].max() < police_total


@pytest.mark.network
class TestProsecutorialDecisionsIntegrity:
    """Table 3a: decisions issued by type and region."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pps.get_prosecutorial_decisions()

    def test_required_columns(self, latest_data):
        assert {"financial_year", "decision_type", "region", "decisions"}.issubset(latest_data.columns)

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_two_years_reported(self, latest_data):
        assert latest_data["financial_year"].nunique() == 2

    def test_expected_decision_types(self, latest_data):
        expected = {
            "Indictable prosecution",
            "Summary prosecution",
            "Total Prosecution",
            "No Prosecution",
            "All Decisions Issued",
        }
        assert expected.issubset(set(latest_data["decision_type"]))

    def test_diversion_types_present(self, latest_data):
        assert {"Caution", "Informed warning", "Youth conference"}.issubset(set(latest_data["decision_type"]))

    def test_counts_non_negative(self, latest_data):
        assert (latest_data["decisions"].dropna() >= 0).all()

    def test_counts_are_integers(self, latest_data):
        assert latest_data["decisions"].dtype == "Int64"

    def test_prosecution_subtotal_consistent(self, latest_data):
        """Indictable + summary prosecutions must equal the published subtotal."""
        totals = latest_data[latest_data["region"] == pps.ALL_PPS]
        pivot = totals.pivot(index="financial_year", columns="decision_type", values="decisions")
        assert (pivot["Indictable prosecution"] + pivot["Summary prosecution"] == pivot["Total Prosecution"]).all()

    def test_prosecution_is_the_dominant_outcome(self, latest_data):
        """Most decisions issued are decisions to prosecute."""
        totals = latest_data[latest_data["region"] == pps.ALL_PPS]
        pivot = totals.pivot(index="financial_year", columns="decision_type", values="decisions")
        assert (pivot["Total Prosecution"] > pivot["No Prosecution"]).all()


@pytest.mark.network
class TestNoProsecutionReasonsIntegrity:
    """Table 3b: the two-stage test applied to no-prosecution decisions."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pps.get_no_prosecution_reasons()

    def test_required_columns(self, latest_data):
        assert {"financial_year", "reason", "region", "decisions"}.issubset(latest_data.columns)

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_both_tests_and_total_present(self, latest_data):
        reasons = set(latest_data["reason"])
        assert any("evidential" in r.lower() for r in reasons)
        assert any("public interest" in r.lower() for r in reasons)
        assert any(r.lower().startswith("all no prosecution") for r in reasons)

    def test_counts_non_negative(self, latest_data):
        assert (latest_data["decisions"].dropna() >= 0).all()

    def test_evidential_test_dominates(self, latest_data):
        """A case must pass the evidential test before public interest is weighed."""
        totals = latest_data[latest_data["region"] == pps.ALL_PPS]
        pivot = totals.pivot(index="financial_year", columns="reason", values="decisions")
        evidential = next(c for c in pivot.columns if "evidential" in c.lower())
        interest = next(c for c in pivot.columns if "public interest" in c.lower())
        assert (pivot[evidential] > pivot[interest]).all()

    def test_reasons_sum_to_total(self, latest_data):
        totals = latest_data[latest_data["region"] == pps.ALL_PPS]
        pivot = totals.pivot(index="financial_year", columns="reason", values="decisions")
        evidential = next(c for c in pivot.columns if "evidential" in c.lower())
        interest = next(c for c in pivot.columns if "public interest" in c.lower())
        total = next(c for c in pivot.columns if c.lower().startswith("all no prosecution"))
        assert (pivot[evidential] + pivot[interest] == pivot[total]).all()


@pytest.mark.network
class TestCourtOutcomesIntegrity:
    """Tables 5a and 5b: defendants dealt with, by court and outcome."""

    @pytest.fixture(scope="class")
    def crown(self):
        return pps.get_court_outcomes("crown")

    @pytest.fixture(scope="class")
    def magistrates(self):
        return pps.get_court_outcomes("magistrates")

    def test_required_columns(self, crown):
        assert {"financial_year", "outcome", "region", "defendants"}.issubset(crown.columns)

    def test_not_empty(self, crown, magistrates):
        assert not crown.empty
        assert not magistrates.empty

    def test_expected_outcomes(self, crown):
        expected = {"Convicted of at least one offence", "Acquitted", "Other", "All defendants"}
        assert expected == set(crown["outcome"])

    def test_rate_rows_excluded(self, crown, magistrates):
        """The published rate lives in get_conviction_rates(), not here."""
        assert not crown["outcome"].str.contains("rate", case=False).any()
        assert not magistrates["outcome"].str.contains("rate", case=False).any()

    def test_counts_are_integers(self, crown):
        assert crown["defendants"].dtype == "Int64"

    def test_outcomes_sum_to_total(self, crown, magistrates):
        for df in (crown, magistrates):
            totals = df[df["region"] == pps.ALL_PPS]
            pivot = totals.pivot(index="financial_year", columns="outcome", values="defendants")
            components = pivot["Convicted of at least one offence"] + pivot["Acquitted"] + pivot["Other"]
            assert (components == pivot["All defendants"]).all()

    def test_magistrates_busier_than_crown(self, crown, magistrates):
        """Summary business vastly outnumbers Crown Court trials."""
        def total(df):
            return df[(df["region"] == pps.ALL_PPS) & (df["outcome"] == "All defendants")]["defendants"].max()

        assert total(magistrates) > total(crown)

    def test_case_insensitive_court_name(self):
        assert not pps.get_court_outcomes("CROWN").empty

    def test_unknown_court_raises(self):
        with pytest.raises(ValueError, match="Unknown court"):
            pps.get_court_outcomes("supreme")


@pytest.mark.network
class TestConvictionRates:
    """The conviction rate PPS publishes alongside the outcome counts."""

    @pytest.fixture(scope="class")
    def rates(self):
        return pps.get_conviction_rates("magistrates")

    def test_required_columns(self, rates):
        assert list(rates.columns) == ["financial_year", "region", "conviction_rate_pct"]

    def test_rates_are_percentages(self, rates):
        assert rates["conviction_rate_pct"].dropna().between(0, 100).all()

    def test_headline_rate_is_high(self, rates):
        """PPS conviction rates run well above 70% in every recent year."""
        headline = rates[rates["region"] == pps.ALL_PPS]["conviction_rate_pct"].dropna()
        assert (headline > 70).all()

    def test_unknown_court_raises(self):
        with pytest.raises(ValueError, match="Unknown court"):
            pps.get_conviction_rates("coroners")


@pytest.mark.network
class TestProsecutionRateSummary:
    """Derived headline rates across the three decision groups."""

    @pytest.fixture(scope="class")
    def summary(self):
        return pps.get_prosecution_rate_summary()

    def test_required_columns(self, summary):
        expected = {
            "financial_year",
            "total_decisions",
            "prosecutions",
            "diversions",
            "no_prosecutions",
            "prosecution_rate_pct",
            "diversion_rate_pct",
            "no_prosecution_rate_pct",
        }
        assert expected == set(summary.columns)

    def test_two_years_reported(self, summary):
        assert len(summary) == 2

    def test_years_ascending(self, summary):
        assert summary["financial_year"].is_monotonic_increasing

    def test_groups_sum_to_total(self, summary):
        components = summary["prosecutions"] + summary["diversions"] + summary["no_prosecutions"]
        assert (components == summary["total_decisions"]).all()

    def test_rates_sum_to_one_hundred(self, summary):
        rates = summary["prosecution_rate_pct"] + summary["diversion_rate_pct"] + summary["no_prosecution_rate_pct"]
        assert rates.between(99, 101).all()

    def test_prosecution_rate_is_majority(self, summary):
        assert (summary["prosecution_rate_pct"] > 50).all()


@pytest.mark.network
class TestHistoricalEditions:
    """Older bulletins use the two-region model and must still parse."""

    @pytest.fixture(scope="class")
    def older(self):
        return pps.get_prosecutorial_decisions("2022/23")

    def test_older_edition_parses(self, older):
        assert not older.empty

    def test_older_edition_years(self, older):
        assert set(older["financial_year"]) == {"2021/22", "2022/23"}

    def test_two_region_model(self, older):
        """Before Autumn 2025 PPS reported Belfast/Eastern and Western/Southern."""
        regions = set(older["region"])
        assert "Belfast and Eastern" in regions
        assert "Belfast Region" not in regions

    def test_all_pps_still_present(self, older):
        assert pps.ALL_PPS in set(older["region"])


class TestLabelCleaning:
    """Unit tests for header and cell coercion - no network calls needed."""

    def test_strips_footnote_marker(self):
        assert pps._clean_label("Type of Decision 3") == "Type of Decision"

    def test_strips_multiple_footnote_markers(self):
        assert pps._clean_label("Outcome 1, 2") == "Outcome"

    def test_preserves_financial_year(self):
        """The year suffix must survive footnote stripping."""
        assert pps._clean_label("2025/26") == "2025/26"

    def test_collapses_whitespace(self):
        assert pps._clean_label("  All PPS  ") == "All PPS"

    def test_handles_missing_value(self):
        assert pps._clean_label(float("nan")) == ""

    def test_handles_none(self):
        assert pps._clean_label(None) == ""


class TestCellCoercion:
    """Unit tests for suppression handling - no network calls needed."""

    @pytest.mark.parametrize("marker", sorted(pps.SUPPRESSION_MARKERS))
    def test_suppressed_counts_become_none(self, marker):
        assert pps._safe_count(marker) is None

    def test_missing_count_becomes_none(self):
        assert pps._safe_count(float("nan")) is None

    def test_numeric_count_parsed(self):
        assert pps._safe_count(1234) == 1234

    def test_float_count_truncated_to_int(self):
        assert pps._safe_count(1234.0) == 1234

    def test_suppressed_rate_becomes_none(self):
        assert pps._safe_rate("*") is None

    def test_numeric_rate_parsed(self):
        assert pps._safe_rate(0.86) == pytest.approx(0.86)

    def test_text_rate_becomes_none(self):
        assert pps._safe_rate("not a number") is None


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def test_valid_frame_passes(self):
        frame = pd.DataFrame({"financial_year": ["2025/26"], "files": [10]})
        assert pps.validate_pps_data(frame) is True

    def test_empty_frame_raises(self):
        with pytest.raises(PPSValidationError, match="empty"):
            pps.validate_pps_data(pd.DataFrame())

    def test_missing_year_column_raises(self):
        with pytest.raises(PPSValidationError, match="financial_year"):
            pps.validate_pps_data(pd.DataFrame({"files": [10]}))

    def test_malformed_year_raises(self):
        frame = pd.DataFrame({"financial_year": ["2025"], "files": [10]})
        with pytest.raises(PPSValidationError):
            pps.validate_pps_data(frame)

    def test_negative_count_raises(self):
        frame = pd.DataFrame({"financial_year": ["2025/26"], "files": [-1]})
        with pytest.raises(PPSValidationError):
            pps.validate_pps_data(frame)

    def test_negative_decisions_raises(self):
        frame = pd.DataFrame({"financial_year": ["2025/26"], "decisions": [-5]})
        with pytest.raises(PPSValidationError):
            pps.validate_pps_data(frame)

    def test_negative_defendants_raises(self):
        frame = pd.DataFrame({"financial_year": ["2025/26"], "defendants": [-2]})
        with pytest.raises(PPSValidationError):
            pps.validate_pps_data(frame)

    def test_suppressed_values_tolerated(self):
        """Suppressed cells arrive as None and must not fail validation."""
        frame = pd.DataFrame({"financial_year": ["2025/26", "2025/26"], "files": [None, 10]})
        assert pps.validate_pps_data(frame) is True


class TestExceptionHierarchy:
    """The module exposes a three-level exception hierarchy."""

    def test_not_found_is_data_error(self):
        assert issubclass(PPSDataNotFoundError, PPSDataError)

    def test_validation_is_data_error(self):
        assert issubclass(PPSValidationError, PPSDataError)
