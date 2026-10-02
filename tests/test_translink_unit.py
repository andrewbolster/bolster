"""Unit tests for Translink data source modules — no network calls.

Covers parsing logic, ticks decoding, journey ID normalisation, direction
inference, CIF parsing, operator alias resolution, and validation edge cases.
"""

import io
import zipfile

import pandas as pd
import pytest

from bolster.data_sources.translink import stops
from bolster.data_sources.translink._base import (
    OPERATOR_ALIASES,
    TranslinkValidationError,
    net_ticks_to_timestamp,
)
from bolster.data_sources.translink.departures import (
    _extract_line,
    _greedy_assign_vehicles,
    _hhmm_to_timestamp,
    _parse_departures,
    _resolve_target_atcos,
    _verified_passing_time,
    validate_departures,
)
from bolster.data_sources.translink.stops import _ing_to_wgs84, _parse_cif_zip, find_stop_fuzzy
from bolster.data_sources.translink.timetable import (
    Trip,
    TripStop,
    _parse_cif_trips,
    _parse_time_at,
    _trip_atco_to_stop_atco,
    find_direct_trips,
    find_trip_for_vehicle,
)
from bolster.data_sources.translink.vehicles import (
    _normalise_operator,
    _parse_journey_time,
    _parse_vmi,
    validate_vehicles,
)

# ---------------------------------------------------------------------------
# _base: net_ticks_to_timestamp
# ---------------------------------------------------------------------------


class TestNetTicksToTimestamp:
    def test_known_epoch(self):
        # Ticks for Unix epoch (1970-01-01 00:00:00 UTC) =
        # 621_355_968_000_000_000
        from bolster.data_sources.translink._base import _NET_TICKS_EPOCH

        ts = net_ticks_to_timestamp(_NET_TICKS_EPOCH)
        assert ts == pd.Timestamp("1970-01-01", tz="UTC")

    def test_utc_aware(self):
        ts = net_ticks_to_timestamp(638_800_000_000_000_000)
        assert ts.tzinfo is not None
        assert str(ts.tzinfo) == "UTC"

    def test_recent_date(self):
        # 2024-01-15 12:00:00 UTC → ticks
        expected = pd.Timestamp("2024-01-15 12:00:00", tz="UTC")
        ticks = int(expected.timestamp() * 10_000_000) + 621_355_968_000_000_000
        result = net_ticks_to_timestamp(ticks)
        assert abs((result - expected).total_seconds()) < 1


# ---------------------------------------------------------------------------
# vehicles: _parse_journey_time
# ---------------------------------------------------------------------------


class TestParseJourneyTime:
    def test_bare_hhmm(self):
        assert _parse_journey_time("1741") == "1741"

    def test_with_suffix(self):
        assert _parse_journey_time("1741#!ADD!#vixvm_new#") == "1741"

    def test_only_hash(self):
        assert _parse_journey_time("0900#") == "0900"

    def test_empty(self):
        assert _parse_journey_time("") == ""


# ---------------------------------------------------------------------------
# vehicles: _normalise_operator
# ---------------------------------------------------------------------------


class TestNormaliseOperator:
    def test_tm_to_met(self):
        assert _normalise_operator("TM") == "MET"

    def test_unknown_passthrough(self):
        assert _normalise_operator("ULB") == "ULB"

    def test_all_aliases_defined(self):
        for k, v in OPERATOR_ALIASES.items():
            assert _normalise_operator(k) == v


# ---------------------------------------------------------------------------
# vehicles: _parse_vmi
# ---------------------------------------------------------------------------


def _make_vmi_record(**overrides):
    base = {
        "ID": "1",
        "VehicleIdentifier": "TM-1234",
        "LineText": "11E",
        "DirectionText": "Royal Avenue",
        "JourneyIdentifier": "1730#!ADD!#vixvm_new#",
        "DayOfOperation": "Monday",
        "X": "-5.9900",
        "Y": "54.6200",
        "XPrevious": "-5.9910",
        "YPrevious": "54.6210",
        "Timestamp": "2024-06-01T17:30:00",
        "TimestampPrevious": "2024-06-01T17:29:00",
        "Delay": -30,
        "CurrentStop": "700000014482",
        "NextStop": "700000014483",
        "IsAtStop": True,
        "RealtimeAvailable": True,
        "MOTCode": 3,
    }
    base.update(overrides)
    return base


