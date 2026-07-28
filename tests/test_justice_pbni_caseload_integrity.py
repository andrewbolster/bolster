"""Integrity tests for the PBNI caseload module.

Tests use real bulletins published through GOV.UK and NISRA (no mocks).
Network calls are made once per class via ``scope="class"`` fixtures. Decoding,
naming and validation edge cases are covered by network-free unit tests.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import pbni_caseload
from bolster.data_sources.justice.pbni_caseload import (
    PBNIDataError,
    PBNIDataNotFoundError,
)


class TestAnnualCaseloadIntegrity:
    """Integrity tests for the annual caseload headline figures."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pbni_caseload.get_annual_caseload()

    def test_required_columns(self, latest_data):
        assert {"date", "caseload", "service_users"}.issubset(latest_data.columns)

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_five_years_of_history(self, latest_data):
        assert len(latest_data) >= 5

    def test_snapshots_are_31_march(self, latest_data):
        assert (latest_data["date"].dt.month == 3).all()
        assert (latest_data["date"].dt.day == 31).all()

    def test_dates_ascending(self, latest_data):
        assert latest_data["date"].is_monotonic_increasing

    def test_recent_coverage(self, latest_data):
        assert latest_data["date"].max() >= pd.Timestamp("2025-03-31")

    def test_caseload_exceeds_service_users(self, latest_data):
        """One person can hold several concurrent orders, never fewer than one."""
        assert (latest_data["caseload"] >= latest_data["service_users"]).all()

    def test_value_ranges(self, latest_data):
        assert latest_data["caseload"].between(2000, 12000).all()
        assert latest_data["service_users"].between(1500, 10000).all()

    def test_published_2025_snapshot(self, latest_data):
        """The 31 March 2025 snapshot is a fixed published figure."""
        row = latest_data.set_index("date").loc[pd.Timestamp("2025-03-31")]
        assert row["caseload"] == 5743
        assert row["service_users"] == 4107

    def test_validate_passes(self, latest_data):
        assert pbni_caseload.validate_data(latest_data) is True


