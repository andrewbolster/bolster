"""Data integrity tests for PSNI Security Situation Statistics.

The live-data classes hit the real PSNI workbook so a change in publication
layout or sheet structure surfaces here rather than downstream.

Note: the source article page sits behind Cloudflare and can 403 from a
low-reputation IP even when the site isn't actually blocking automated
access (see the module docstring and issue #1887's history) -- a discovery
failure here in one environment doesn't necessarily mean the module is
broken; check whether the same call succeeds in CI before concluding
otherwise. ``TestInternals``/``TestValidation`` run in-process against
constructed frames and never touch the network.
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import security_situation as ss
from bolster.data_sources.psni._base import PSNIDataNotFoundError, PSNIValidationError


class TestDiscovery:
    def test_workbook_url_found(self) -> None:
        url = ss.find_latest_workbook_url()
        assert url.startswith("https://") and url.lower().endswith(".xls")


class TestSeriesIntegrity:
    @pytest.fixture(scope="class")
    def deaths(self) -> pd.DataFrame:
        return ss.get_deaths()

    @pytest.fixture(scope="class")
    def incidents(self) -> pd.DataFrame:
        return ss.get_security_related_incidents()

    @pytest.fixture(scope="class")
    def paramilitary(self) -> pd.DataFrame:
        return ss.get_paramilitary_style_attacks()

    @pytest.fixture(scope="class")
    def finds(self) -> pd.DataFrame:
        return ss.get_firearms_and_explosives_finds()

    @pytest.fixture(scope="class")
    def terrorism_act(self) -> pd.DataFrame:
        return ss.get_terrorism_act_arrests()

    def test_deaths_covers_the_troubles_onward(self, deaths: pd.DataFrame) -> None:
        assert deaths.year.min() == 1969
        assert deaths.resolution.eq("annual").all()

    def test_deaths_no_year_gaps(self, deaths: pd.DataFrame) -> None:
        years = sorted(deaths.year.unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_incidents_transitions_from_annual_to_monthly(self, incidents: pd.DataFrame) -> None:
        annual = incidents[incidents.resolution == "annual"]
        monthly = incidents[incidents.resolution == "monthly"]
        assert not annual.empty and not monthly.empty
        assert annual.year.max() < monthly.date.min().year
        # No year should appear in both resolutions -- that would mean a
        # derived rollup row leaked through the annual/monthly split.
        assert not (set(annual.year) & set(monthly.year))

    def test_incidents_no_future_placeholder_rows(self, incidents: pd.DataFrame) -> None:
        metric_cols = [c for c in incidents.columns if c not in ("date", "year", "resolution")]
        assert incidents[metric_cols].notna().any(axis=1).all()

    def test_paramilitary_columns_present(self, paramilitary: pd.DataFrame) -> None:
        assert {
            "shootings_total",
            "shootings_loyalist",
            "shootings_republican",
            "assaults_total",
            "assaults_loyalist",
            "assaults_republican",
            "total_casualties",
        } <= set(paramilitary.columns)

    def test_paramilitary_loyalist_plus_republican_at_most_total(self, paramilitary: pd.DataFrame) -> None:
        # Attribution is "as perceived by PSNI" and some incidents may be
        # attributed to neither, so parts can be <= the total, not ==.
        sub = paramilitary.dropna(subset=["shootings_total", "shootings_loyalist", "shootings_republican"])
        assert (sub.shootings_loyalist + sub.shootings_republican <= sub.shootings_total + 1e-9).all()

    def test_finds_transitions_from_annual_to_monthly(self, finds: pd.DataFrame) -> None:
        annual = finds[finds.resolution == "annual"]
        monthly = finds[finds.resolution == "monthly"]
        assert not annual.empty and not monthly.empty
        assert annual.year.max() < monthly.date.min().year

    def test_terrorism_act_starts_2001_monthly_only(self, terrorism_act: pd.DataFrame) -> None:
        assert terrorism_act.resolution.eq("monthly").all()
        assert terrorism_act.date.min().year == 2001

    def test_all_series_reach_a_recent_period(self, deaths, incidents, paramilitary, finds, terrorism_act) -> None:
        # The workbook is a monthly-updated edition; each series should
        # extend to within the last couple of years, not stop short.
        recent_cutoff = pd.Timestamp.now() - pd.DateOffset(years=2)
        for series in (incidents, paramilitary, finds, terrorism_act):
            assert series.date.max() >= recent_cutoff
        assert deaths.year.max() >= recent_cutoff.year - 1

    @pytest.mark.parametrize(
        "accessor",
        [
            ss.get_deaths,
            ss.get_security_related_incidents,
            ss.get_paramilitary_style_attacks,
            ss.get_firearms_and_explosives_finds,
            ss.get_terrorism_act_arrests,
        ],
    )
    def test_validation_passes(self, accessor) -> None:
        assert ss.validate_data(accessor()) is True


class TestDistrictBreakdown:
    @pytest.fixture(scope="class")
    def districts(self) -> pd.DataFrame:
        return ss.get_district_breakdown()

    def test_covers_all_eleven_districts_plus_total(self, districts: pd.DataFrame) -> None:
        assert len(districts) == 12
        assert "NORTHERN IRELAND" in set(districts.district)

    def test_lgd_codes_resolve_for_real_districts(self, districts: pd.DataFrame) -> None:
        real_districts = districts[districts.district != "NORTHERN IRELAND"]
        assert real_districts.lgd_code.notna().all()

    def test_ni_total_row_has_no_lgd_code(self, districts: pd.DataFrame) -> None:
        ni_row = districts[districts.district == "NORTHERN IRELAND"]
        assert ni_row.lgd_code.isna().all()

    def test_district_sums_match_ni_total(self, districts: pd.DataFrame) -> None:
        metric_cols = [c for c in districts.columns if c not in ("district", "lgd_code")]
        real_districts = districts[districts.district != "NORTHERN IRELAND"]
        ni_row = districts[districts.district == "NORTHERN IRELAND"].iloc[0]
        for column in metric_cols:
            assert real_districts[column].sum() == pytest.approx(ni_row[column])

    def test_validation_passes(self, districts: pd.DataFrame) -> None:
        assert ss.validate_data(districts) is True


class TestGetAllData:
    def test_returns_all_six_topics(self) -> None:
        data = ss.get_all_data()
        assert set(data) == {
            "deaths",
            "security_related_incidents",
            "paramilitary_style_attacks",
            "firearms_and_explosives_finds",
            "terrorism_act_arrests",
            "district_breakdown",
        }
        for df in data.values():
            assert ss.validate_data(df) is True


class TestInternals:
    """Network-free checks of the pure-Python parsing helpers."""

    def test_detect_header_start_skips_lone_section_title(self) -> None:
        rows = [
            ["Section title", None, None],
            [None, None, None],
            [None, "Header A", "Header B"],
            ["TOTAL 2020", 1, 2],
        ]
        df = pd.DataFrame(rows)
        assert ss._detect_header_start(df) == 2

    def test_detect_header_start_requires_two_populated_columns(self) -> None:
        rows = [
            [None, "Lone label spanning one column", None],
            [None, "Header A", "Header B"],
        ]
        df = pd.DataFrame(rows)
        assert ss._detect_header_start(df) == 1

    def test_detect_header_start_raises_when_absent(self) -> None:
        df = pd.DataFrame([["just", "text", "rows"], ["no", "header", "here"]])
        with pytest.raises(PSNIDataNotFoundError, match="No header row"):
            ss._detect_header_start(df)

    def test_combine_headers_single_row(self) -> None:
        df = pd.DataFrame([[None, "A", "B"]])
        assert ss._combine_headers(df, 0, 1) == ["", "A", "B"]

    def test_combine_headers_forward_fills_group_row(self) -> None:
        df = pd.DataFrame(
            [
                [None, "Group X", None, "Group Y"],
                [None, "Sub 1", "Sub 2", "Sub 3"],
            ]
        )
        assert ss._combine_headers(df, 0, 2) == ["", "Group X Sub 1", "Group X Sub 2", "Group Y Sub 3"]

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("TOTAL 1990", "annual_candidate"),
            ("TOTAL 1990 to date", None),
            ("Financial Year 2025/26 to date", None),
            (None, None),
        ],
    )
    def test_classify_label_strings(self, label, expected) -> None:
        assert ss._classify_label(label) == expected

    def test_classify_label_timestamp_is_monthly(self) -> None:
        import datetime as dt

        assert ss._classify_label(pd.Timestamp("2020-01-01")) == "monthly"
        assert ss._classify_label(dt.datetime(2020, 1, 1)) == "monthly"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("-", None),
            ("", None),
            (None, None),
            ("1,234", 1234.0),
            (5, 5.0),
            (5.5, 5.5),
            ("not a number", None),
        ],
    )
    def test_parse_numeric(self, value, expected) -> None:
        assert ss._parse_numeric(value) == expected

    def test_annual_rows_after_monthly_era_are_dropped(self) -> None:
        # Regression test for the core row-classification rule: a "TOTAL
        # <year>" row appearing after monthly rows have started is a derived
        # rollup and must not become a duplicate annual observation.
        rows = [
            [None, "Metric A", "Metric B"],
            ["TOTAL 1989", 10, 20],
            [pd.Timestamp("1990-01-01"), 1, 2],
            [pd.Timestamp("1990-02-01"), 2, 3],
            ["TOTAL 1990", 3, 5],
        ]
        df = pd.DataFrame(rows)
        config = {"header_rows": 1, "rename": {"Metric A": "metric_a", "Metric B": "metric_b"}}
        result = ss._parse_series_sheet(df, config)
        assert set(result.year) == {1989, 1990}
        assert len(result) == 3
        assert result[result.year == 1989].resolution.iloc[0] == "annual"
        assert result[result.year == 1990].resolution.eq("monthly").all()

    def test_latest_district_sheet_picks_max_fiscal_year(self) -> None:
        class _FakeWorkbook:
            sheet_names = ["Breakdown by District 2024.25", "Breakdown by District 2026.27", "Other Sheet"]

        assert ss._latest_district_sheet(_FakeWorkbook()) == "Breakdown by District 2026.27"

    def test_latest_district_sheet_raises_when_absent(self) -> None:
        class _FakeWorkbook:
            sheet_names = ["Other Sheet"]

        with pytest.raises(PSNIDataNotFoundError, match="district breakdown"):
            ss._latest_district_sheet(_FakeWorkbook())


class TestValidation:
    """Network-free checks of the validation guard rails."""

    def test_empty_frame_raises(self) -> None:
        with pytest.raises(PSNIValidationError, match="empty"):
            ss.validate_data(pd.DataFrame())

    def test_bad_resolution_raises(self) -> None:
        frame = pd.DataFrame({"resolution": ["monthly", "weekly"], "value": [1.0, 2.0]})
        with pytest.raises(PSNIValidationError, match="resolution"):
            ss.validate_data(frame)

    def test_unparseable_date_raises(self) -> None:
        frame = pd.DataFrame({"date": [pd.Timestamp("2020-01-01"), pd.NaT], "value": [1.0, 2.0]})
        with pytest.raises(PSNIValidationError, match="dates"):
            ss.validate_data(frame)

    def test_negative_value_raises(self) -> None:
        frame = pd.DataFrame({"value": [10.0, -1.0]})
        with pytest.raises(PSNIValidationError, match="Negative values"):
            ss.validate_data(frame)

    def test_valid_frame_passes(self) -> None:
        frame = pd.DataFrame(
            {
                "date": [pd.Timestamp("2020-01-01")],
                "year": [2020],
                "resolution": ["monthly"],
                "value": [10.0],
            }
        )
        assert ss.validate_data(frame) is True
