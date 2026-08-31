"""Data integrity tests for the NI Road Safety Partnership module.

These tests exercise the live OpenDataNI publication — no mocks. The two
published batches are downloaded once per class and cached.
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import road_safety_partnership as rsp
from bolster.data_sources.psni._base import PSNIValidationError


@pytest.mark.network
class TestDatasetDiscovery:
    """The CKAN discovery layer must find both published batches."""

    @pytest.fixture(scope="class")
    def datasets(self):
        return rsp._get_available_datasets()

    def test_finds_at_least_two_batches(self, datasets):
        assert len(datasets) >= 2

    def test_every_batch_has_a_csv_url(self, datasets):
        for dataset in datasets:
            assert dataset["url"].lower().endswith(".csv")

    def test_year_ranges_are_ordered_and_sane(self, datasets):
        for dataset in datasets:
            assert 2010 <= dataset["start_year"] <= dataset["end_year"] <= 2035

    def test_batches_do_not_overlap(self, datasets):
        """Each year must be published by exactly one batch."""
        for earlier, later in zip(datasets, datasets[1:], strict=False):
            assert earlier["end_year"] < later["start_year"], f"{earlier['url']} overlaps {later['url']}"

    def test_available_years_are_contiguous(self):
        years = rsp.get_available_years()
        assert years == list(range(min(years), max(years) + 1))

    def test_coverage_starts_in_2011(self):
        assert min(rsp.get_available_years()) == 2011


@pytest.mark.network
class TestDetectionIntegrity:
    """Record-level detections must be well-formed."""

    @pytest.fixture(scope="class")
    def detections(self):
        return rsp.get_detections(year=2024)

    def test_required_columns_present(self, detections):
        for column in rsp.REQUIRED_COLUMNS:
            assert column in detections.columns

    def test_has_substantial_volume(self, detections):
        assert len(detections) > 10_000

    def test_validates(self, detections):
        assert rsp.validate_data(detections) is True

    def test_all_rows_are_the_requested_year(self, detections):
        assert (detections["year"] == 2024).all()

    def test_dates_parse(self, detections):
        assert detections["offence_date"].notna().all()
        assert pd.api.types.is_datetime64_any_dtype(detections["offence_date"])

    def test_camera_types_are_known(self, detections):
        assert set(detections["camera_type"]) <= set(rsp.CAMERA_TYPES)

    def test_outcomes_are_known(self, detections):
        assert set(detections["outcome"]) <= set(rsp.OUTCOMES)

    def test_age_bands_are_known(self, detections):
        assert set(detections["age_band"]) <= set(rsp.AGE_BANDS)

    def test_speed_bands_are_known(self, detections):
        assert set(detections["speed_band"].dropna()) <= set(rsp.SPEED_BANDS)

    def test_speed_limits_are_plausible(self, detections):
        limits = detections["speed_limit_mph"].dropna()
        assert limits.between(20, 70).all()

    def test_all_eleven_districts_present(self, detections):
        assert detections["district"].nunique() == 11

    def test_every_district_resolves_to_an_lgd_code(self, detections):
        assert detections["lgd_code"].notna().all()

    def test_every_district_resolves_to_a_nuts3_code(self, detections):
        assert detections["nuts3_code"].notna().all()

    def test_hours_are_valid(self, detections):
        assert detections["hour"].dropna().between(0, 23).all()

    def test_months_cover_the_full_year(self, detections):
        assert set(detections["month"].dropna()) == set(range(1, 13))

    def test_only_red_light_cameras_lack_a_speed(self, detections):
        """Speed is null exactly when the camera cannot measure speed."""
        missing = detections[detections["speed_band"].isna()]
        assert (missing["camera_type"] == rsp.NO_SPEED_CAMERA_TYPE).all()

    def test_red_light_cameras_never_record_a_speed(self, detections):
        red_light = detections[detections["camera_type"] == rsp.NO_SPEED_CAMERA_TYPE]
        assert red_light["speed_band"].isna().all()

    def test_references_unique_within_a_batch(self, detections):
        assert not detections["reference"].duplicated().any()


@pytest.mark.network
class TestHistoricalCoverage:
    """The full series must span both batches consistently."""

    @pytest.fixture(scope="class")
    def summary(self):
        return rsp.get_annual_summary()

    def test_spans_both_batches(self, summary):
        assert summary["year"].min() == 2011
        assert summary["year"].max() >= 2024

    def test_years_are_contiguous(self, summary):
        years = sorted(summary["year"])
        assert years == list(range(years[0], years[-1] + 1))

    def test_every_year_has_detections(self, summary):
        assert (summary["detections"] > 0).all()

    def test_outcome_columns_sum_to_total(self, summary):
        parts = summary["fixed_penalties"] + summary["awareness_courses"] + summary["prosecutions"]
        assert (parts == summary["detections"]).all()

    def test_prosecution_rate_is_a_percentage(self, summary):
        assert summary["prosecution_rate_pct"].between(0, 100).all()

    def test_prosecution_rate_matches_counts(self, summary):
        derived = summary["prosecutions"] / summary["detections"] * 100
        assert (derived - summary["prosecution_rate_pct"]).abs().max() < 0.01

    def test_annual_volumes_are_plausible(self, summary):
        assert summary["detections"].between(10_000, 500_000).all()

    def test_detections_have_grown(self, summary):
        """Enforcement volume in the 2020s exceeds the early 2010s."""
        early = summary[summary["year"] <= 2013]["detections"].mean()
        recent = summary[summary["year"] >= 2022]["detections"].mean()
        assert recent > early


@pytest.mark.network
class TestAggregations:
    """Aggregation helpers must preserve the underlying totals."""

    @pytest.fixture(scope="class")
    def detections(self):
        return rsp.get_detections(year=2023)

    def test_district_counts_sum_to_total(self, detections):
        by_district = rsp.get_detections_by_district(year=2023)
        assert by_district["detections"].sum() == len(detections)

    def test_district_counts_cover_all_districts(self):
        by_district = rsp.get_detections_by_district(year=2023)
        assert len(by_district) == 11

    def test_district_counts_are_sorted_descending(self):
        by_district = rsp.get_detections_by_district(year=2023)
        assert by_district["detections"].is_monotonic_decreasing

    def test_camera_counts_sum_to_total(self, detections):
        by_camera = rsp.get_detections_by_camera_type(year=2023)
        assert by_camera["detections"].sum() == len(detections)

    def test_mobile_cameras_dominate(self):
        """Mobile deployments account for the large majority of detections."""
        by_camera = rsp.get_detections_by_camera_type(year=2023)
        top = by_camera.nlargest(1, "detections").iloc[0]
        assert top["camera_type"] == "Mobile Speed Camera"
        assert top["detections"] / by_camera["detections"].sum() > 0.5

    def test_speed_distribution_excludes_red_light(self, detections):
        dist = rsp.get_speed_distribution(year=2023)
        expected = len(detections[detections["speed_band"].notna()])
        assert dist["detections"].sum() == expected

    def test_speed_distribution_bands_are_ordered(self):
        dist = rsp.get_speed_distribution(year=2023)
        assert isinstance(dist["speed_band"].dtype, pd.CategoricalDtype)
        assert dist["speed_band"].cat.ordered

    def test_detected_speed_always_exceeds_the_limit(self):
        """A detection band's lower bound must be above the posted limit."""
        dist = rsp.get_speed_distribution(year=2023)
        lower = dist["speed_band"].astype(str).str.split("-").str[0].astype(int)
        assert (lower > dist["speed_limit_mph"]).all()

    def test_demographics_sum_to_total(self, detections):
        demo = rsp.get_offender_demographics(year=2023)
        assert demo["detections"].sum() == len(detections)

    def test_hourly_profile_sums_to_total(self, detections):
        profile = rsp.get_hourly_profile(year=2023)
        expected = len(detections[detections["hour"].notna()])
        assert profile["detections"].sum() == expected

    def test_hourly_profile_covers_all_hours(self):
        profile = rsp.get_hourly_profile(year=2023)
        assert set(profile["hour"]) == set(range(24))

    def test_daytime_detections_exceed_overnight(self):
        """Mobile camera deployment is concentrated in working hours."""
        profile = rsp.get_hourly_profile(year=2023).set_index("hour")["detections"]
        daytime = profile.loc[9:17].sum()
        overnight = profile.loc[0:5].sum()
        assert daytime > overnight


