"""Data integrity tests for HSC Workforce Statistics.

The ``TestWorkforceIntegrity`` classes hit the live DoH bulletin so that a
change in the published CSV layout surfaces here rather than downstream.
``TestValidation`` runs in-process against constructed frames.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import hsc_workforce
from bolster.data_sources.health_ni._base import NISRADataNotFoundError, NISRAValidationError


class TestPublicationDiscovery:
    @pytest.fixture(scope="class")
    def publications(self) -> pd.DataFrame:
        return hsc_workforce.list_publications()

    def test_publications_found(self, publications: pd.DataFrame) -> None:
        assert not publications.empty, "No workforce bulletins found on the series index"

    def test_expected_columns(self, publications: pd.DataFrame) -> None:
        assert set(publications.columns) == {"period", "title", "url"}

    def test_sorted_newest_first(self, publications: pd.DataFrame) -> None:
        assert publications.period.is_monotonic_decreasing

    def test_periods_are_quarter_months(self, publications: pd.DataFrame) -> None:
        months = set(publications.period.dt.month)
        assert months <= {3, 6, 9, 12}, f"Unexpected publication months: {sorted(months)}"

    def test_urls_are_absolute(self, publications: pd.DataFrame) -> None:
        assert publications.url.str.startswith("https://").all()

    def test_unknown_period_raises(self) -> None:
        with pytest.raises(NISRADataNotFoundError, match="No bulletin"):
            hsc_workforce.find_publication("1999-03")


class TestWorkforceIntegrity:
    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return hsc_workforce.get_latest_data()

    @pytest.fixture(scope="class")
    def summary(self) -> pd.DataFrame:
        return hsc_workforce.get_workforce_summary()

    def test_expected_columns(self, latest_data: pd.DataFrame) -> None:
        assert set(latest_data.columns) == {
            "table_id",
            "table_title",
            "row_group",
            "row_label",
            "column",
            "value",
        }

    def test_all_expected_tables_present(self, latest_data: pd.DataFrame) -> None:
        # Tables 1 to 6 are in every bulletin. 7A, 7B and 7C carry turnover,
        # which closes the financial year and appears once a year, so they are
        # absent from three bulletins in four and are not asserted here.
        expected = {"1", "2A", "2B", "3", "4", "5", "6"}
        assert expected <= set(latest_data.table_id), f"Missing tables: {sorted(expected - set(latest_data.table_id))}"

    def test_turnover_tables_are_annual(self) -> None:
        """Turnover is published once a year, so it must be found by search."""
        data = hsc_workforce.find_turnover_data()
        assert {"7A", "7B", "7C"} <= set(data.table_id)

    def test_list_tables_matches_data(self, latest_data: pd.DataFrame) -> None:
        tables = hsc_workforce.list_tables()
        assert set(tables.table_id) == set(latest_data.table_id)

    def test_summary_covers_headline_measures(self, summary: pd.DataFrame) -> None:
        measures = set(summary.measure)
        assert {"WTE", "Headcount"} <= measures, f"Got measures: {sorted(measures)}"

    def test_summary_wte_in_plausible_range(self, summary: pd.DataFrame) -> None:
        wte = summary[summary.measure == "WTE"].value
        assert wte.between(50_000, 100_000).all(), f"WTE outside plausible range: {wte.tolist()}"

    def test_summary_headcount_exceeds_wte(self, summary: pd.DataFrame) -> None:
        pivot = summary.pivot_table(index="period", columns="measure", values="value")
        assert (pivot["Headcount"] >= pivot["WTE"]).all(), "Headcount must be >= WTE"

    def test_summary_series_starts_2021(self, summary: pd.DataFrame) -> None:
        assert summary.period.min() == pd.Timestamp("2021-03-31")

    def test_summary_periods_are_march_census_points(self, summary: pd.DataFrame) -> None:
        assert (summary.period.dt.month == 3).all()

    def test_staff_groups_include_nursing(self) -> None:
        groups = hsc_workforce.get_workforce_by_staff_group()
        assert any("Nursing" in name for name in groups.staff_group), (
            f"No nursing staff group in {sorted(set(groups.staff_group))}"
        )

    def test_sub_staff_groups_are_a_distinct_cut(self) -> None:
        # Table 2B is a profession-level view, not a strict subdivision of the
        # eight headline groups, so it carries labels absent from table 2A.
        top = set(hsc_workforce.get_workforce_by_staff_group().staff_group)
        sub = set(hsc_workforce.get_workforce_by_staff_group(sub=True).staff_group)
        assert sub - top, f"Sub staff groups add nothing beyond {sorted(top)}"
        assert "Consultants" in sub, f"Expected profession-level labels, got {sorted(sub)}"

    def test_organisations_include_belfast_trust(self) -> None:
        orgs = hsc_workforce.get_workforce_by_organisation()
        assert "Belfast HSC Trust" in set(orgs.organisation)

    def test_organisation_wte_is_positive(self) -> None:
        orgs = hsc_workforce.get_workforce_by_organisation()
        assert (orgs.wte.dropna() > 0).all()

    def test_staff_group_by_organisation_is_cross_tabulated(self) -> None:
        cross = hsc_workforce.get_staff_group_by_organisation()
        assert {"organisation", "staff_group", "wte"} <= set(cross.columns)
        assert cross.organisation.nunique() > 1
        assert cross.staff_group.nunique() > 1

    def test_pay_band_distribution_is_proportions(self) -> None:
        bands = hsc_workforce.get_pay_band_distribution()
        # The "Total WTE" column carries absolute WTE rather than a share
        shares = bands[~bands.pay_band.str.contains("Total", case=False, na=False)].share
        assert shares.dropna().between(0, 1).all(), "Pay band shares should be proportions in [0, 1]"

    @pytest.mark.parametrize("measure", ["leavers", "joiners", "stability"])
    def test_turnover_measures_available(self, measure: str) -> None:
        turnover = hsc_workforce.get_turnover(measure=measure)
        assert not turnover.empty, f"No {measure} data returned"

    def test_turnover_is_a_financial_year_series(self) -> None:
        leavers = hsc_workforce.get_turnover(measure="leavers")
        assert leavers.financial_year.str.match(r"\d{4}/\d{2}").all(), (
            f"Unexpected financial years: {sorted(set(leavers.financial_year))}"
        )

    def test_turnover_rates_are_proportions(self) -> None:
        leavers = hsc_workforce.get_turnover(measure="leavers")
        rates = leavers[leavers.metric.str.contains("Rate", case=False, na=False)].value
        assert rates.dropna().between(0, 1).all(), f"Leaving rates outside [0, 1]: {rates.tolist()}"

    def test_unknown_turnover_measure_raises(self) -> None:
        with pytest.raises(ValueError, match="measure"):
            hsc_workforce.get_turnover(measure="nonsense")

    def test_validation_passes(self, latest_data: pd.DataFrame) -> None:
        assert hsc_workforce.validate_data(latest_data) is True


class TestValidation:
    """Network-free checks of the validation guard rails."""

    @pytest.fixture
    def valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "table_id": ["1"] * 500,
                "table_title": ["HSC Workforce"] * 500,
                "row_group": [None] * 500,
                "row_label": ["Medical & Dental"] * 500,
                "column": ["2026"] * 500,
                "value": [100.0] * 500,
            }
        )

    def test_valid_frame_passes(self, valid_frame: pd.DataFrame) -> None:
        assert hsc_workforce.validate_data(valid_frame) is True

    def test_empty_frame_raises(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            hsc_workforce.validate_data(pd.DataFrame())

    def test_missing_columns_raise(self, valid_frame: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            hsc_workforce.validate_data(valid_frame.drop(columns=["row_group"]))

    def test_too_few_records_raise(self, valid_frame: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="Too few records"):
            hsc_workforce.validate_data(valid_frame.head(10))

    def test_negative_count_raises(self, valid_frame: pd.DataFrame) -> None:
        frame = valid_frame.copy()
        frame.loc[0, "value"] = -1.0
        with pytest.raises(NISRAValidationError, match="Negative values"):
            hsc_workforce.validate_data(frame)

    def test_negative_percent_change_allowed(self, valid_frame: pd.DataFrame) -> None:
        frame = valid_frame.copy()
        frame.loc[0, "column"] = "% Change 2025 to 2026"
        frame.loc[0, "value"] = -0.118
        assert hsc_workforce.validate_data(frame) is True

    def test_mostly_unparsed_raises(self, valid_frame: pd.DataFrame) -> None:
        frame = valid_frame.copy()
        frame.loc[: len(frame) // 2, "value"] = None
        with pytest.raises(NISRAValidationError, match="unparsed"):
            hsc_workforce.validate_data(frame)


class TestArchive:
    """The series page advertises a rolling window; older bulletins persist.

    These exercise the archive path and, more importantly, that the extractors
    survive the format changes across it: table 2 became 2A/2B in March 2025,
    "Regional HSC Trust" gained "/Organisation", and the "% Change" column
    labels were reworded. Selection is by table title for exactly that reason.
    """

    @pytest.fixture(scope="class")
    def archive(self) -> pd.DataFrame:
        return hsc_workforce.list_archive()

    def test_archive_reaches_past_the_advertised_window(self, archive: pd.DataFrame) -> None:
        advertised = hsc_workforce.list_publications()
        assert len(archive) > len(advertised)
        assert archive.period.min() < advertised.period.min()

    def test_archive_is_quarterly_and_newest_first(self, archive: pd.DataFrame) -> None:
        assert archive.period.is_monotonic_decreasing
        assert set(archive.period.dt.month) <= {3, 6, 9, 12}

    def test_delisted_bulletin_is_reachable_by_period(self) -> None:
        publication = hsc_workforce.find_publication("March 2024")
        assert publication["period"] == pd.Timestamp("2024-03-01")

    @pytest.mark.parametrize("period", ["March 2024", "March 2026"])
    def test_accessors_survive_format_changes(self, period: str) -> None:
        # March 2024 predates the 2A/2B split and the retitled trust table.
        assert not hsc_workforce.get_workforce_summary(period=period).empty
        assert not hsc_workforce.get_workforce_by_staff_group(period=period).empty
        assert not hsc_workforce.get_workforce_by_organisation(period=period).empty
        assert not hsc_workforce.get_staff_group_by_organisation(period=period).empty
        assert not hsc_workforce.get_pay_band_distribution(period=period).empty

    def test_sub_staff_group_refuses_rather_than_substituting(self) -> None:
        # Table 2B arrived in March 2025. The headline groups are a different
        # cut, so falling back to them would quietly change what was asked for.
        with pytest.raises(NISRADataNotFoundError):
            hsc_workforce.get_workforce_by_staff_group(period="March 2024", sub=True)

    def test_census_columns_parse_across_generations(self) -> None:
        # Headings are bare years throughout, but the "% Change" columns that
        # sit beside them were reworded; they must stay excluded either way.
        for period in ("March 2024", "March 2026"):
            summary = hsc_workforce.get_workforce_summary(period=period)
            assert summary.period.notna().all()
            assert (summary.period.dt.month == 3).all()
