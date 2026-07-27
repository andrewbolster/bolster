"""Data integrity tests for HSC Active Recruitment (vacancy) Statistics.

The ``TestRecruitmentIntegrity`` classes hit the live DoH bulletin so that a
change in the published CSV layout surfaces here rather than downstream.
``TestValidation`` runs in-process against constructed frames.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import hsc_recruitment
from bolster.data_sources.health_ni._base import NISRADataNotFoundError, NISRAValidationError


class TestPublicationDiscovery:
    @pytest.fixture(scope="class")
    def publications(self) -> pd.DataFrame:
        return hsc_recruitment.list_publications()

    def test_publications_found(self, publications: pd.DataFrame) -> None:
        assert not publications.empty, "No recruitment bulletins found on the series index"

    def test_expected_columns(self, publications: pd.DataFrame) -> None:
        assert set(publications.columns) == {"period", "title", "url"}

    def test_sorted_newest_first(self, publications: pd.DataFrame) -> None:
        assert publications.period.is_monotonic_decreasing

    def test_periods_are_quarter_months(self, publications: pd.DataFrame) -> None:
        months = set(publications.period.dt.month)
        assert months <= {3, 6, 9, 12}, f"Unexpected publication months: {sorted(months)}"

    def test_unknown_period_raises(self) -> None:
        with pytest.raises(NISRADataNotFoundError, match="No bulletin"):
            hsc_recruitment.find_publication("1999-03")


class TestRecruitmentIntegrity:
    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return hsc_recruitment.get_latest_data()

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
        expected = {"1A", "1B", "2", "3", "4A", "4B", "5A", "5B", "6", "7", "8A", "8B", "8C"}
        assert expected <= set(latest_data.table_id), (
            f"Missing tables: {sorted(expected - set(latest_data.table_id))}"
        )

    def test_list_tables_matches_data(self, latest_data: pd.DataFrame) -> None:
        tables = hsc_recruitment.list_tables()
        assert set(tables.table_id) == set(latest_data.table_id)

    def test_pay_band_vacancies_are_counts(self) -> None:
        bands = hsc_recruitment.get_vacancies_by_pay_band()
        assert (bands.vacancies.dropna() >= 0).all()

    def test_pay_band_total_is_plausible(self) -> None:
        bands = hsc_recruitment.get_vacancies_by_pay_band()
        total = bands[bands.pay_band.str.contains("Total", case=False, na=False)].vacancies.sum()
        assert 5_000 < total < 30_000, f"Total vacancies implausible: {total}"

    def test_sub_pay_band_view_differs(self) -> None:
        top = set(hsc_recruitment.get_vacancies_by_pay_band().staff_group)
        sub = set(hsc_recruitment.get_vacancies_by_pay_band(sub=True).staff_group)
        assert sub - top, f"Sub staff groups add nothing beyond {sorted(top)}"

    def test_organisation_series_includes_belfast_trust(self) -> None:
        orgs = hsc_recruitment.get_vacancies_by_organisation()
        assert "Belfast HSC Trust" in set(orgs.organisation)

    def test_organisation_series_starts_2017(self) -> None:
        orgs = hsc_recruitment.get_vacancies_by_organisation()
        assert orgs.period.min() == pd.Timestamp("2017-03-31")

    def test_staff_group_series_is_quarterly(self) -> None:
        groups = hsc_recruitment.get_vacancies_by_staff_group()
        assert groups.period.nunique() > 1
        months = set(groups.period.dt.month)
        assert months <= {3, 6, 9, 12}, f"Unexpected census months: {sorted(months)}"

    def test_vacancy_rates_are_proportions(self) -> None:
        rates = hsc_recruitment.get_vacancy_rates()
        assert rates.vacancy_rate.dropna().between(0, 1).all(), (
            f"Vacancy rates outside [0, 1]: max {rates.vacancy_rate.max()}"
        )

    def test_vacancy_rates_are_non_trivial(self) -> None:
        rates = hsc_recruitment.get_vacancy_rates()
        assert rates.vacancy_rate.max() > 0.01, "Expected at least one staff group above a 1% vacancy rate"

    def test_profession_view_is_cross_tabulated(self) -> None:
        professions = hsc_recruitment.get_vacancies_by_profession()
        assert {"period", "staff_group", "profession", "vacancies"} <= set(professions.columns)
        assert professions.staff_group.nunique() > 1
        assert professions.profession.nunique() > professions.staff_group.nunique()

    @pytest.mark.parametrize("grade", ["consultant", "locum", "sas"])
    def test_doctor_grades_available(self, grade: str) -> None:
        doctors = hsc_recruitment.get_doctor_vacancies(grade=grade)
        assert not doctors.empty, f"No {grade} vacancy data returned"
        assert doctors.period.min() >= pd.Timestamp("2020-03-31")

    def test_doctor_specialties_are_clinical(self) -> None:
        doctors = hsc_recruitment.get_doctor_vacancies()
        specialties = set(doctors.specialty)
        assert {"Cardiology", "Emergency Medicine"} <= specialties, (
            f"Expected clinical specialties, got {sorted(specialties)[:10]}"
        )

    def test_unknown_doctor_grade_raises(self) -> None:
        with pytest.raises(ValueError, match="grade"):
            hsc_recruitment.get_doctor_vacancies(grade="nonsense")

    def test_validation_passes(self, latest_data: pd.DataFrame) -> None:
        assert hsc_recruitment.validate_data(latest_data) is True


class TestValidation:
    """Network-free checks of the validation guard rails."""

    @pytest.fixture
    def valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "table_id": ["1A"] * 6000,
                "table_title": ["HSC Vacancies"] * 6000,
                "row_group": [None] * 6000,
                "row_label": ["Administration & Clerical"] * 6000,
                "column": ["2026"] * 6000,
                "value": [10.0] * 6000,
            }
        )

    def test_valid_frame_passes(self, valid_frame: pd.DataFrame) -> None:
        assert hsc_recruitment.validate_data(valid_frame) is True

    def test_empty_frame_raises(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            hsc_recruitment.validate_data(pd.DataFrame())

    def test_missing_columns_raise(self, valid_frame: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            hsc_recruitment.validate_data(valid_frame.drop(columns=["row_group"]))

    def test_too_few_records_raise(self, valid_frame: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="Too few records"):
            hsc_recruitment.validate_data(valid_frame.head(10))

    def test_negative_count_raises(self, valid_frame: pd.DataFrame) -> None:
        frame = valid_frame.copy()
        frame.loc[0, "value"] = -1.0
        with pytest.raises(NISRAValidationError, match="Negative values"):
            hsc_recruitment.validate_data(frame)

    def test_mostly_unparsed_raises(self, valid_frame: pd.DataFrame) -> None:
        frame = valid_frame.copy()
        frame.loc[: len(frame) // 2, "value"] = None
        with pytest.raises(NISRAValidationError, match="unparsed"):
            hsc_recruitment.validate_data(frame)