class TestParseVmi:
    def test_basic_parse(self):
        df = _parse_vmi([_make_vmi_record()])
        assert len(df) == 1
        row = df.iloc[0]
        assert row["vehicle_id"] == "TM-1234"
        assert row["line"] == "11E"
        assert row["operator"] == "MET"  # TM → MET alias
        assert row["journey_id"] == "1730"  # suffix stripped
        assert abs(row["longitude"] - (-5.99)) < 0.001
        assert abs(row["latitude"] - 54.62) < 0.001
        assert bool(row["is_at_stop"]) is True
        assert row["delay_seconds"] == -30

    def test_empty_feed(self):
        df = _parse_vmi([])
        assert df.empty

    def test_missing_xy(self):
        rec = _make_vmi_record()
        del rec["X"]
        del rec["Y"]
        df = _parse_vmi([rec])
        assert pd.isna(df.iloc[0]["longitude"])
        assert pd.isna(df.iloc[0]["latitude"])

    def test_is_at_stop_sparse(self):
        # IsAtStop only appears when True in live feed
        rec = _make_vmi_record()
        del rec["IsAtStop"]
        df = _parse_vmi([rec])
        assert bool(df.iloc[0]["is_at_stop"]) is False

    def test_delay_coerced_to_int64(self):
        df = _parse_vmi([_make_vmi_record(Delay=None)])
        assert pd.isna(df.iloc[0]["delay_seconds"])

    def test_multiple_records(self):
        recs = [
            _make_vmi_record(ID="1", VehicleIdentifier="TM-1111"),
            _make_vmi_record(ID="2", VehicleIdentifier="ULB-2222"),
        ]
        df = _parse_vmi(recs)
        assert len(df) == 2
        assert set(df["vehicle_id"]) == {"TM-1111", "ULB-2222"}


# ---------------------------------------------------------------------------
# vehicles: validate_vehicles
# ---------------------------------------------------------------------------


class TestValidateVehicles:
    def _valid_df(self):
        return pd.DataFrame(
            {
                "vehicle_id": ["TM-1234"],
                "line": ["11E"],
                "latitude": [54.62],
                "longitude": [-5.99],
                "timestamp": [pd.Timestamp("2024-06-01", tz="UTC")],
            }
        )

    def test_valid_passes(self):
        assert validate_vehicles(self._valid_df()) is True

    def test_empty_passes(self):
        df = self._valid_df().iloc[0:0]
        assert validate_vehicles(df) is True

    def test_missing_column_raises(self):
        df = self._valid_df().drop(columns=["line"])
        with pytest.raises(TranslinkValidationError, match="missing columns"):
            validate_vehicles(df)

    def test_bad_latitude_raises(self):
        df = self._valid_df()
        df["latitude"] = 10.0  # Well outside island of Ireland
        with pytest.raises(TranslinkValidationError, match="Latitude"):
            validate_vehicles(df)

    def test_bad_longitude_raises(self):
        df = self._valid_df()
        df["longitude"] = 10.0  # Well outside island of Ireland
        with pytest.raises(TranslinkValidationError, match="Longitude"):
            validate_vehicles(df)

    def test_nan_coords_ignored(self):
        df = self._valid_df()
        df["latitude"] = float("nan")
        df["longitude"] = float("nan")
        assert validate_vehicles(df) is True  # NaN coords skipped


# ---------------------------------------------------------------------------
# departures: _extract_line
# ---------------------------------------------------------------------------


class TestExtractLine:
    def test_bus_service(self):
        assert _extract_line("Bus 11e") == "11E"

    def test_glider_service(self):
        assert _extract_line("Glider G1") == "G1"

    def test_plain_line(self):
        assert _extract_line("11E") == "11E"

    def test_no_prefix(self):
        assert _extract_line("12A") == "12A"

    def test_rail_larne(self):
        assert _extract_line("Rail Larne Line") == "Rail Larne Line"

    def test_rail_bangor(self):
        assert _extract_line("Rail Bangor Line") == "Rail Bangor Line"

    def test_rail_derry(self):
        assert _extract_line("Rail Derry/Londonderry Line") == "Rail Derry/Londonderry Line"


# ---------------------------------------------------------------------------
# departures: _parse_departures
# ---------------------------------------------------------------------------