class TestQuarterlyCaseloadIntegrity:
    """Integrity tests for the quarterly caseload headline figures."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pbni_caseload.get_quarterly_caseload()

    def test_required_columns(self, latest_data):
        assert {"date", "caseload", "service_users"}.issubset(latest_data.columns)

    def test_multiple_quarters_of_history(self, latest_data):
        assert len(latest_data) >= 8

    def test_snapshots_are_quarter_ends(self, latest_data):
        assert set(latest_data["date"].dt.month).issubset({3, 6, 9, 12})

    def test_dates_ascending_and_unique(self, latest_data):
        assert latest_data["date"].is_monotonic_increasing
        assert not latest_data["date"].duplicated().any()

    def test_caseload_exceeds_service_users(self, latest_data):
        assert (latest_data["caseload"] >= latest_data["service_users"]).all()

    def test_validate_passes(self, latest_data):
        assert pbni_caseload.validate_data(latest_data) is True


class TestAnnualDimensions:
    """Integrity tests across every annual breakdown."""

    @pytest.fixture(scope="class")
    def frames(self):
        return pbni_caseload.get_latest_data("all", frequency="annual")

    def test_all_dimensions_present(self, frames):
        assert set(frames) == set(pbni_caseload.list_dimensions("annual"))

    def test_no_frame_is_empty(self, frames):
        assert all(not frame.empty for name, frame in frames.items())

    def test_order_type_percentages_sum_to_100(self, frames):
        totals = frames["order_type"].groupby("date")["percentage"].sum()
        assert totals.between(99, 101).all()

    def test_order_type_includes_probation_orders(self, frames):
        assert "Probation Order" in set(frames["order_type"]["order_type"])

    def test_gender_split_matches_service_users(self, frames):
        gender = frames["gender"].set_index("date")
        caseload = frames["caseload"].set_index("date")
        combined = gender["male_service_users"] + gender["female_service_users"]
        assert (combined == caseload["service_users"]).all()

    def test_gender_percentages_sum_to_100(self, frames):
        gender = frames["gender"]
        totals = gender["pct_of_male_service_users"] + gender["pct_of_female_service_users"]
        assert totals.between(99, 101).all()

    def test_offence_caseload_matches_latest_total(self, frames):
        """The offence breakdown covers the most recent snapshot only."""
        latest = frames["caseload"]["caseload"].iloc[-1]
        assert frames["offence"]["caseload"].sum() == latest

    def test_offence_includes_violence_against_the_person(self, frames):
        assert any("Violence against the person" in o for o in frames["offence"]["offence"])

    def test_age_bands_partition_service_users(self, frames):
        totals = frames["age"].groupby("date")["percentage"].sum()
        assert totals.between(99, 101).all()

    def test_new_victims_financial_years(self, frames):
        years = frames["new_victims"]["financial_year"]
        assert years.str.fullmatch(r"\d{4}/\d{2}").all()

    def test_new_victims_positive(self, frames):
        assert (frames["new_victims"]["new_victims"] > 0).all()

    def test_victims_gender_covers_same_span(self, frames):
        assert set(frames["victims_gender"]["date"]) == set(frames["caseload"]["date"])

    def test_ppani_total_within_service_users(self, frames):
        ppani = frames["ppani"].set_index("date")["total_ppani_users"]
        service_users = frames["caseload"].set_index("date")["service_users"]
        assert (ppani < service_users).all()

    def test_srosh_total_within_service_users(self, frames):
        srosh = frames["srosh"].set_index("date")["total_srosh_service_users"]
        service_users = frames["caseload"].set_index("date")["service_users"]
        assert (srosh < service_users).all()


class TestQuarterlyDimensions:
    """Integrity tests across every quarterly breakdown."""

    @pytest.fixture(scope="class")
    def frames(self):
        return pbni_caseload.get_latest_data("all", frequency="quarterly")

    def test_all_dimensions_present(self, frames):
        assert set(frames) == set(pbni_caseload.list_dimensions("quarterly"))

    def test_no_frame_is_empty(self, frames):
        assert all(not frame.empty for name, frame in frames.items())

    def test_supervision_splits_sum_to_caseload(self, frames):
        supervision = frames["supervision"].set_index("date")
        caseload = frames["caseload"].set_index("date")
        combined = supervision["community_supervision"] + supervision["custody_supervision"]
        assert (combined == caseload["caseload"]).all()

    def test_order_type_percentages_sum_to_100(self, frames):
        totals = frames["order_type"].groupby("date")["percentage"].sum()
        assert totals.between(99, 101).all()

    def test_ppani_categories_sum_to_ppani_total(self, frames):
        categories = frames["ppani_category"].set_index("date")
        total = frames["ppani"].set_index("date")["ppani_service_users"]
        combined = categories[["category_1", "category_2", "category_3"]].sum(axis=1)
        assert (combined == total).all()

    def test_new_caseload_is_a_flow_not_a_stock(self, frames):
        """New arrivals in a quarter are a fraction of the standing caseload."""
        assert (frames["new_caseload"]["new_caseload"] < frames["caseload"]["caseload"].to_numpy()).all()

    def test_reports_positive(self, frames):
        assert (frames["reports"]["reports"] > 0).all()

    def test_victims_new_within_total(self, frames):
        victims = frames["victims"]
        assert (victims["new_victims"] < victims["total_victims"]).all()

    def test_quarter_labels_populated(self, frames):
        assert frames["reports"]["quarter"].notna().all()


class TestPublicationDiscovery:
    """Tests for resolving publication URLs through the GOV.UK APIs."""

    @pytest.mark.parametrize("frequency", ["annual", "quarterly"])
    def test_resolves_to_datavis_page(self, frequency):
        url = pbni_caseload.find_latest_publication(frequency)
        assert url.startswith("https://")
        assert pbni_caseload.DATAVIS_HOST in url

    def test_rejects_unknown_frequency(self):
        with pytest.raises(ValueError, match="frequency must be one of"):
            pbni_caseload.find_latest_publication("monthly")


class TestDimensionSelection:
    """Tests for the dimension and frequency arguments - minimal network use."""

    def test_list_dimensions_annual(self):
        dimensions = pbni_caseload.list_dimensions("annual")
        assert "caseload" in dimensions
        assert "offence" in dimensions
        assert dimensions == sorted(dimensions)

    def test_list_dimensions_quarterly(self):
        dimensions = pbni_caseload.list_dimensions("quarterly")
        assert "supervision" in dimensions
        assert "reports" in dimensions

    def test_cadences_expose_different_dimensions(self):
        annual = set(pbni_caseload.list_dimensions("annual"))
        quarterly = set(pbni_caseload.list_dimensions("quarterly"))
        assert "offence" in annual - quarterly
        assert "reports" in quarterly - annual

    def test_list_dimensions_rejects_unknown_frequency(self):
        with pytest.raises(ValueError, match="frequency must be one of"):
            pbni_caseload.list_dimensions("weekly")

    def test_get_latest_data_rejects_unknown_dimension(self):
        with pytest.raises(ValueError, match="dimension must be"):
            pbni_caseload.get_latest_data("sentencing", frequency="annual")

    def test_get_latest_data_rejects_unknown_frequency(self):
        with pytest.raises(ValueError, match="frequency must be one of"):
            pbni_caseload.get_latest_data("caseload", frequency="daily")

    def test_annual_only_dimension_rejected_for_quarterly(self):
        with pytest.raises(ValueError, match="dimension must be"):
            pbni_caseload.get_latest_data("offence", frequency="quarterly")


class TestDecoding:
    """Unit tests for the NISRA CSV decoder - no network calls needed."""

    def test_strips_null_bytes_from_utf16le_payload(self):
        payload = "Date,Caseload\r\n2025-03-31,5743\r\n".encode("utf-16-le")
        assert pbni_caseload._decode_csv(payload) == "Date,Caseload\r\n2025-03-31,5743\r\n"

    def test_handles_odd_length_payload(self):
        """Bare single-byte line terminators leave some payloads odd-length."""
        payload = "A,B\r\n".encode("utf-16-le")[:-1]
        assert pbni_caseload._decode_csv(payload).startswith("A,B")

    def test_strips_utf8_bom(self):
        assert pbni_caseload._decode_csv(b"\xef\xbb\xbfDate") == "Date"

    def test_plain_ascii_passes_through(self):
        assert pbni_caseload._decode_csv(b"Date,Caseload") == "Date,Caseload"


class TestSnakeCase:
    """Unit tests for the column heading normaliser - no network calls needed."""

    def test_spaces_become_underscores(self):
        assert pbni_caseload._snake_case("Service users") == "service_users"

    def test_percent_sign_expands(self):
        assert pbni_caseload._snake_case("% of caseload") == "pct_of_caseload"

    def test_punctuation_collapses(self):
        assert pbni_caseload._snake_case("Order/Licence type") == "order_licence_type"

    def test_digits_preserved(self):
        assert pbni_caseload._snake_case("Category 1 users") == "category_1_users"

    def test_leading_and_trailing_separators_stripped(self):
        assert pbni_caseload._snake_case("(Caseload)") == "caseload"


class TestFigureExtraction:
    """Unit tests for figure extraction guards - no network calls needed."""

    def test_missing_figures_raise(self):
        with pytest.raises(PBNIDataNotFoundError, match="Missing annual figures"):
            pbni_caseload._extract_figures("<html>no figures here</html>", "annual")

    def test_unregistered_figure_numbers_ignored(self):
        import base64

        payload = base64.b64encode("Date,Caseload\r\n2025-03-31,1\r\n".encode("utf-16-le")).decode()
        html = f'href="data:text/csv;base64,{payload}" download="pbni-figure-99-2025.csv"'
        with pytest.raises(PBNIDataNotFoundError, match="Missing annual figures"):
            pbni_caseload._extract_figures(html, "annual")


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def _valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-03-31", "2025-03-31"]),
                "caseload": [5886, 5743],
                "service_users": [4258, 4107],
            }
        )

    def test_validate_good_dataframe(self):
        assert pbni_caseload.validate_data(self._valid_frame()) is True

    def test_validate_empty_dataframe(self):
        with pytest.raises(PBNIDataError, match="empty"):
            pbni_caseload.validate_data(pd.DataFrame())

    def test_validate_missing_columns(self):
        df = self._valid_frame().drop(columns=["service_users"])
        with pytest.raises(PBNIDataError, match="missing columns"):
            pbni_caseload.validate_data(df)

    def test_validate_unparseable_dates(self):
        df = self._valid_frame()
        df.loc[0, "date"] = pd.NaT
        with pytest.raises(PBNIDataError, match="unparseable dates"):
            pbni_caseload.validate_data(df)

    def test_validate_non_positive_counts(self):
        df = self._valid_frame()
        df.loc[0, "caseload"] = 0
        with pytest.raises(PBNIDataError, match="non-positive"):
            pbni_caseload.validate_data(df)

    def test_validate_negative_counts(self):
        df = self._valid_frame()
        df.loc[1, "service_users"] = -1
        with pytest.raises(PBNIDataError, match="non-positive"):
            pbni_caseload.validate_data(df)
