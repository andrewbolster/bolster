"""Integration tests for Translink data source modules — live network calls.

These tests hit the real Translink APIs and VMI feed.  They use
``scope="class"`` fixtures so each class makes only one network call.

Tests verify:
- Stop lookup table coverage (>10,000 stops)
- find_stop returns plausible results
- get_departures returns correct schema and sane values
- get_live_vehicles returns correct schema and NI-bounded coordinates
- validate_departures and validate_vehicles pass on live data
"""

import pandas as pd
import pytest

from bolster.data_sources.translink._base import TranslinkDataNotFoundError
from bolster.data_sources.translink.departures import (
    find_stop_id,
    get_departures,
    get_departures_by_name,
    get_departures_with_vehicles,
    get_direct_journeys,
    validate_departures,
)
from bolster.data_sources.translink.stops import (
    find_stop,
    get_stop_dataframe,
    get_stop_lookup,
)
from bolster.data_sources.translink.vehicles import get_live_vehicles, validate_vehicles

# ---------------------------------------------------------------------------
# Stop lookup table
# ---------------------------------------------------------------------------


class TestStopLookup:
    @pytest.fixture(scope="class")
    def lookup(self):
        return get_stop_lookup()

    def test_minimum_stop_count(self, lookup):
        assert len(lookup) >= 10_000

    def test_victoria_square_present(self, lookup):
        assert "700000001661" in lookup

    def test_stop_has_name(self, lookup):
        info = lookup["700000001661"]
        assert "name" in info
        assert len(info["name"]) > 0

    def test_stop_has_wgs84_coords(self, lookup):
        info = lookup["700000001661"]
        assert "latitude" in info
        assert "longitude" in info
        assert 54.0 < info["latitude"] < 56.0
        assert -8.5 < info["longitude"] < -5.0

    def test_all_entries_have_name(self, lookup):
        missing_name = [k for k, v in lookup.items() if "name" not in v]
        assert len(missing_name) == 0, f"{len(missing_name)} entries missing name"


class TestStopDataframe:
    @pytest.fixture(scope="class")
    def df(self):
        return get_stop_dataframe()

    def test_schema(self, df):
        assert set(df.columns) >= {"name", "latitude", "longitude"}

    def test_indexed_by_atco(self, df):
        assert df.index.name == "atco_code"
        assert "700000001661" in df.index

    def test_row_count(self, df):
        assert len(df) >= 10_000

    def test_coord_ranges(self, df):
        lats = df["latitude"].dropna()
        lons = df["longitude"].dropna()
        # Includes cross-border routes into the Republic (lat as low as ~51.5)
        assert (lats >= 51.0).all() and (lats <= 56.0).all()
        assert (lons >= -10.5).all() and (lons <= -5.0).all()


# ---------------------------------------------------------------------------
# find_stop / find_stop_id
# ---------------------------------------------------------------------------


class TestFindStop:
    @pytest.fixture(scope="class")
    def results(self):
        return find_stop("Cambria Street")

    def test_returns_list(self, results):
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_result_has_required_keys(self, results):
        for r in results:
            assert "id" in r
            assert "name" in r
            assert "location_type" in r

    def test_cambria_street_in_results(self, results):
        names = [r["name"].lower() for r in results]
        assert any("cambria" in n for n in names)

    def test_ids_are_strings(self, results):
        for r in results:
            assert isinstance(r["id"], str)
            assert len(r["id"]) > 0


class TestFindStopId:
    def test_cambria_street_returns_id(self):
        stop_id = find_stop_id("Cambria Street")
        assert isinstance(stop_id, str)
        assert len(stop_id) > 0


# ---------------------------------------------------------------------------
# get_departures
# ---------------------------------------------------------------------------


class TestGetDepartures:
    @pytest.fixture(scope="class")
    def departures(self):
        stop_id = find_stop_id("Shankill, Cambria Street")
        return get_departures(stop_id, n=5)

    def test_returns_dataframe(self, departures):
        assert isinstance(departures, pd.DataFrame)

    def test_schema(self, departures):
        required = {
            "planned_departure",
            "actual_departure",
            "service",
            "destination",
            "transport_mode",
            "is_real_time",
            "is_cancelled",
            "delay_minutes",
            "unique_id",
        }
        assert required.issubset(set(departures.columns))

    def test_at_most_n_rows(self, departures):
        assert len(departures) <= 5

    def test_sorted_by_departure(self, departures):
        if len(departures) < 2:
            pytest.skip("Need at least 2 departures to test sort order")
        times = departures["actual_departure"].tolist()
        assert times == sorted(times)

    def test_datetime_columns_utc(self, departures):
        if departures.empty:
            pytest.skip("No departures available")
        ts = departures["actual_departure"].iloc[0]
        assert str(ts.tzinfo) == "UTC"

    def test_bool_columns(self, departures):
        if departures.empty:
            pytest.skip("No departures available")
        assert departures["is_real_time"].dtype == bool
        assert departures["is_cancelled"].dtype == bool

    def test_validate_passes(self, departures):
        assert validate_departures(departures) is True


