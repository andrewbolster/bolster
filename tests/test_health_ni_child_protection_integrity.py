"""Data integrity tests for NISRA Children's Social Care — Child Protection module.

These tests validate that the child protection data is internally consistent and
covers the expected temporal range.  They use real data (no mocks) with a
``scope="class"`` fixture so the network fetch happens once per class.

Key validations:
- Required columns present with correct dtypes
- Non-negative values throughout
- Historical coverage from 2013/14 (referrals) and 2015 (CPR trend)
- Known measures present in the output
- Validation helper raises on bad input
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import child_protection as cp
from bolster.data_sources.health_ni._base import NISRAValidationError


class TestChildProtectionIntegrity:
    """Integration tests for the child protection module using real downloaded data."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        """Download the latest child protection data once for all tests in this class."""
        return cp.get_latest_child_protection()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        """All required columns must be present."""
        assert cp.REQUIRED_COLUMNS.issubset(set(latest_data.columns)), (
            f"Missing columns: {cp.REQUIRED_COLUMNS - set(latest_data.columns)}"
        )

    def test_dataframe_not_empty(self, latest_data: pd.DataFrame) -> None:
        """Dataset must contain records."""
        assert len(latest_data) > 0

    def test_year_dtype_is_integer(self, latest_data: pd.DataFrame) -> None:
        """Year column must be integer-compatible (Int64 nullable int)."""
        assert pd.api.types.is_integer_dtype(latest_data["year"]), f"year column has dtype {latest_data['year'].dtype}"

    def test_value_dtype_is_integer(self, latest_data: pd.DataFrame) -> None:
        """Value column must be integer-compatible."""
        assert pd.api.types.is_integer_dtype(latest_data["value"]), (
            f"value column has dtype {latest_data['value'].dtype}"
        )

    def test_no_negative_values(self, latest_data: pd.DataFrame) -> None:
        """Count values must never be negative."""
        non_null = latest_data["value"].dropna()
        assert (non_null >= 0).all(), "Found negative value(s) in the data"

    def test_known_measures_present(self, latest_data: pd.DataFrame) -> None:
        """Expected measure codes must be present in the output."""
        expected = {
            cp.MEASURE_CPR_TOTAL,
            cp.MEASURE_REFERRALS_TOTAL,
            cp.MEASURE_INVESTIGATIONS_TOTAL,
            "cpr_registrations_trust_snapshot",
            "referrals_by_trust",
            "investigations_by_trust",
            "cpr_by_abuse_category",
        }
        actual = set(latest_data["measure"].unique())
        missing = expected - actual
        assert not missing, f"Missing measures: {missing}"

    def test_historical_coverage_referrals(self, latest_data: pd.DataFrame) -> None:
        """Referrals data must go back to at least financial year 2013/14 (year=2014)."""
        ref = latest_data[latest_data["measure"] == cp.MEASURE_REFERRALS_TOTAL]
        min_year = ref["year"].min()
        assert min_year <= 2014, f"Expected referrals from 2014 (FY 2013/14), earliest is {min_year}"

    def test_historical_coverage_cpr_trend(self, latest_data: pd.DataFrame) -> None:
        """CPR trust snapshot trend must cover from 2015 to present."""
        cpr = latest_data[latest_data["measure"] == "cpr_registrations_trust_snapshot"]
        min_year = cpr["year"].min()
        max_year = cpr["year"].max()
        assert min_year <= 2015, f"Expected CPR data from 2015, earliest is {min_year}"
        assert max_year >= 2024, f"Expected CPR data to 2024+, latest is {max_year}"

    def test_all_five_trusts_in_cpr_trend(self, latest_data: pd.DataFrame) -> None:
        """All five HSC Trusts must appear in the CPR trend data."""
        cpr = latest_data[latest_data["measure"] == "cpr_registrations_trust_snapshot"]
        present = set(cpr["subcategory"].unique())
        expected = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}
        assert expected.issubset(present), f"Missing trusts: {expected - present}"

    def test_cpr_ni_total_snapshot_present(self, latest_data: pd.DataFrame) -> None:
        """Latest-year NI total CPR snapshot must be present."""
        snap = latest_data[latest_data["measure"] == cp.MEASURE_CPR_TOTAL]
        assert len(snap) >= 1, "No CPR NI total snapshot found"
        assert (snap["value"].dropna() > 0).all(), "CPR NI total must be positive"

    def test_abuse_categories_present(self, latest_data: pd.DataFrame) -> None:
        """Key abuse categories must be present in the data."""
        abuse = latest_data[latest_data["measure"] == "cpr_by_abuse_category"]
        cats = set(abuse["subcategory"].unique())
        expected_partial = {"Neglect (Only)", "Physical Abuse (Only)", "Sexual Abuse (Only)"}
        assert expected_partial.issubset(cats), f"Missing abuse categories: {expected_partial - cats}"

    def test_investigations_cover_multiple_years(self, latest_data: pd.DataFrame) -> None:
        """Investigation totals must span at least 5 years."""
        inv = latest_data[latest_data["measure"] == cp.MEASURE_INVESTIGATIONS_TOTAL]
        n_years = inv["year"].nunique()
        assert n_years >= 5, f"Expected 5+ years of investigation data, got {n_years}"

    def test_referrals_plausible_magnitude(self, latest_data: pd.DataFrame) -> None:
        """NI-wide annual referrals should be between 500 and 10,000."""
        ref = latest_data[latest_data["measure"] == cp.MEASURE_REFERRALS_TOTAL]
        vals = ref["value"].dropna()
        assert (vals >= 500).all(), f"Unusually low referral count: {vals.min()}"
        assert (vals <= 10_000).all(), f"Unusually high referral count: {vals.max()}"

    def test_validation_passes_on_real_data(self, latest_data: pd.DataFrame) -> None:
        """validate_child_protection_data must return the same DataFrame unchanged."""
        result = cp.validate_child_protection_data(latest_data)
        assert result is latest_data

    def test_cpr_ni_total_covers_full_trend(self, latest_data: pd.DataFrame) -> None:
        """NI total must span the same years as the trust trend, not just the snapshot year."""
        total = latest_data[latest_data["measure"] == cp.MEASURE_CPR_TOTAL]
        assert total["year"].min() <= 2015, f"NI total starts at {total['year'].min()}, expected 2015 or earlier"
        assert total["year"].max() >= 2024, f"NI total ends at {total['year'].max()}, expected 2024 or later"

    def test_ni_total_not_folded_into_northern_trust(self, latest_data: pd.DataFrame) -> None:
        """Each trust must have exactly one CPR value per year.

        "Northern Ireland" contains "Northern", so a naive substring match folds the
        NI-wide total into the Northern HSC Trust and silently doubles its series.
        """
        cpr = latest_data[latest_data["measure"] == "cpr_registrations_trust_snapshot"]
        counts = cpr.groupby(["year", "subcategory"]).size()
        assert (counts == 1).all(), f"Duplicate trust-year rows: {counts[counts > 1].to_dict()}"
        assert "Northern Ireland" not in set(cpr["subcategory"]), "NI total leaked into the trust breakdown"

    def test_trusts_sum_to_ni_total(self, latest_data: pd.DataFrame) -> None:
        """CPR trust values must sum to the NI-wide total for each shared year."""
        trusts = latest_data[latest_data["measure"] == "cpr_registrations_trust_snapshot"]
        totals = latest_data[latest_data["measure"] == cp.MEASURE_CPR_TOTAL].set_index("year")["value"]
        summed = trusts.groupby("year")["value"].sum()
        shared = summed.index.intersection(totals.index)
        assert len(shared) >= 5, f"Only {len(shared)} years overlap between trust and NI total series"
        for year in shared:
            assert summed[year] == totals[year], f"{year}: trusts sum to {summed[year]}, NI total is {totals[year]}"

    def test_combined_abuse_categories_kept_distinct(self, latest_data: pd.DataFrame) -> None:
        """Combined categories split by "Main Category of Abuse" must not collapse together."""
        abuse = latest_data[latest_data["measure"] == "cpr_by_abuse_category"]
        cats = set(abuse["subcategory"].unique())
        expected = {
            "Neglect and Physical Abuse (main: Neglect)",
            "Neglect and Physical Abuse (main: Physical Abuse)",
        }
        assert expected.issubset(cats), f"Combined categories collapsed: {expected - cats}"

    def test_abuse_categories_sum_to_ni_total(self, latest_data: pd.DataFrame) -> None:
        """Abuse category counts must sum to the NI-wide CPR total for each year.

        This cross-checks table 2.5a against table 2.2a — a dropped or collapsed
        category row shows up here as a shortfall.
        """
        summed = latest_data[latest_data["measure"] == "cpr_by_abuse_category"].groupby("year")["value"].sum()
        totals = latest_data[latest_data["measure"] == cp.MEASURE_CPR_TOTAL].set_index("year")["value"]
        shared = summed.index.intersection(totals.index)
        assert len(shared) >= 5, f"Only {len(shared)} years overlap between category and NI total series"
        for year in shared:
            assert summed[year] == totals[year], (
                f"{year}: abuse categories sum to {summed[year]}, NI total is {totals[year]}"
            )

    def test_no_duplicate_records(self, latest_data: pd.DataFrame) -> None:
        """Tables 2.1 and 2.2a both report the NI total; duplicates must be collapsed."""
        dupes = latest_data.duplicated(subset=["year", "measure", "category", "subcategory"])
        assert not dupes.any(), f"Duplicate records:\n{latest_data[dupes].to_string()}"


class TestTrustNormalisation:
    """Unit tests for trust-name normalisation — no network calls required."""

    def test_northern_ireland_is_not_a_trust(self) -> None:
        """The NI-wide label must never normalise to the Northern HSC Trust."""
        assert cp._is_ni_total("Northern Ireland")
        assert cp._normalise_trust("Northern Ireland") == "Northern Ireland"

    def test_northern_trust_still_normalises(self) -> None:
        """The Northern HSC Trust must still resolve to its short form."""
        assert not cp._is_ni_total("Northern HSC Trust")
        assert cp._normalise_trust("Northern HSC Trust") == "Northern"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Belfast HSC Trust", "Belfast"),
            ("South Eastern HSC Trust", "South Eastern"),
            ("Southern HSC Trust", "Southern"),
            ("Western HSC Trust", "Western"),
        ],
    )
    def test_known_trusts(self, raw: str, expected: str) -> None:
        """Each HSC Trust must normalise to its canonical short form."""
        assert cp._normalise_trust(raw) == expected


class TestValidation:
    """Unit tests for validate_child_protection_data — no network calls required."""

    def test_empty_dataframe_raises(self) -> None:
        """Validation must raise NISRAValidationError on empty DataFrame."""
        with pytest.raises(NISRAValidationError, match="empty"):
            cp.validate_child_protection_data(pd.DataFrame())

    def test_none_raises(self) -> None:
        """Validation must raise NISRAValidationError when passed None."""
        with pytest.raises(NISRAValidationError):
            cp.validate_child_protection_data(None)  # type: ignore[arg-type]

    def test_missing_columns_raises(self) -> None:
        """Validation must raise NISRAValidationError when required columns are missing."""
        incomplete = pd.DataFrame({"year": [2025], "value": [100]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            cp.validate_child_protection_data(incomplete)

    def test_negative_values_raises(self) -> None:
        """Validation must raise NISRAValidationError when value column has negatives."""
        bad = pd.DataFrame(
            {
                "year": [2025],
                "measure": ["cpr_registrations_ni_total"],
                "category": ["ni_total"],
                "subcategory": ["Northern Ireland"],
                "value": [-1],
                "notes": ["test"],
            }
        )
        with pytest.raises(NISRAValidationError, match="negative"):
            cp.validate_child_protection_data(bad)

    def test_valid_minimal_dataframe_passes(self) -> None:
        """Validation must return the DataFrame when all checks pass."""
        good = pd.DataFrame(
            {
                "year": [2025],
                "measure": ["cpr_registrations_ni_total"],
                "category": ["ni_total"],
                "subcategory": ["Northern Ireland"],
                "value": [2283],
                "notes": ["Snapshot at 31 March 2025"],
            }
        )
        result = cp.validate_child_protection_data(good)
        assert result is good