def _make_departure(**overrides):
    # .NET ticks for 2024-06-01 17:30:00 UTC
    base_ticks = 638_529_990_000_000_000
    base = {
        "SysPlannedDepartureDate": base_ticks,
        "SysActualDepartureDate": base_ticks + 3_000_000_000,  # +5 min delay
        "ServiceName": "Bus 11E",
        "DestinationName": "Belfast, CastleCourt",
        "TransportMode": "Bus",
        "IsRealTime": True,
        "IsCancelled": False,
        "UniqueId": "dep-001",
    }
    base.update(overrides)
    return base


class TestParseDepartures:
    def test_empty_returns_schema(self):
        df = _parse_departures([])
        assert set(df.columns) >= {
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
        assert len(df) == 0

    def test_single_departure(self):
        df = _parse_departures([_make_departure()])
        assert len(df) == 1
        row = df.iloc[0]
        assert row["service"] == "Bus 11E"
        assert row["destination"] == "Belfast, CastleCourt"
        assert row["is_real_time"] == True  # noqa: E712
        assert row["is_cancelled"] == False  # noqa: E712
        assert row["delay_minutes"] == pytest.approx(5.0, abs=0.2)

    def test_delay_minutes_negative_for_early(self):
        dep = _make_departure()
        # Actual is 2 min before planned
        dep["SysActualDepartureDate"] = dep["SysPlannedDepartureDate"] - 1_200_000_000
        df = _parse_departures([dep])
        assert df.iloc[0]["delay_minutes"] < 0

    def test_sorted_by_actual_departure(self):
        base = 638_529_990_000_000_000
        deps = [_make_departure(SysActualDepartureDate=base + i * 600_000_000, UniqueId=f"dep-{i}") for i in [3, 1, 2]]
        df = _parse_departures(deps)
        times = df["actual_departure"].tolist()
        assert times == sorted(times)

    def test_bool_types(self):
        df = _parse_departures([_make_departure()])
        assert df["is_real_time"].dtype == bool
        assert df["is_cancelled"].dtype == bool


# ---------------------------------------------------------------------------
# departures: validate_departures
# ---------------------------------------------------------------------------


class TestValidateDepartures:
    def _valid_df(self):
        return pd.DataFrame(
            {
                "planned_departure": pd.to_datetime(["2024-06-01 17:30:00"], utc=True),
                "actual_departure": pd.to_datetime(["2024-06-01 17:35:00"], utc=True),
                "service": ["Bus 11E"],
                "destination": ["Belfast, CastleCourt"],
                "transport_mode": ["Bus"],
                "is_real_time": [True],
                "is_cancelled": [False],
                "delay_minutes": [5.0],
                "unique_id": ["dep-001"],
            }
        )

    def test_valid_passes(self):
        assert validate_departures(self._valid_df()) is True

    def test_empty_passes(self):
        df = self._valid_df().iloc[0:0]
        assert validate_departures(df) is True

    def test_missing_column_raises(self):
        df = self._valid_df().drop(columns=["service"])
        with pytest.raises(TranslinkValidationError, match="missing columns"):
            validate_departures(df)

    def test_non_datetime_raises(self):
        df = self._valid_df()
        df["planned_departure"] = "not a datetime"
        with pytest.raises(TranslinkValidationError, match="datetime"):
            validate_departures(df)

    def test_non_bool_is_real_time_raises(self):
        df = self._valid_df()
        df["is_real_time"] = df["is_real_time"].astype(int)
        with pytest.raises(TranslinkValidationError, match="is_real_time"):
            validate_departures(df)

    def test_non_bool_is_cancelled_raises(self):
        df = self._valid_df()
        df["is_cancelled"] = df["is_cancelled"].astype(int)
        with pytest.raises(TranslinkValidationError, match="is_cancelled"):
            validate_departures(df)


# ---------------------------------------------------------------------------
# stops: _ing_to_wgs84
# ---------------------------------------------------------------------------


class TestIngToWgs84:
    def test_victoria_square(self):
        # Victoria Square, Belfast: approximately 54.595°N, 5.924°W
        # ING coordinates from CIF
        lat, lon = _ing_to_wgs84(333_889, 374_332)
        assert abs(lat - 54.595) < 0.05
        assert abs(lon - (-5.924)) < 0.05

    def test_north_of_ni(self):
        # Somewhere in Antrim coast area — check broadly within NI bounds
        lat, lon = _ing_to_wgs84(310_000, 430_000)
        assert 54.0 < lat < 56.0
        assert -9.0 < lon < -5.0

    def test_returns_tuple(self):
        result = _ing_to_wgs84(300_000, 380_000)
        assert len(result) == 2
        lat, lon = result
        assert isinstance(lat, float)
        assert isinstance(lon, float)


# ---------------------------------------------------------------------------
# stops: _parse_cif_zip
# ---------------------------------------------------------------------------


def _make_cif_zip(cif_content: str) -> bytes:
    """Build an in-memory zip containing a single .cif file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.cif", cif_content)
    return buf.getvalue()


class TestParseCifZip:
    def test_ql_record(self):
        # Format: QLN<atco:12><name:48>...
        cif = "QLN700000001661Victoria Square Victoria Street               \n"
        stops = _parse_cif_zip(_make_cif_zip(cif))
        assert "700000001661" in stops
        assert stops["700000001661"]["name"] == "Victoria Square Victoria Street"

    def test_qb_record(self):
        # Format: QBN<atco:12><easting:8><northing:8>...
        cif = "QBN700000001661333889  374332  Northern Ireland\n"
        stops = _parse_cif_zip(_make_cif_zip(cif))
        assert "700000001661" in stops
        assert stops["700000001661"]["easting"] == 333889
        assert stops["700000001661"]["northing"] == 374332

    def test_ql_and_qb_combined(self):
        cif = (
            "QLN700000001661Victoria Square Victoria Street               \n"
            "QBN700000001661333889  374332  Northern Ireland\n"
        )
        stops = _parse_cif_zip(_make_cif_zip(cif))
        assert stops["700000001661"]["name"] == "Victoria Square Victoria Street"
        assert stops["700000001661"]["easting"] == 333889

    def test_ignores_non_cif_files(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "not a cif file")
            zf.writestr("data.cif", "QLN700000001661Test Stop                                        \n")
        stops = _parse_cif_zip(buf.getvalue())
        assert "700000001661" in stops

    def test_empty_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        stops = _parse_cif_zip(buf.getvalue())
        assert stops == {}

    def test_bad_qb_coords_skipped(self):
        cif = "QBN700000001661BADVAL  BADVAL  Northern Ireland\n"
        stops = _parse_cif_zip(_make_cif_zip(cif))
        # Record exists but has no easting/northing (bad coords skipped)
        assert "700000001661" not in stops or "easting" not in stops.get("700000001661", {})


# ---------------------------------------------------------------------------
# timetable: _parse_time_at
# ---------------------------------------------------------------------------


class TestParseTimeAt:
    def test_4digit_daytime(self):
        hhmm, pos = _parse_time_at("1035xyz", 0)
        assert hhmm == "1035"
        assert pos == 4

    def test_3digit_early_morning(self):
        # '519' = 05:19 (no leading zero for hours < 10)
        hhmm, pos = _parse_time_at("519B", 0)
        assert hhmm == "0519"
        assert pos == 3

    def test_evening_2xxx(self):
        hhmm, pos = _parse_time_at("2026B", 0)
        assert hhmm == "2026"
        assert pos == 4

    def test_next_day_notation(self):
        # 2601 = 26:01 = 02:01 next day (valid in CIF night services)
        hhmm, pos = _parse_time_at("2601B", 0)
        assert hhmm == "2601"
        assert pos == 4

    def test_blank_returns_empty(self):
        hhmm, pos = _parse_time_at("   B", 0)
        assert hhmm == ""

    def test_packed_arrive_depart(self):
        # QI7-style: arrive=0519 (3 chars) + depart=0519 (4 chars) packed = '5190519B'
        arr, p1 = _parse_time_at("5190519B", 0)
        dep, p2 = _parse_time_at("5190519B", p1)
        assert arr == "0519"
        assert dep == "0519"

    def test_packed_1xxx_times(self):
        # arrive=1035 (4 chars) + depart=1035 packed = '10351035B'
        arr, p1 = _parse_time_at("10351035B", 0)
        dep, _ = _parse_time_at("10351035B", p1)
        assert arr == "1035"
        assert dep == "1035"


# ---------------------------------------------------------------------------
# timetable: _trip_atco_to_stop_atco
# ---------------------------------------------------------------------------


class TestTripAtcoToStopAtco:
    def test_prepends_7(self):
        assert _trip_atco_to_stop_atco("00000009264") == "700000009264"

    def test_12_chars(self):
        assert len(_trip_atco_to_stop_atco("00000001514")) == 12


# ---------------------------------------------------------------------------
# timetable: _parse_cif_trips
# ---------------------------------------------------------------------------


def _make_trip_zip(cif_content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.cif", cif_content)
    return buf.getvalue()


class TestParseCifTrips:
    def test_single_trip_parsed(self):
        # Real CIF format: trip ATCOs are 11 digits at [3:14]; times start at [14].
        # Stop 700000001436 → trip code '00000001436'; 'QO7' + '00000001436' + '0545...'
        cif = (
            "QDNMET 11B OCity Centre - Springmartin\n"
            "QSNMET 0545  20260413999999991111100 X11B       DD              O\n"
            "QO700000001436"
            "0545CHCT1  \n"
            "QT700000001425"
            "0559   T1  \n"
        )
        trips = _parse_cif_trips(_make_trip_zip(cif))
        assert len(trips) == 1
        t = trips[0]
        assert t.operator == "MET"
        assert t.line == "11B"
        assert t.direction == "O"
        assert len(t.stops) == 2
        assert t.stops[0].atco == "700000001436"
        assert t.stops[0].depart == "0545"
        assert t.stops[1].atco == "700000001425"
        assert t.stops[1].arrive == "0559"

    def test_empty_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        trips = _parse_cif_trips(buf.getvalue())
        assert trips == []

    def test_trip_without_stops_excluded(self):
        # QD with no QO/QI/QT
        cif = "QDNMET 11B OCity Centre - Springmartin\n"
        trips = _parse_cif_trips(_make_trip_zip(cif))
        assert trips == []

    def test_multiple_trips(self):
        cif = (
            "QDNMET 11B OCity Centre - Springmartin\n"
            "QSNMET 0545  20260413999999991111100 X11B       DD              O\n"
            "QO700000014360545T1  \n"
            "QT700000014250559   T1  \n"
            "QDNMET G1  OGlider Route\n"
            "QSNGDR 0518  20260413999999991111100 XG1        GDR             O\n"
            "QO700000001646051 T1  \n"
            "QT700000016011054 T1  \n"
        )
        trips = _parse_cif_trips(_make_trip_zip(cif))
        lines = [t.line for t in trips]
        assert "11B" in lines
        assert "G1" in lines


# ---------------------------------------------------------------------------
# timetable: find_direct_trips
# ---------------------------------------------------------------------------


class TestFindDirectTrips:
    def _make_index_with_trip(self, stops: list[str]) -> None:
        """Inject a synthetic trip into the module's trip index for testing."""
        from bolster.data_sources.translink import timetable

        trip = Trip(
            operator="MET",
            line="11E",
            description="City Centre - Test",
            depart_hhmm="0900",
            date_from="20260101",
            date_to="99999999",
            days="1111100",
            direction="O",
        )
        for i, atco in enumerate(stops):
            if i == 0:
                ts = TripStop(atco=atco, arrive="", depart="0900", seq=0)
            elif i == len(stops) - 1:
                ts = TripStop(atco=atco, arrive="0930", depart="", seq=i)
            else:
                t = f"09{10 + i:02d}"
                ts = TripStop(atco=atco, arrive=t, depart=t, seq=i)
            trip.stops.append(ts)
        # Inject into the global index
        index = {atco: [] for atco in stops}
        for ts in trip.stops:
            index[ts.atco].append((trip, ts))
        timetable._TRIP_INDEX = index

    def test_direct_trip_found(self):
        stops = ["700000001000", "700000001001", "700000001002"]
        self._make_index_with_trip(stops)
        results = find_direct_trips("700000001000", "700000001002")
        assert len(results) == 1
        trip, orig_ts, dest_ts = results[0]
        assert trip.line == "11E"
        assert orig_ts.atco == "700000001000"
        assert dest_ts.atco == "700000001002"
        assert orig_ts.seq < dest_ts.seq

    def test_no_direct_trip(self):
        stops = ["700000001000", "700000001001", "700000001002"]
        self._make_index_with_trip(stops)
        results = find_direct_trips("700000001002", "700000001000")  # wrong direction
        assert results == []

    def test_unknown_stop_returns_empty(self):
        stops = ["700000001000", "700000001001"]
        self._make_index_with_trip(stops)
        results = find_direct_trips("700000009999", "700000001001")
        assert results == []


class TestFindStopFuzzy:
    """find_stop_fuzzy's own grouping logic — stops.get_stop_dataframe monkeypatched
    to a small synthetic table, so no network/CIF download is involved."""

    @staticmethod
    def _stub_dataframe(monkeypatch):
        df = pd.DataFrame(
            {"name": ["Victoria Street", "Victoria Street", "Victoria Road", "City Hall"]},
            index=pd.Index(["700000000001", "700000000002", "700000000003", "700000000004"], name="atco_code"),
        )
        monkeypatch.setattr(stops, "get_stop_dataframe", lambda: df)

    def test_expands_a_matched_name_to_every_sharing_atco_code(self, monkeypatch):
        self._stub_dataframe(monkeypatch)

        results = find_stop_fuzzy("victoria street")

        matching = [r for r in results if r["name"] == "Victoria Street"]
        assert {r["atco_code"] for r in matching} == {"700000000001", "700000000002"}
        assert all(r["score"] == 1.0 for r in matching)

    def test_results_sorted_best_first(self, monkeypatch):
        self._stub_dataframe(monkeypatch)

        results = find_stop_fuzzy("victoria", cutoff=0.0)

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_no_match_returns_empty(self, monkeypatch):
        self._stub_dataframe(monkeypatch)

        assert find_stop_fuzzy("completely unrelated query") == []


# ---------------------------------------------------------------------------
# timetable: find_trip_for_vehicle
# ---------------------------------------------------------------------------


class TestFindTripForVehicle:
    def _inject(self, monkeypatch, trips: list[Trip]) -> None:
        from bolster.data_sources.translink import timetable

        index: dict[tuple[str, str], list[Trip]] = {}
        for trip in trips:
            index.setdefault((trip.line.upper(), trip.depart_hhmm), []).append(trip)
        monkeypatch.setattr(timetable, "_TRIPS_BY_LINE_DEPARTURE", index)

    def _trip(self, **overrides) -> Trip:
        defaults = {
            "operator": "MET",
            "line": "11E",
            "description": "Test",
            "depart_hhmm": "0846",
            "date_from": "20260101",
            "date_to": "99999999",
            "days": "1111111",  # valid every day, to avoid weekday flakiness
            "direction": "I",
        }
        defaults.update(overrides)
        return Trip(**defaults)

    def test_exact_line_and_time_match(self, monkeypatch):
        from datetime import UTC, datetime

        trip = self._trip()
        self._inject(monkeypatch, [trip])
        results = find_trip_for_vehicle("11E", "0846", ref_dt=datetime.now(tz=UTC))
        assert results == [trip]

    def test_case_insensitive_line(self, monkeypatch):
        from datetime import UTC, datetime

        trip = self._trip(line="11E")
        self._inject(monkeypatch, [trip])
        results = find_trip_for_vehicle("11e", "0846", ref_dt=datetime.now(tz=UTC))
        assert results == [trip]

    def test_no_match_for_different_time(self, monkeypatch):
        from datetime import UTC, datetime

        self._inject(monkeypatch, [self._trip(depart_hhmm="0846")])
        results = find_trip_for_vehicle("11E", "0900", ref_dt=datetime.now(tz=UTC))
        assert results == []

    def test_excludes_trip_not_running_today(self, monkeypatch):
        from datetime import UTC, datetime

        # Saturday-only trip (index 5), checked against a Monday reference.
        sat_only = self._trip(days="0000010")
        self._inject(monkeypatch, [sat_only])
        monday = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)  # a real Monday
        assert monday.weekday() == 0
        results = find_trip_for_vehicle("11E", "0846", ref_dt=monday)
        assert results == []

    def test_excludes_trip_outside_date_range(self, monkeypatch):
        from datetime import UTC, datetime

        expired = self._trip(date_from="20200101", date_to="20200201")
        self._inject(monkeypatch, [expired])
        results = find_trip_for_vehicle("11E", "0846", ref_dt=datetime.now(tz=UTC))
        assert results == []

    def test_multiple_same_time_variants_both_returned(self, monkeypatch):
        from datetime import UTC, datetime

        a = self._trip(description="Variant A")
        b = self._trip(description="Variant B")
        self._inject(monkeypatch, [a, b])
        results = find_trip_for_vehicle("11E", "0846", ref_dt=datetime.now(tz=UTC))
        assert len(results) == 2

    def test_unknown_line_returns_empty(self, monkeypatch):
        from datetime import UTC, datetime

        self._inject(monkeypatch, [self._trip()])
        results = find_trip_for_vehicle("99Z", "0846", ref_dt=datetime.now(tz=UTC))
        assert results == []