class TestGetDeparturesByName:
    @pytest.fixture(scope="class")
    def departures(self):
        return get_departures_by_name("Shankill, Cambria Street", n=3)

    def test_has_stop_name_column(self, departures):
        assert "stop_name" in departures.columns

    def test_stop_name_populated(self, departures):
        if departures.empty:
            pytest.skip("No departures available")
        assert departures["stop_name"].iloc[0] != ""


# ---------------------------------------------------------------------------
# get_direct_journeys
# ---------------------------------------------------------------------------


class TestGetDirectJourneys:
    """get_direct_journeys uses only the locally cached CIF timetable, so
    these tests use real data without any live network call."""

    @pytest.fixture(scope="class")
    def journeys(self):
        return get_direct_journeys("McKinstry Road", "Westwood Centre", n=5)

    def test_returns_dataframe(self, journeys):
        assert isinstance(journeys, pd.DataFrame)

    def test_schema(self, journeys):
        expected_cols = {
            "origin",
            "destination",
            "service",
            "scheduled_departure",
            "scheduled_arrival",
            "days",
            "direction",
        }
        assert expected_cols.issubset(journeys.columns)

    def test_at_most_n_rows(self, journeys):
        assert len(journeys) <= 5

    def test_origin_and_destination_populated(self, journeys):
        assert (journeys["origin"] != "").all()
        assert (journeys["destination"] != "").all()

    def test_unknown_stop_raises(self):
        with pytest.raises(TranslinkDataNotFoundError):
            get_direct_journeys("Not A Real Stop Name XYZ", "Westwood Centre")

    def test_no_direct_service_raises(self):
        with pytest.raises(TranslinkDataNotFoundError):
            get_direct_journeys("Europa Bus Station", "Great Victoria Street")

    def test_accepts_explicit_naive_datetime(self):
        from datetime import datetime

        journeys = get_direct_journeys("McKinstry Road", "Westwood Centre", n=3, dt=datetime(2026, 6, 29, 8, 0))
        assert len(journeys) <= 3


# ---------------------------------------------------------------------------
# get_live_vehicles
# ---------------------------------------------------------------------------


class TestGetLiveVehicles:
    @pytest.fixture(scope="class")
    def vehicles(self):
        return get_live_vehicles()

    def test_returns_dataframe(self, vehicles):
        assert isinstance(vehicles, pd.DataFrame)

    def test_schema(self, vehicles):
        required = {
            "vehicle_id",
            "line",
            "latitude",
            "longitude",
            "timestamp",
            "operator",
            "journey_id",
            "delay_seconds",
        }
        assert required.issubset(set(vehicles.columns))

    def test_has_vehicles(self, vehicles):
        assert len(vehicles) > 0, "VMI feed returned no vehicles (service hours?)"

    def test_most_coords_in_ni_region(self, vehicles):
        # Filter zero-coords (uninitialised GPS) and check most are in NI/border region
        lats = vehicles["latitude"].dropna()
        lats = lats[lats != 0.0]
        lons = vehicles["longitude"].dropna()
        lons = lons[lons != 0.0]
        if len(lats) == 0:
            pytest.skip("No non-zero coordinates available")
        in_range = ((lats >= 53.0) & (lats <= 55.4)).sum()
        assert in_range / len(lats) > 0.9, "Less than 90% of vehicles in island-of-Ireland bounds"

    def test_validate_passes(self, vehicles):
        assert validate_vehicles(vehicles) is True


class TestGetLiveVehiclesFiltered:
    def test_line_filter(self):
        df = get_live_vehicles(line="11E")
        if df.empty:
            pytest.skip("No 11E vehicles in feed (route may not be running)")
        assert all(df["line"].str.upper() == "11E")

    def test_operator_filter(self):
        df = get_live_vehicles(operator="MET")
        if df.empty:
            pytest.skip("No Metro vehicles in feed")
        assert all(df["operator"] == "MET")

    def test_operator_alias(self):
        # TM and MET should return the same Metro vehicles
        df_tm = get_live_vehicles(operator="TM")
        df_met = get_live_vehicles(operator="MET")
        assert len(df_tm) == len(df_met)


# ---------------------------------------------------------------------------
# get_departures_with_vehicles
# ---------------------------------------------------------------------------


class TestGetDeparturesWithVehicles:
    @pytest.fixture(scope="class")
    def enriched(self):
        return get_departures_with_vehicles("Shankill, Cambria Street", n=5)

    def test_returns_dataframe(self, enriched):
        assert isinstance(enriched, pd.DataFrame)

    def test_has_vehicle_columns(self, enriched):
        vehicle_cols = {"vehicle_id", "vehicle_lat", "vehicle_lon", "vehicle_delay_s"}
        assert vehicle_cols.issubset(set(enriched.columns))

    def test_has_departure_columns(self, enriched):
        assert "planned_departure" in enriched.columns
        assert "service" in enriched.columns

    def test_at_most_n_rows(self, enriched):
        assert len(enriched) <= 5
