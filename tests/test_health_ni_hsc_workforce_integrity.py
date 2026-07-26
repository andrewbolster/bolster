"""Data integrity tests for the NI HSC Workforce Statistics module.

These tests validate that the workforce data is internally consistent across
the several differently-shaped tables flattened out of each quarterly
workbook.  They use real data (no mocks) with a ``scope="class"`` fixture so
the network fetch happens once per class.

Key validations:
- Required columns present, with the expected dtypes
- Every published quarter contributes a six-year series (24 reference dates)
- ``Total`` rows reconcile exactly against the sum of their parts, both by
  staff group and by HSC organisation, and against the Table 1 headline WTE
- Pay band shares sum to 1 for each staff group
- Headcount is below active posts (individuals holding multiple posts)
- Validation helper raises on bad input
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import hsc_workforce as hw
from bolster.data_sources.health_ni._base import NISRAValidationError

#: The five geographic HSC Trusts, always present in the organisation table.
HSC_TRUSTS = {
    "Belfast HSC Trust",
    "Northern HSC Trust",
    "South Eastern HSC Trust",
    "Southern HSC Trust",
    "Western HSC Trust",
}


class TestHSCWorkforceIntegrity:
    """Integration tests using real downloaded workbooks."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        """Download and parse every published quarterly release once."""
        return hw.get_latest_data()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        """All required columns must be present."""
        missing = hw.REQUIRED_COLUMNS - set(latest_data.columns)
        assert not missing, f"Missing columns: {sorted(missing)}"

    def test_dataframe_not_empty(self, latest_data: pd.DataFrame) -> None:
        """Dataset must contain a substantial number of records."""
        assert len(latest_data) >= 1000

    def test_date_dtype(self, latest_data: pd.DataFrame) -> None:
        """Date column must be datetime-typed."""
        assert pd.api.types.is_datetime64_any_dtype(latest_data["date"])

    def test_value_dtype_is_float(self, latest_data: pd.DataFrame) -> None:
        """WTE figures are fractional, so value must be float-typed."""
        assert pd.api.types.is_float_dtype(latest_data["value"])

    def test_quarters_are_valid(self, latest_data: pd.DataFrame) -> None:
        """Quarter must always be 1-4 and agree with the month of the date."""
        assert set(latest_data["quarter"].unique()).issubset({1, 2, 3, 4})
        derived = latest_data["date"].dt.quarter
        assert (latest_data["quarter"] == derived).all()

    def test_dates_are_period_ends(self, latest_data: pd.DataFrame) -> None:
        """Every reference date must be a quarter end (March/June/Sept/Dec)."""
        months = set(latest_data["date"].dt.month.unique())
        assert months.issubset({3, 6, 9, 12}), f"Unexpected months: {sorted(months)}"

    def test_historical_coverage(self, latest_data: pd.DataFrame) -> None:
        """Each release carries a six-year series, so coverage far exceeds the
        handful of publications currently listed."""
        assert latest_data["date"].nunique() >= 20
        assert latest_data["date"].min() <= pd.Timestamp("2021-03-31")
        assert latest_data["date"].max() >= pd.Timestamp("2025-03-31")

    def test_expected_tables_present(self, latest_data: pd.DataFrame) -> None:
        """All documented table dimensions must appear in the output."""
        missing = set(hw.TABLE_DIMENSIONS.values()) - set(latest_data["table"].unique())
        assert not missing, f"Missing tables: {sorted(missing)}"

    def test_no_negative_values(self, latest_data: pd.DataFrame) -> None:
        """Staff counts and rates must never be negative."""
        assert (latest_data["value"].dropna() >= 0).all()

    def test_trusts_present(self, latest_data: pd.DataFrame) -> None:
        """The five geographic Trusts must appear among the organisations."""
        organisations = set(hw.list_organisations(latest_data))
        assert HSC_TRUSTS.issubset(organisations)

    def test_ambulance_service_present(self, latest_data: pd.DataFrame) -> None:
        """NIAS is reported as an organisation alongside the five Trusts."""
        organisations = set(hw.list_organisations(latest_data))
        assert any("Ambulance" in name for name in organisations)

    def test_staff_groups_present(self, latest_data: pd.DataFrame) -> None:
        """The major clinical staff groups must be present."""
        groups = set(hw.list_staff_groups(latest_data))
        assert "Medical & Dental" in groups
        assert "Registered Nursing & Midwifery" in groups
        assert len(groups) >= 8

    def test_organisation_totals_reconcile(self, latest_data: pd.DataFrame) -> None:
        """The organisation Total must equal the sum of the individual orgs."""
        table = latest_data[latest_data["table"] == "organisation"]
        for date, group in table.groupby("date"):
            total = group.loc[group["organisation"] == "Total", "value"]
            if total.empty:
                continue
            parts = group.loc[group["organisation"] != "Total", "value"].sum()
            assert float(total.iloc[0]) == pytest.approx(parts, rel=1e-6), f"Organisation total mismatch at {date.date()}"

    def test_staff_group_totals_reconcile(self, latest_data: pd.DataFrame) -> None:
        """The staff group Total must equal the sum of the individual groups."""
        table = latest_data[latest_data["table"] == "staff_group"]
        for date, group in table.groupby("date"):
            total = group.loc[group["staff_group"] == "Total", "value"]
            if total.empty:
                continue
            parts = group.loc[group["staff_group"] != "Total", "value"].sum()
            assert float(total.iloc[0]) == pytest.approx(parts, rel=1e-6), f"Staff group total mismatch at {date.date()}"

    def test_summary_wte_matches_organisation_total(self, latest_data: pd.DataFrame) -> None:
        """Headline WTE (Table 1) must agree with the organisation Total (Table 3)."""
        summary = latest_data[(latest_data["table"] == "summary") & (latest_data["measure"] == "wte")].set_index(
            "date"
        )["value"]
        organisations = latest_data[
            (latest_data["table"] == "organisation") & (latest_data["organisation"] == "Total")
        ].set_index("date")["value"]
        shared = summary.index.intersection(organisations.index)
        assert len(shared) >= 20
        for date in shared:
            assert float(summary[date]) == pytest.approx(float(organisations[date]), rel=1e-6)

    def test_headcount_below_active_posts(self, latest_data: pd.DataFrame) -> None:
        """Some staff hold more than one post, so headcount < active posts."""
        summary = latest_data[latest_data["table"] == "summary"].pivot_table(
            index="date", columns="measure", values="value"
        )
        assert (summary["headcount"] < summary["active_posts"]).all()

    def test_multiple_post_holders_reconcile(self, latest_data: pd.DataFrame) -> None:
        """Surplus posts must be at least the number of multiple-post holders.

        Someone holding three posts adds two surplus posts but counts once as an
        individual, so the surplus is an upper bound on the holder count.
        """
        summary = latest_data[latest_data["table"] == "summary"].pivot_table(
            index="date", columns="measure", values="value"
        )
        surplus = summary["active_posts"] - summary["headcount"]
        holders = summary["individuals_multiple_posts"]
        assert (surplus >= holders).all()
        assert (surplus <= holders * 1.1).all()

    def test_wte_below_headcount(self, latest_data: pd.DataFrame) -> None:
        """Part-time working means WTE is always below headcount."""
        summary = latest_data[latest_data["table"] == "summary"].pivot_table(
            index="date", columns="measure", values="value"
        )
        assert (summary["wte"] < summary["headcount"]).all()

    def test_pay_band_shares_sum_to_one(self, latest_data: pd.DataFrame) -> None:
        """Each staff group's pay band proportions must sum to 1."""
        bands = hw.get_pay_bands(latest_data)
        assert len(bands) > 0
        sums = bands.groupby(["date", "staff_group"])["value"].sum()
        assert sums.between(0.99, 1.01).all(), f"Pay band shares out of range: {sums[~sums.between(0.99, 1.01)]}"

    def test_rate_measures_are_proportions(self, latest_data: pd.DataFrame) -> None:
        """Joining, leaving and stability rates are proportions, not percentages."""
        rates = latest_data.loc[latest_data["measure"].isin(hw.RATE_MEASURES), "value"].dropna()
        assert len(rates) > 0
        assert rates.between(0, 1).all()

    def test_turnover_is_march_only(self, latest_data: pd.DataFrame) -> None:
        """Turnover tables are reported by financial year, so always end 31 March."""
        turnover = hw.get_turnover(latest_data)
        assert len(turnover) > 0
        assert (turnover["date"].dt.month == 3).all()

    def test_stability_rate_plausible(self, latest_data: pd.DataFrame) -> None:
        """Annual workforce stability sits comfortably above 80%."""
        stability = latest_data[latest_data["measure"] == "stability_rate"]["value"]
        assert len(stability) > 0
        assert stability.between(0.8, 1.0).all()

    def test_total_wte_plausible(self, latest_data: pd.DataFrame) -> None:
        """NI HSC employs on the order of 60-90k WTE staff."""
        summary = latest_data[(latest_data["table"] == "summary") & (latest_data["measure"] == "wte")]["value"]
        assert summary.between(50_000, 100_000).all()

    def test_belfast_is_largest_trust(self, latest_data: pd.DataFrame) -> None:
        """Belfast HSC Trust is consistently the largest employer of the five."""
        organisations = hw.get_organisations(latest_data)
        latest = organisations[organisations["date"] == organisations["date"].max()]
        trusts = latest[latest["organisation"].isin(HSC_TRUSTS)]
        assert trusts.loc[trusts["value"].idxmax(), "organisation"] == "Belfast HSC Trust"

    def test_workforce_grew_over_period(self, latest_data: pd.DataFrame) -> None:
        """Headline WTE has risen across the covered period."""
        summary = (
            latest_data[(latest_data["table"] == "summary") & (latest_data["measure"] == "wte")]
            .sort_values("date")
            .set_index("date")["value"]
        )
        assert summary.iloc[-1] > summary.iloc[0]

    def test_no_duplicate_observations(self, latest_data: pd.DataFrame) -> None:
        """Each dimension combination must appear at most once."""
        dimensions = ["date", "table", "measure", "organisation", "staff_group", "grade_band"]
        assert not latest_data.duplicated(subset=dimensions).any()

    def test_cross_tab_covers_published_quarters(self, latest_data: pd.DataFrame) -> None:
        """Tables 4/5 are current-quarter only, so appear once per publication."""
        cross_tab = latest_data[latest_data["table"] == "organisation_staff_group"]
        assert cross_tab["date"].nunique() >= 3

    def test_other_organisations_decompose(self, latest_data: pd.DataFrame) -> None:
        """Table 5 decomposes the 'Other HSC Organisations' row of Table 4."""
        cross_tab = latest_data[latest_data["table"] == "organisation_staff_group"]
        assert "Other HSC Organisations" in set(cross_tab["organisation"].dropna())
        other = latest_data[latest_data["table"] == "other_organisation_staff_group"]
        assert "Public Health Agency" in set(other["organisation"].dropna())

    def test_validate_data_passes(self, latest_data: pd.DataFrame) -> None:
        """The shipped data must satisfy its own validation rules."""
        assert hw.validate_data(latest_data) is True