# ---------------------------------------------------------------------------
# departures: _resolve_target_atcos
# ---------------------------------------------------------------------------


class TestResolveTargetAtcos:
    def _patch_stop_df(self, monkeypatch, rows: dict[str, str]) -> None:
        from bolster.data_sources.translink import departures

        df = pd.DataFrame({"name": list(rows.values())}, index=pd.Index(list(rows.keys()), name="atco_code"))
        monkeypatch.setattr(departures, "get_stop_dataframe", lambda: df)

    def test_strips_locality_prefix_for_confident_match(self, monkeypatch):
        self._patch_stop_df(
            monkeypatch,
            {"700000001038": "Cambrai Street", "700000000001": "Clara Street", "700000000002": "Agra Street"},
        )
        result = _resolve_target_atcos("Shankill, Cambria Street")
        assert result == ["700000001038"]

    def test_exact_match_without_locality_prefix(self, monkeypatch):
        self._patch_stop_df(monkeypatch, {"700000000003": "Castle Street"})
        result = _resolve_target_atcos("Castle Street")
        assert result == ["700000000003"]

    def test_ties_at_top_score_all_included(self, monkeypatch):
        # Both genuinely contain "Agnes Street" as a substring -> both score 1.0.
        self._patch_stop_df(
            monkeypatch,
            {"700000000004": "Agnes Street", "700000000005": "Crumlin Road (Agnes Street)"},
        )
        result = _resolve_target_atcos("Oldpark, Agnes Street")
        assert set(result) == {"700000000004", "700000000005"}

    def test_no_confident_match_returns_empty(self, monkeypatch):
        self._patch_stop_df(monkeypatch, {"700000000006": "Completely Unrelated Road"})
        result = _resolve_target_atcos("Some Other Place, Nonexistent Street")
        assert result == []


