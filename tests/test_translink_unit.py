"""Unit tests for Translink data source modules — no network calls.

Covers parsing logic, ticks decoding, journey ID normalisation, direction
inference, CIF parsing, operator alias resolution, and validation edge cases.
"""

import io
import zipfile

import pandas as pd
import pytest

from bolster.data_sources.translink._base import (
    OPERATOR_ALIASES,
    TranslinkValidationError,
    net_ticks_to_timestamp,
)
from bolster.data_sources.translink.departures import (
    _extract_line,
    _parse_departures,
    validate_departures,
)
from bolster.data_sources.translink.stops import _ing_to_wgs84, _parse_cif_zip
from bolster.data_sources.translink.timetable import (
    Trip,
    TripStop,
    _parse_cif_trips,
    _parse_time_at,
    _trip_atco_to_stop_atco,
    find_direct_trips,
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
        deps = [
            _make_departure(SysActualDepartureDate=base + i * 600_000_000, UniqueId=f"dep-{i}")
            for i in [3, 1, 2]
        ]
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
            "QO700000001436" "0545CHCT1  \n"
            "QT700000001425" "0559   T1  \n"
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