@pytest.mark.network
class TestFiltering:
    """Filter arguments must narrow the result without corrupting it."""

    def test_camera_type_filter(self):
        df = rsp.get_detections(year=2024, camera_type="Fixed Speed Camera")
        assert not df.empty
        assert (df["camera_type"] == "Fixed Speed Camera").all()

    def test_district_filter_accepts_canonical_name(self):
        df = rsp.get_detections(year=2024, district="Belfast City")
        assert not df.empty
        assert (df["district"] == "Belfast City").all()

    def test_district_filter_accepts_published_name(self):
        """The published "and" spelling must resolve to the canonical form."""
        df = rsp.get_detections(year=2024, district="Mid and East Antrim")
        assert not df.empty
        assert (df["district"] == "Mid & East Antrim").all()

    def test_unknown_year_raises(self):
        from bolster.data_sources.psni._base import PSNIDataNotFoundError

        with pytest.raises(PSNIDataNotFoundError):
            rsp.get_detections(year=1999)

    def test_earliest_year_loads_from_the_first_batch(self):
        df = rsp.get_detections(year=2011)
        assert not df.empty
        assert (df["year"] == 2011).all()


class TestNormalisation:
    """Unit tests for the header and label normalisation helpers."""

    @pytest.mark.parametrize(
        "published,canonical",
        [
            ("Antrim and Newtownabbey", "Antrim & Newtownabbey"),
            ("Ards and North Down", "Ards & North Down"),
            ("Armagh City, Banbridge and Craigavon", "Armagh City Banbridge & Craigavon"),
            ("Belfast City", "Belfast City"),
            ("Causeway Coast and Glens", "Causeway Coast & Glens"),
            ("Derry City and Strabane", "Derry City & Strabane"),
            ("Fermanagh and Omagh", "Fermanagh & Omagh"),
            ("Lisburn and Castlereagh City", "Lisburn & Castlereagh City"),
            ("Mid and East Antrim", "Mid & East Antrim"),
            ("Mid Ulster", "Mid Ulster"),
            ("Newry Mourne and Down", "Newry Mourne & Down"),
        ],
    )
    def test_district_canonicalisation(self, published, canonical):
        assert rsp._canonicalise_district(published) == canonical

    def test_every_canonical_district_has_an_lgd_code(self):
        from bolster.data_sources.psni._base import LGD_CODES

        published = [
            "Antrim and Newtownabbey",
            "Ards and North Down",
            "Armagh City, Banbridge and Craigavon",
            "Belfast City",
            "Causeway Coast and Glens",
            "Derry City and Strabane",
            "Fermanagh and Omagh",
            "Lisburn and Castlereagh City",
            "Mid and East Antrim",
            "Mid Ulster",
            "Newry Mourne and Down",
        ]
        assert {rsp._canonicalise_district(p) for p in published} == set(LGD_CODES)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("31-40 mph", "31-40 mph"),
            ("61-70mph", "61-70 mph"),
            ("71-80mph", "71-80 mph"),
            ("111-120mph", "111-120 mph"),
            ("110-120mph", "111-120 mph"),
            ("  51-60 mph  ", "51-60 mph"),
        ],
    )
    def test_speed_band_normalisation(self, raw, expected):
        assert rsp._normalise_speed_band(raw) == expected

    def test_speed_band_normalisation_passes_through_nulls(self):
        assert rsp._normalise_speed_band(None) is None
        assert rsp._normalise_speed_band(float("nan")) is None

    def test_normalised_bands_are_all_known(self):
        for raw in ["31-40 mph", "61-70mph", "110-120mph", "121-130 mph"]:
            assert rsp._normalise_speed_band(raw) in rsp.SPEED_BANDS

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ID", "reference"),
            ("RefNo", "reference"),
            ("Offence Date", "offence_date"),
            ("OffenceDate", "offence_date"),
            ("Camera Type", "camera_type"),
            ("CameraType", "camera_type"),
            ("Speed limit (mph)", "speed_limit_mph"),
            ("SpeedLimit(mph)", "speed_limit_mph"),
            ("Speed detected (grouped)", "speed_band"),
            ("speed_grouped", "speed_band"),
            ("Local Government District", "district"),
            ("Offender Age (grouped)", "age_band"),
            ("AGE", "age_band"),
            ("Offender Gender", "gender"),
            ("offender_sex", "gender"),
        ],
    )
    def test_column_normalisation(self, raw, expected):
        assert rsp._normalise_column(raw) == expected

    def test_unknown_column_falls_back_to_snake_case(self):
        assert rsp._normalise_column("Some New Column") == "some_new_column"

    def test_both_batches_normalise_to_the_same_schema(self):
        """Every required column must be reachable from either header set."""
        batch_2011 = [
            "ID",
            "Offence Date",
            "Offence Time",
            "Camera Type",
            "Speed limit (mph)",
            "Speed detected (grouped)",
            "Outcome",
            "Local Government District",
            "Offender Age (grouped)",
            "Offender Gender",
        ]
        batch_2020 = [
            "RefNo",
            "OffenceDate",
            "OffenceTime",
            "CameraType",
            "SpeedLimit(mph)",
            "speed_grouped",
            "Outcome",
            "Local Government District",
            "AGE",
            "offender_sex",
        ]
        assert [rsp._normalise_column(c) for c in batch_2011] == [rsp._normalise_column(c) for c in batch_2020]


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    @staticmethod
    def _valid_frame():
        return pd.DataFrame(
            {
                "reference": [1, 2],
                "offence_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "camera_type": ["Mobile Speed Camera", "Red Light Running Camera"],
                "outcome": ["Fixed Penalty Notice Issued", "Referred for Prosecution"],
                "district": ["Belfast City", "Mid Ulster"],
                "year": [2024, 2024],
                "speed_band": ["31-40 mph", None],
            }
        )

    def test_valid_frame_passes(self):
        assert rsp.validate_data(self._valid_frame()) is True

    def test_empty_dataframe_rejected(self):
        with pytest.raises(PSNIValidationError, match="empty"):
            rsp.validate_data(pd.DataFrame())

    def test_missing_columns_rejected(self):
        df = self._valid_frame().drop(columns=["district"])
        with pytest.raises(PSNIValidationError, match="Missing required columns"):
            rsp.validate_data(df)

    def test_unparseable_dates_rejected(self):
        df = self._valid_frame()
        df.loc[0, "offence_date"] = pd.NaT
        with pytest.raises(PSNIValidationError, match="offence dates"):
            rsp.validate_data(df)

    def test_unknown_camera_type_rejected(self):
        df = self._valid_frame()
        df.loc[0, "camera_type"] = "Drone"
        with pytest.raises(PSNIValidationError, match="Unknown camera types"):
            rsp.validate_data(df)

    def test_unknown_outcome_rejected(self):
        df = self._valid_frame()
        df.loc[0, "outcome"] = "Let off with a warning"
        with pytest.raises(PSNIValidationError, match="Unknown outcomes"):
            rsp.validate_data(df)

    def test_unknown_speed_band_rejected(self):
        df = self._valid_frame()
        df.loc[0, "speed_band"] = "200-300 mph"
        with pytest.raises(PSNIValidationError, match="Unknown speed bands"):
            rsp.validate_data(df)

    def test_missing_district_rejected(self):
        df = self._valid_frame()
        df.loc[0, "district"] = None
        with pytest.raises(PSNIValidationError, match="missing districts"):
            rsp.validate_data(df)

    def test_frame_without_speed_band_column_passes(self):
        """speed_band is optional — validation must not require it."""
        df = self._valid_frame().drop(columns=["speed_band"])
        assert rsp.validate_data(df) is True