class TestAccessors:
    """Accessor helpers filter the tidy frame down to a single table."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return hw.get_latest_data()

    def test_get_summary(self, latest_data: pd.DataFrame) -> None:
        assert set(hw.get_summary(latest_data)["table"].unique()) == {"summary"}

    def test_get_staff_groups_excludes_total(self, latest_data: pd.DataFrame) -> None:
        groups = hw.get_staff_groups(latest_data)
        assert "Total" not in set(groups["staff_group"])

    def test_get_staff_groups_can_include_total(self, latest_data: pd.DataFrame) -> None:
        groups = hw.get_staff_groups(latest_data, include_total=True)
        assert "Total" in set(groups["staff_group"])

    def test_get_organisations_excludes_total(self, latest_data: pd.DataFrame) -> None:
        organisations = hw.get_organisations(latest_data)
        assert "Total" not in set(organisations["organisation"])

    def test_get_organisations_can_include_total(self, latest_data: pd.DataFrame) -> None:
        organisations = hw.get_organisations(latest_data, include_total=True)
        assert "Total" in set(organisations["organisation"])

    def test_get_turnover_tables(self, latest_data: pd.DataFrame) -> None:
        assert set(hw.get_turnover(latest_data)["table"].unique()) == {"leavers", "joiners", "stability"}


class TestPublicationDiscovery:
    """The article page must list parseable quarterly publications."""

    @pytest.fixture(scope="class")
    def publications(self) -> list[dict]:
        return hw.list_publications()

    def test_publications_found(self, publications: list[dict]) -> None:
        assert len(publications) > 0

    def test_publications_sorted_oldest_first(self, publications: list[dict]) -> None:
        dates = [publication["date"] for publication in publications]
        assert dates == sorted(dates)

    def test_publication_fields(self, publications: list[dict]) -> None:
        for publication in publications:
            assert publication["url"].startswith("https://")
            assert publication["quarter"] in {1, 2, 3, 4}
            assert publication["date"].month in {3, 6, 9, 12}

    def test_workbook_link_resolves(self, publications: list[dict]) -> None:
        url = hw.find_publication_xlsx(publications[-1]["url"])
        assert url.lower().endswith(".xlsx")


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def _frame(self, **overrides) -> pd.DataFrame:
        row = {
            "date": pd.Timestamp("2026-03-31"),
            "year": 2026,
            "quarter": 1,
            "table": "summary",
            "measure": "wte",
            "organisation": None,
            "staff_group": None,
            "grade_band": None,
            "value": 68341.2887,
        }
        row.update(overrides)
        return pd.DataFrame([row] * 1000, columns=hw.COLUMNS)

    def test_validate_empty_dataframe(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            hw.validate_data(pd.DataFrame())

    def test_validate_none(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            hw.validate_data(None)

    def test_validate_missing_columns(self) -> None:
        frame = self._frame().drop(columns=["grade_band"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            hw.validate_data(frame)

    def test_validate_too_few_records(self) -> None:
        with pytest.raises(NISRAValidationError, match="at least"):
            hw.validate_data(self._frame().head(10))

    def test_validate_unknown_table(self) -> None:
        with pytest.raises(NISRAValidationError, match="Unknown table"):
            hw.validate_data(self._frame(table="mystery"))

    def test_validate_negative_values(self) -> None:
        with pytest.raises(NISRAValidationError, match="negative"):
            hw.validate_data(self._frame(value=-1.0))

    def test_validate_rate_above_one(self) -> None:
        with pytest.raises(NISRAValidationError, match="proportions"):
            hw.validate_data(self._frame(table="leavers", measure="leaving_rate", value=55.0))

    def test_validate_passes_on_good_frame(self) -> None:
        assert hw.validate_data(self._frame()) is True


class TestHelpers:
    """Unit tests for the parsing helpers - no network calls needed."""

    def test_clean_label_strips_footnotes(self) -> None:
        assert hw._clean_label("Nursing & Midwifery Support [note 1]") == "Nursing & Midwifery Support"

    def test_clean_label_collapses_whitespace(self) -> None:
        assert hw._clean_label("Pay bands 8 \n& above") == "Pay bands 8 & above"

    def test_clean_label_normalises_punctuation(self) -> None:
        assert hw._clean_label("Children’s Court") == "Children's Court"

    def test_clean_label_returns_none_for_blank(self) -> None:
        assert hw._clean_label(None) is None
        assert hw._clean_label("   ") is None
        assert hw._clean_label(float("nan")) is None

    def test_period_end(self) -> None:
        assert hw._period_end(2026, 3) == pd.Timestamp("2026-03-31")
        assert hw._period_end(2024, 2) == pd.Timestamp("2024-02-29")

    def test_as_year_accepts_floats(self) -> None:
        assert hw._as_year(2021.0) == 2021

    def test_as_year_rejects_non_years(self) -> None:
        assert hw._as_year("% Change 2021 to 2026") is None
        assert hw._as_year(None) is None
        assert hw._as_year(12) is None

    def test_as_financial_year_end(self) -> None:
        assert hw._as_financial_year_end("2025/26") == 2026

    def test_as_financial_year_end_rejects_labels(self) -> None:
        assert hw._as_financial_year_end("Leavers") is None
        assert hw._as_financial_year_end(None) is None

    def test_as_measure_known_label(self) -> None:
        assert hw._as_measure("Individuals with multiple posts") == "individuals_multiple_posts"
        assert hw._as_measure("Leaving Rate (%)") == "leaving_rate"

    def test_as_measure_falls_back_to_slug(self) -> None:
        assert hw._as_measure("Some New Measure") == "some_new_measure"

    def test_as_measure_none(self) -> None:
        assert hw._as_measure(None) is None