# ---------------------------------------------------------------------------
# departures: _hhmm_to_timestamp
# ---------------------------------------------------------------------------


class TestHhmmToTimestamp:
    def test_applies_bst_offset_during_bst(self):
        # CIF/VMI HHMM is genuine Europe/London local time -- confirmed against a
        # vehicle whose live current_stop was the target stop itself (so its CIF
        # passing time must be close to real "now"). During BST, local "09:04"
        # must land on UTC 08:04, not 09:04 (a since-reverted version of this
        # function wrongly treated HHMM as already-UTC, off by exactly one DST
        # hour -- a bug masked for a while by 20-minute-interval schedules, where
        # a 60-minute error still coincidentally lines up with some real row).
        ref = pd.Timestamp("2026-10-02 08:26:00", tz="UTC")  # a BST-era date
        result = _hhmm_to_timestamp("0904", ref)
        assert result == pd.Timestamp("2026-10-02 08:04:00", tz="UTC")

    def test_same_calendar_date_as_ref(self):
        ref = pd.Timestamp("2026-10-02 23:50:00", tz="UTC")
        result = _hhmm_to_timestamp("0100", ref)
        assert result.tz_convert("Europe/London").date() == ref.tz_convert("Europe/London").date()

    def test_invalid_hhmm_returns_none(self):
        ref = pd.Timestamp("2026-10-02 08:00:00", tz="UTC")
        assert _hhmm_to_timestamp("not-a-time", ref) is None