class TestConstants:
    """The declared vocabularies must be internally consistent."""

    def test_speed_bands_are_ascending(self):
        lower = [int(band.split("-")[0]) for band in rsp.SPEED_BANDS]
        assert lower == sorted(lower)

    def test_speed_band_fixes_target_known_bands(self):
        assert set(rsp.SPEED_BAND_FIXES.values()) <= set(rsp.SPEED_BANDS)

    def test_speed_band_fixes_do_not_shadow_valid_bands(self):
        assert not set(rsp.SPEED_BAND_FIXES) & set(rsp.SPEED_BANDS)

    def test_no_speed_camera_type_is_a_known_camera(self):
        assert rsp.NO_SPEED_CAMERA_TYPE in rsp.CAMERA_TYPES

    def test_column_aliases_cover_the_required_columns(self):
        derived = {"year"}
        assert set(rsp.REQUIRED_COLUMNS) - derived <= set(rsp.COLUMN_ALIASES.values())

    def test_age_bands_place_unknown_last(self):
        assert rsp.AGE_BANDS[-1] == "Unknown"


@pytest.mark.network
class TestCrossValidation:
    """RSP detections must agree with the other PSNI and NISRA sources."""

    @pytest.fixture(scope="class")
    def rsp_districts(self):
        return rsp.get_detections_by_district(year=2023)

    @pytest.fixture(scope="class")
    def rtc_districts(self):
        from bolster.data_sources.psni import road_traffic_collisions

        return road_traffic_collisions.get_casualties_by_district(2023)

    def test_district_sets_match_road_traffic_collisions(self, rsp_districts, rtc_districts):
        """Both PSNI sources must name the 11 districts identically."""
        assert set(rsp_districts["district"]) == set(rtc_districts["district"])

    def test_lgd_codes_match_road_traffic_collisions(self, rsp_districts, rtc_districts):
        rsp_map = dict(zip(rsp_districts["district"], rsp_districts["lgd_code"], strict=False))
        rtc_map = dict(zip(rtc_districts["district"], rtc_districts["lgd_code"], strict=False))
        assert rsp_map == rtc_map

    def test_detection_years_overlap_collision_years(self):
        """RSP and RTC must share reporting years for joint analysis."""
        from bolster.data_sources.psni import road_traffic_collisions

        rsp_years = set(rsp.get_available_years())
        rtc_years = set(road_traffic_collisions.get_available_years())
        assert len(rsp_years & rtc_years) >= 5

    def test_detections_vastly_exceed_injury_collisions(self):
        """Camera detections are an order of magnitude more common than injury collisions."""
        from bolster.data_sources.psni import road_traffic_collisions

        rsp_annual = rsp.get_annual_summary()
        rtc_annual = road_traffic_collisions.get_annual_summary()

        shared = set(rsp_annual["year"]) & set(rtc_annual["year"])
        assert shared

        for year in sorted(shared):
            detections = int(rsp_annual.loc[rsp_annual["year"] == year, "detections"].iloc[0])
            collisions = int(rtc_annual.loc[rtc_annual["year"] == year, "collisions"].iloc[0])
            assert detections > collisions * 5, f"{year}: {detections} detections vs {collisions} collisions"

    def test_districts_resolve_against_the_shared_lgd_lookup(self, rsp_districts):
        """Every district must map onto the project-wide LGD code table."""
        from bolster.data_sources.psni.crime_statistics import get_lgd_code

        for district, code in zip(rsp_districts["district"], rsp_districts["lgd_code"], strict=False):
            assert get_lgd_code(district) == code

    def test_detections_per_capita_are_plausible(self, rsp_districts):
        """Detections per head must sit within a believable band for every district."""
        from bolster.data_sources.nisra import population

        pop = population.get_latest_population()
        pop = pop[
            (pop["sex"] == "All persons") & (pop["area"].str.contains("Local Government")) & (pop["year"] == 2023)
        ]
        by_lgd = pop.groupby("area_code")["population"].sum()

        if by_lgd.empty:
            pytest.skip("LGD-level population estimates unavailable for 2023")

        for code, detections in zip(rsp_districts["lgd_code"], rsp_districts["detections"], strict=False):
            if code not in by_lgd.index:
                continue
            per_1000 = detections / by_lgd[code] * 1000
            assert 0 < per_1000 < 200, f"{code}: {per_1000:.1f} detections per 1,000 residents"
