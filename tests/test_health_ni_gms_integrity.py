"""Data integrity tests for NI General Medical Services (GMS) statistics.

Integrity classes hit the live BSO/FPS workbooks so a change in publication
layout, sheet numbering, or GOV.UK's slugs surfaces here rather than
downstream. ``TestValidation`` and ``TestInternals`` run in-process against
constructed frames.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import gms
from bolster.data_sources.health_ni._base import NISRADataNotFoundError, NISRAValidationError


class TestDiscovery:
    def test_quarterly_url_found(self) -> None:
        url = gms.find_latest_quarterly_url()
        assert url.startswith("https://") and url.lower().endswith(".xlsx")

    def test_annual_tables_url_found(self) -> None:
        url = gms.find_latest_annual_tables_url()
        assert url.startswith("https://") and url.lower().endswith(".xlsx")

    def test_registered_patients_url_found(self) -> None:
        url = gms.find_latest_registered_patients_url()
        assert url.startswith("https://") and url.lower().endswith(".xlsx")

    def test_annual_urls_differ_by_attachment(self) -> None:
        # Both live on the same publication; they must resolve to distinct files.
        assert gms.find_latest_annual_tables_url() != gms.find_latest_registered_patients_url()

    def test_unknown_prefix_raises(self) -> None:
        with pytest.raises(NISRADataNotFoundError, match="No GMS publications"):
            gms._find_latest_publication("general medical services", "/government/statistics/does-not-exist")


class TestAnnualIntegrity:
    @pytest.fixture(scope="class")
    def annual(self) -> pd.DataFrame:
        return gms.get_latest_annual_data()

    def test_expected_columns(self, annual: pd.DataFrame) -> None:
        assert set(annual.columns) == {"table_id", "table_title", "row_group", "row_label", "column", "value", "sheet"}

    def test_all_registry_sheets_present(self, annual: pd.DataFrame) -> None:
        expected = set(gms._ANNUAL_SHEETS)
        found = set(annual.sheet)
        assert expected <= found, f"Missing annual sheets: {sorted(expected - found)}"

    def test_list_annual_topics_matches_registry(self) -> None:
        assert set(gms.list_annual_topics()) == set(gms._ANNUAL_TOPICS)

    def test_registered_patients_sub_tables_span_years(self, annual: pd.DataFrame) -> None:
        sub_tables = annual[annual.sheet == "1.1"].table_id.unique()
        assert len(sub_tables) >= 10, f"Expected ~13 yearly sub-tables, got {sorted(sub_tables)}"

    def test_unknown_topic_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown annual GMS topic"):
            gms.get_annual_data("not_a_real_topic")

    def test_validation_passes(self, annual: pd.DataFrame) -> None:
        assert gms.validate_data(annual) is True


class TestQuarterlyIntegrity:
    @pytest.fixture(scope="class")
    def quarterly(self) -> pd.DataFrame:
        return gms.get_latest_quarterly_data()

    def test_expected_columns(self, quarterly: pd.DataFrame) -> None:
        assert set(quarterly.columns) == {
            "table_id",
            "table_title",
            "row_group",
            "row_label",
            "column",
            "value",
            "sheet",
        }

    def test_all_registry_sheets_present(self, quarterly: pd.DataFrame) -> None:
        expected = set(gms._QUARTERLY_SHEETS)
        found = set(quarterly.sheet)
        assert expected <= found, f"Missing quarterly sheets: {sorted(expected - found)}"

    def test_sheet_71_excluded(self, quarterly: pd.DataFrame) -> None:
        assert "7.1" not in set(quarterly.sheet)

    def test_list_quarterly_topics_matches_registry(self) -> None:
        assert set(gms.list_quarterly_topics()) == set(gms._QUARTERLY_TOPICS)

    def test_columns_are_quarter_labels(self, quarterly: pd.DataFrame) -> None:
        sample = quarterly[quarterly.sheet == "1.1"].column
        assert sample.str.match(r"^Quarter [1-4] \d{4}/\d{2}$").all()

    def test_unknown_topic_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown quarterly GMS topic"):
            gms.get_quarterly_data("not_a_real_topic")

    def test_validation_passes(self, quarterly: pd.DataFrame) -> None:
        assert gms.validate_data(quarterly) is True


class TestHeadlineAccessors:
    @pytest.fixture(scope="class")
    def list_size(self) -> pd.DataFrame:
        return gms.get_list_size("trust")

    def test_registered_patients_covers_all_trusts(self) -> None:
        df = gms.get_registered_patients("trust")
        expected = {"Belfast", "Northern", "South Eastern", "Southern", "Western", "Northern Ireland"}
        assert expected <= set(df.trust)

    def test_registered_patients_positive(self) -> None:
        df = gms.get_registered_patients("trust")
        assert (df.value > 0).all()

    def test_gp_count_positive(self) -> None:
        df = gms.get_gp_count("lgd")
        assert (df.value > 0).all()

    def test_practice_count_by_federation(self) -> None:
        df = gms.get_practice_count("federation")
        assert not df.empty
        assert (df.value > 0).all()

    def test_list_size_columns(self, list_size: pd.DataFrame) -> None:
        assert set(list_size.columns) == {"trust", "period", "list_size"}

    def test_list_size_in_plausible_range(self, list_size: pd.DataFrame) -> None:
        # GMS's own GP counts are headcount, not WTE-adjusted, so this runs
        # lower than a press-quoted "patients per GP" figure would.
        assert list_size.list_size.between(800, 3000).all(), f"Implausible list sizes: {list_size.list_size.tolist()}"

    def test_list_size_periods_are_march_census_points(self, list_size: pd.DataFrame) -> None:
        assert (list_size.period.dt.month == 3).all()

    def test_funding_per_patient_has_payment_columns(self) -> None:
        df = gms.get_funding_per_patient("trust")
        assert any("payment" in c.lower() for c in df.column.unique())

    def test_patient_proximity_by_deprivation_quintile(self) -> None:
        df = gms.get_patient_proximity("deprivation_quintile")
        assert any("Quintile" in label for label in df.row_label.unique())


class TestPracticeLevel:
    @pytest.fixture(scope="class")
    def registered_by_practice(self) -> pd.DataFrame:
        return gms.get_latest_registered_patients_by_practice()

    @pytest.fixture(scope="class")
    def quarterly_by_practice(self) -> pd.DataFrame:
        return gms.get_latest_quarterly_patients_by_practice()

    def test_registered_by_practice_columns(self, registered_by_practice: pd.DataFrame) -> None:
        assert {
            "practice_code",
            "practice_name",
            "postcode",
            "gender",
            "age_group",
            "registered_patients",
            "year",
        } <= set(registered_by_practice.columns)

    def test_registered_by_practice_spans_years(self, registered_by_practice: pd.DataFrame) -> None:
        assert registered_by_practice.year.nunique() >= 10

    def test_registered_by_practice_genders_are_uppercase(self, registered_by_practice: pd.DataFrame) -> None:
        assert set(registered_by_practice.gender) <= {"MALE", "FEMALE", "UNKNOWN"}

    def test_registered_by_practice_counts_non_negative(self, registered_by_practice: pd.DataFrame) -> None:
        counts = registered_by_practice.registered_patients.dropna()
        assert (counts >= 0).all()

    def test_quarterly_by_practice_columns(self, quarterly_by_practice: pd.DataFrame) -> None:
        assert {"practice_code", "trust", "lgd", "federation", "period", "value"} <= set(quarterly_by_practice.columns)

    def test_quarterly_by_practice_periods_are_quarter_ends(self, quarterly_by_practice: pd.DataFrame) -> None:
        months = set(quarterly_by_practice.period.dropna().dt.month)
        assert months <= {3, 6, 9, 12}

    def test_quarterly_by_practice_missing_header_raises(self) -> None:
        class _EmptyWorkbook:
            sheet_names = ["7.1"]

            def parse(self, *_args, **_kwargs):
                return pd.DataFrame([["not the header we expect"]])

        with pytest.raises(NISRADataNotFoundError, match="header row"):
            gms.parse_quarterly_patients_by_practice(_EmptyWorkbook())

    def test_missing_sheet_71_raises(self) -> None:
        class _NoSheet:
            sheet_names = ["1.1"]

        with pytest.raises(NISRADataNotFoundError, match="sheet 7.1"):
            gms.parse_quarterly_patients_by_practice(_NoSheet())


class TestInternals:
    """Network-free checks of pure-Python parsing helpers."""

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Quarter 1 2017/18", pd.Timestamp("2017-06-30")),
            ("Quarter 2 2017/18", pd.Timestamp("2017-09-30")),
            ("Quarter 3 2017/18", pd.Timestamp("2017-12-31")),
            ("Quarter 4 2017/18", pd.Timestamp("2018-03-31")),
        ],
    )
    def test_parse_quarter_period(self, label: str, expected: pd.Timestamp) -> None:
        assert gms._parse_quarter_period(label) == expected

    def test_parse_quarter_period_rejects_non_quarter_label(self) -> None:
        assert gms._parse_quarter_period("2020/21") is None

    def test_year_in_title_extracts_trailing_year(self) -> None:
        match = gms._YEAR_IN_TITLE_RE.search("Registered patients by gender, age group and LCG 2014")
        assert match is not None
        assert match.group(1) == "2014"

    def test_quarterly_registry_excludes_practice_level_sheet(self) -> None:
        # Sheet 7.1 is handled by parse_quarterly_patients_by_practice, not
        # through the generic topic registry.
        assert "7.1" not in gms._QUARTERLY_SHEETS


class TestValidation:
    """Network-free checks of the validation guard rails."""

    def test_empty_frame_raises(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            gms.validate_data(pd.DataFrame())

    def test_negative_value_raises(self) -> None:
        frame = pd.DataFrame({"value": [10.0, -5.0]})
        with pytest.raises(NISRAValidationError, match="negative values"):
            gms.validate_data(frame)

    def test_implausible_list_size_raises(self) -> None:
        frame = pd.DataFrame({"trust": ["Belfast"], "period": [pd.Timestamp("2026-03-31")], "list_size": [50000.0]})
        with pytest.raises(NISRAValidationError, match="list-size"):
            gms.validate_data(frame)

    def test_negative_registered_patients_raises(self) -> None:
        frame = pd.DataFrame({"registered_patients": [100.0, -1.0]})
        with pytest.raises(NISRAValidationError, match="negative"):
            gms.validate_data(frame)

    def test_valid_frame_passes(self) -> None:
        frame = pd.DataFrame({"value": [1.0, 2.0, 3.0]})
        assert gms.validate_data(frame) is True
