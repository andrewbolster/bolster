"""Data integrity tests for PSNI Police Ombudsman complaint statistics.

These tests verify:
- Data structure and required column presence
- Historical coverage (2000/01 totals, 2011/12+ breakdowns)
- District counts and LGD code mapping
- Allegation type coverage
- Validation function edge cases (no network calls)
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import police_ombudsman
from bolster.data_sources.psni._base import PSNIValidationError


# ── Annual totals ──────────────────────────────────────────────────────────────


class TestAnnualTotalsIntegrity:
    """Test data integrity for annual total complaints (T1 sheet)."""

    @pytest.fixture(scope="class")
    def totals(self):
        """Download and return the annual totals breakdown."""
        return police_ombudsman.get_latest_complaints("totals")

    def test_required_columns(self, totals):
        """DataFrame must contain year, year_label, complaints columns."""
        assert {"year", "year_label", "complaints"}.issubset(totals.columns), (
            f"Missing required columns. Got: {list(totals.columns)}"
        )

    def test_data_back_to_2000(self, totals):
        """Annual totals must cover 2000/01 (the earliest available year)."""
        assert totals["year"].min() <= 2000, (
            f"Expected data from 2000, earliest is {totals['year'].min()}"
        )

    def test_complaint_counts_positive(self, totals):
        """All complaint counts must be positive integers."""
        counts = pd.to_numeric(totals["complaints"], errors="coerce").dropna()
        assert (counts > 0).all(), "Found zero or negative complaint counts"

    def test_at_least_20_years(self, totals):
        """Must have at least 20 years of data (2000/01–2020/21 minimum)."""
        assert len(totals) >= 20, f"Expected ≥20 years, got {len(totals)}"

    def test_year_label_format(self, totals):
        """Year labels should follow the 'YYYY/YY' financial-year format."""
        import re

        pattern = re.compile(r"^\d{4}/\d{2}\*?$")
        assert totals["year_label"].apply(lambda v: bool(pattern.match(str(v)))).all()

    def test_complaint_range_plausible(self, totals):
        """Annual complaint totals should be in a plausible range (500–10000)."""
        counts = pd.to_numeric(totals["complaints"], errors="coerce").dropna()
        assert counts.max() <= 10000, f"Unrealistically high complaints: {counts.max()}"
        assert counts.min() >= 500, f"Unrealistically low complaints: {counts.min()}"

    def test_recent_year_present(self, totals):
        """Must include data up to at least 2022/23."""
        assert totals["year"].max() >= 2022, (
            f"Expected recent data, latest is {totals['year'].max()}"
        )

    def test_validation_passes(self, totals):
        """validate_complaints should pass on real totals data."""
        assert police_ombudsman.validate_complaints(totals, "totals") is True


# ── District breakdown ─────────────────────────────────────────────────────────


class TestDistrictIntegrity:
    """Test data integrity for the by-district breakdown (T8 sheet)."""

    @pytest.fixture(scope="class")
    def by_district(self):
        """Download and return the annual by-district breakdown."""
        return police_ombudsman.get_latest_complaints("by_district")

    def test_required_columns(self, by_district):
        assert {"year", "year_label", "district", "lgd_code", "complaints"}.issubset(
            by_district.columns
        )

    def test_eleven_districts(self, by_district):
        """There should be exactly 11 policing districts in the data."""
        n = by_district["district"].nunique()
        assert n == 11, f"Expected 11 districts, found {n}: {sorted(by_district['district'].unique())}"

    def test_lgd_codes_populated(self, by_district):
        """All policing-district rows must map to a valid LGD code."""
        # Filter to rows that are actual policing districts (not "Unknown" etc.)
        known = by_district[by_district["lgd_code"].notna()]
        assert len(known) > 0, "No rows with LGD codes found"
        # Every row that has a non-null district should have an LGD code
        unmapped = by_district.loc[by_district["lgd_code"].isna(), "district"].unique()
        assert len(unmapped) == 0, f"Districts without LGD codes: {unmapped}"

    def test_lgd_code_format(self, by_district):
        """LGD codes must follow the N09000XXX pattern."""
        import re

        pattern = re.compile(r"^N09000\d{3}$")
        invalid = by_district[~by_district["lgd_code"].apply(lambda v: bool(pattern.match(str(v))))][
            "lgd_code"
        ].unique()
        assert len(invalid) == 0, f"Invalid LGD codes: {invalid}"

    def test_years_from_2011(self, by_district):
        """District data starts from 2011/12."""
        assert by_district["year"].min() <= 2011, (
            f"Expected data from 2011, earliest is {by_district['year'].min()}"
        )

    def test_complaint_counts_positive(self, by_district):
        counts = pd.to_numeric(by_district["complaints"], errors="coerce").dropna()
        assert (counts > 0).all(), "Found zero or negative complaint counts by district"

    def test_belfast_highest(self, by_district):
        """Belfast City should be among the highest-complaint districts in most years."""
        recent = by_district[by_district["year"] >= 2019]
        by_d = recent.groupby("district")["complaints"].sum()
        top = by_d.idxmax()
        assert top == "Belfast City", f"Expected Belfast City to have most complaints, got {top}"

    def test_validation_passes(self, by_district):
        assert police_ombudsman.validate_complaints(by_district, "by_district") is True


# ── Allegation type breakdown ──────────────────────────────────────────────────


class TestAllegationTypeIntegrity:
    """Test data integrity for the by-allegation-type breakdown (T10 sheet)."""

    @pytest.fixture(scope="class")
    def by_allegation(self):
        """Download and return the annual by-allegation-type breakdown."""
        return police_ombudsman.get_latest_complaints("by_allegation_type")

    def test_required_columns(self, by_allegation):
        assert {"year", "allegation_type", "allegation_subtype", "allegations"}.issubset(
            by_allegation.columns
        )

    def test_multiple_allegation_types(self, by_allegation):
        """There must be at least 3 distinct allegation types."""
        n = by_allegation["allegation_type"].nunique()
        assert n >= 3, f"Expected ≥3 allegation types, found {n}"

    def test_multiple_subtypes(self, by_allegation):
        """There must be at least 10 distinct allegation subtypes."""
        n = by_allegation["allegation_subtype"].nunique()
        assert n >= 10, f"Expected ≥10 allegation subtypes, found {n}"

    def test_allegations_non_negative(self, by_allegation):
        counts = pd.to_numeric(by_allegation["allegations"], errors="coerce").dropna()
        assert (counts >= 0).all(), "Found negative allegation counts"

    def test_years_from_2011(self, by_allegation):
        assert by_allegation["year"].min() <= 2011

    def test_failure_in_duty_present(self, by_allegation):
        """'Failure in Duty' is the largest allegation category — must appear."""
        types = by_allegation["allegation_type"].str.lower().unique()
        assert any("failure" in t for t in types), (
            f"'Failure in Duty' allegation type not found. Types: {list(types)}"
        )

    def test_validation_passes(self, by_allegation):
        assert police_ombudsman.validate_complaints(by_allegation, "by_allegation_type") is True


# ── Outcome / closure breakdown ────────────────────────────────────────────────


class TestOutcomeIntegrity:
    """Test data integrity for the by-outcome breakdown (T12 sheet)."""

    @pytest.fixture(scope="class")
    def by_outcome(self):
        """Download and return the annual by-outcome breakdown."""
        return police_ombudsman.get_latest_complaints("by_outcome")

    def test_required_columns(self, by_outcome):
        assert {"year", "outcome", "closures"}.issubset(by_outcome.columns)

    def test_multiple_outcomes(self, by_outcome):
        """There should be at least 3 distinct outcome categories."""
        n = by_outcome["outcome"].nunique()
        assert n >= 3, f"Expected ≥3 outcomes, found {n}"

    def test_closures_positive(self, by_outcome):
        counts = pd.to_numeric(by_outcome["closures"], errors="coerce").dropna()
        assert (counts >= 0).all()

    def test_validation_passes(self, by_outcome):
        assert police_ombudsman.validate_complaints(by_outcome, "by_outcome") is True


# ── Quarterly breakdown ────────────────────────────────────────────────────────


class TestQuarterlyIntegrity:
    """Test data integrity for the quarterly complaints breakdown."""

    @pytest.fixture(scope="class")
    def quarterly(self):
        """Download and return quarterly complaint data."""
        return police_ombudsman.get_latest_complaints("quarterly")

    def test_required_columns(self, quarterly):
        assert {"year", "year_label", "quarter", "complaints"}.issubset(quarterly.columns)

    def test_four_quarters(self, quarterly):
        """Each financial year should have exactly 4 quarters."""
        counts = quarterly.groupby("year_label")["quarter"].count()
        assert (counts == 4).all(), f"Not all years have 4 quarters: {counts.to_dict()}"

    def test_five_years(self, quarterly):
        """Quarterly data covers 5 financial years."""
        n_years = quarterly["year"].nunique()
        assert n_years == 5, f"Expected 5 years, got {n_years}"

    def test_validation_passes(self, quarterly):
        assert police_ombudsman.validate_complaints(quarterly, "quarterly") is True


# ── Validation unit tests (no network calls) ──────────────────────────────────


class TestValidation:
    """Unit tests for validate_complaints edge cases — no network calls."""

    def test_validate_empty_dataframe(self):
        """Empty DataFrame must raise PSNIValidationError."""
        df = pd.DataFrame(columns=["year", "complaints"])
        with pytest.raises(PSNIValidationError, match="Empty"):
            police_ombudsman.validate_complaints(df, "totals")

    def test_validate_missing_columns(self):
        """DataFrame missing required columns must raise PSNIValidationError."""
        df = pd.DataFrame({"year": [2020], "wrong_col": [100]})
        with pytest.raises(PSNIValidationError, match="Missing required columns"):
            police_ombudsman.validate_complaints(df, "totals")

    def test_validate_negative_values(self):
        """DataFrame with negative complaint counts must raise PSNIValidationError."""
        df = pd.DataFrame({"year": [2020, 2021], "complaints": [-1, 3000]})
        with pytest.raises(PSNIValidationError, match="Negative"):
            police_ombudsman.validate_complaints(df, "totals")

    def test_validate_unknown_breakdown(self):
        """Unknown breakdown argument must raise PSNIValidationError."""
        df = pd.DataFrame({"year": [2020], "complaints": [100]})
        with pytest.raises(PSNIValidationError, match="Unknown breakdown"):
            police_ombudsman.validate_complaints(df, "unknown_breakdown")

    def test_validate_year_too_old(self):
        """Years before 2000 must raise PSNIValidationError."""
        df = pd.DataFrame({"year": [1990], "complaints": [1000]})
        with pytest.raises(PSNIValidationError, match="out of expected range"):
            police_ombudsman.validate_complaints(df, "totals")

    def test_validate_year_too_future(self):
        """Years past 2030 must raise PSNIValidationError."""
        df = pd.DataFrame({"year": [2035], "complaints": [1000]})
        with pytest.raises(PSNIValidationError, match="out of expected range"):
            police_ombudsman.validate_complaints(df, "totals")

    def test_validate_totals_valid(self):
        """Valid totals DataFrame must return True."""
        df = pd.DataFrame({"year": [2020, 2021, 2022], "complaints": [3000, 3100, 2900]})
        assert police_ombudsman.validate_complaints(df, "totals") is True

    def test_validate_by_district_valid(self):
        """Valid by_district DataFrame must return True."""
        df = pd.DataFrame(
            {
                "year": [2020, 2021],
                "district": ["Belfast City", "Mid Ulster"],
                "complaints": [800, 130],
            }
        )
        assert police_ombudsman.validate_complaints(df, "by_district") is True

    def test_validate_by_allegation_type_valid(self):
        """Valid by_allegation_type DataFrame must return True."""
        df = pd.DataFrame(
            {
                "year": [2020],
                "allegation_type": ["Failure in Duty"],
                "allegations": [1500],
            }
        )
        assert police_ombudsman.validate_complaints(df, "by_allegation_type") is True

    def test_validate_by_outcome_valid(self):
        """Valid by_outcome DataFrame must return True."""
        df = pd.DataFrame(
            {
                "year": [2020],
                "outcome": ["Total complaints closed"],
                "closures": [3200],
            }
        )
        assert police_ombudsman.validate_complaints(df, "by_outcome") is True

    def test_validate_quarterly_valid(self):
        """Valid quarterly DataFrame must return True."""
        df = pd.DataFrame(
            {
                "year": [2020, 2020],
                "quarter": ["Quarter 1 (April to June)", "Quarter 2 (July to September)"],
                "complaints": [700, 750],
            }
        )
        assert police_ombudsman.validate_complaints(df, "quarterly") is True

    def test_get_latest_complaints_invalid_breakdown(self):
        """get_latest_complaints with unknown breakdown must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid breakdown"):
            police_ombudsman.get_latest_complaints("bad_breakdown")

    def test_parse_fy_label(self):
        """_parse_fy_label extracts the start year correctly."""
        assert police_ombudsman._parse_fy_label("2024/25") == 2024
        assert police_ombudsman._parse_fy_label("2000/01*") == 2000
        assert police_ombudsman._parse_fy_label("2011/12") == 2011

    def test_normalise_annual_district_known(self):
        """Known district labels should map to canonical LGD names."""
        assert police_ombudsman._normalise_annual_district("A - Belfast City") == "Belfast City"
        assert police_ombudsman._normalise_annual_district("B - Lisburn & Castlereagh City") == (
            "Lisburn & Castlereagh City"
        )

    def test_normalise_annual_district_unknown(self):
        """Unknown district labels should be returned unchanged."""
        assert police_ombudsman._normalise_annual_district("Z - Unknown District") == (
            "Z - Unknown District"
        )

    def test_normalise_quarterly_district_known(self):
        """Known quarterly district labels should map to canonical LGD names."""
        assert police_ombudsman._normalise_quarterly_district("District A - Belfast City") == (
            "Belfast City"
        )

    def test_normalise_quarterly_district_unknown(self):
        """Unknown quarterly labels return unchanged."""
        assert police_ombudsman._normalise_quarterly_district("Unknown Area") == "Unknown Area"