# ---------------------------------------------------------------------------
# departures: _verified_passing_time
# ---------------------------------------------------------------------------


class TestVerifiedPassingTime:
    def _inject_trip(self, monkeypatch, trip: Trip) -> None:
        from bolster.data_sources.translink import timetable

        monkeypatch.setattr(timetable, "_TRIPS_BY_LINE_DEPARTURE", {(trip.line.upper(), trip.depart_hhmm): [trip]})

    def _trip_with_stops(self) -> Trip:
        trip = Trip(
            operator="MET",
            line="11E",
            description="Test",
            depart_hhmm="0846",
            date_from="20260101",
            date_to="99999999",
            days="1111111",
            direction="I",
        )
        trip.stops = [
            TripStop(atco="700000000001", arrive="", depart="0846", seq=0),
            TripStop(atco="700000001006", arrive="0903", depart="0903", seq=12),  # Ardoyne Shops
            TripStop(atco="700000001036", arrive="0903", depart="0903", seq=13),  # Ardoyne
            TripStop(atco="700000001038", arrive="0904", depart="0904", seq=14),  # Cambrai Street
        ]
        return trip

    def test_vehicle_before_target_is_verified(self, monkeypatch):
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        result = _verified_passing_time("11E", "0846", "700000001006", "700000001036", ["700000001038"], ref_dt)
        # "0904" is Europe/London local; during BST that's UTC 08:04, not 09:04.
        assert result == pd.Timestamp("2026-10-02 08:04:00", tz="UTC")

    def test_vehicle_after_target_is_rejected(self, monkeypatch):
        # The real Ardoyne/Cambria regression case, inverted: vehicle already past
        # the target stop (seq 14) must not be verified, even though line/direction
        # and timing proximity would otherwise look plausible.
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        # Vehicle at seq 14 (the target itself) or beyond has already passed/reached it
        # going further; simulate "beyond" with a stop not before the target.
        result = _verified_passing_time(
            "11E",
            "0846",
            None,
            "700000000999",  # unknown stop, not in this trip -> can't verify as "before"
            ["700000001038"],
            ref_dt,
        )
        assert result is None

    def test_no_target_atcos_returns_none(self, monkeypatch):
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        result = _verified_passing_time("11E", "0846", "700000001006", "700000001036", [], ref_dt)
        assert result is None

    def test_trip_not_calling_at_target_returns_none(self, monkeypatch):
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        result = _verified_passing_time("11E", "0846", "700000001006", "700000001036", ["700000099999"], ref_dt)
        assert result is None

    def test_positive_delay_shifts_predicted_time_later(self, monkeypatch):
        # Found live: the journey-planner's own delay field doesn't reliably
        # reflect a significantly late bus, but the vehicle's own VMI
        # delay_seconds does -- this is what makes that usable.
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        result = _verified_passing_time(
            "11E", "0846", "700000001006", "700000001036", ["700000001038"], ref_dt, vehicle_delay_seconds=300
        )
        assert result == pd.Timestamp("2026-10-02 08:09:00", tz="UTC")  # 08:04 + 5 min

    def test_negative_delay_shifts_predicted_time_earlier(self, monkeypatch):
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        result = _verified_passing_time(
            "11E", "0846", "700000001006", "700000001036", ["700000001038"], ref_dt, vehicle_delay_seconds=-60
        )
        assert result == pd.Timestamp("2026-10-02 08:03:00", tz="UTC")  # 08:04 - 1 min

    def test_missing_delay_falls_back_to_unadjusted_cif_time(self, monkeypatch):
        # VMI's realtime_available=False case: delay_seconds is NA, not 0 -- must
        # not error, and must not be treated as a real zero-delay measurement.
        trip = self._trip_with_stops()
        self._inject_trip(monkeypatch, trip)
        ref_dt = pd.Timestamp("2026-10-02 08:50:00", tz="UTC")
        result = _verified_passing_time(
            "11E", "0846", "700000001006", "700000001036", ["700000001038"], ref_dt, vehicle_delay_seconds=pd.NA
        )
        assert result == pd.Timestamp("2026-10-02 08:04:00", tz="UTC")


# ---------------------------------------------------------------------------
# departures: _greedy_assign_vehicles
# ---------------------------------------------------------------------------


class TestGreedyAssignVehicles:
    def test_closest_pair_wins(self):
        pairs = [
            (0, 10, pd.Timedelta(minutes=5)),
            (0, 11, pd.Timedelta(minutes=1)),
        ]
        assert _greedy_assign_vehicles(pairs) == {0: 11}

    def test_vehicle_not_reused_across_departures(self):
        # The exact bug found live: TM-3587 within 60 min of two adjacent
        # departures must only be assigned to the closer one.
        pairs = [
            (0, 99, pd.Timedelta(minutes=2)),
            (1, 99, pd.Timedelta(minutes=20)),
        ]
        result = _greedy_assign_vehicles(pairs)
        assert result == {0: 99}
        assert 1 not in result

    def test_departure_not_matched_twice(self):
        pairs = [
            (0, 1, pd.Timedelta(minutes=10)),
            (0, 2, pd.Timedelta(minutes=5)),
        ]
        result = _greedy_assign_vehicles(pairs)
        assert len(result) == 1
        assert result[0] == 2

    def test_empty_pairs_returns_empty(self):
        assert _greedy_assign_vehicles([]) == {}
