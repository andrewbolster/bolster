"""Data integrity tests for the PSNI hate motivated incidents and crimes data source.

Live tests read the PxStat ``HATE*`` cubes; the validation and accessor tests at
the end run on small hand-built frames and need no network.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import racial_equality_indicators as rei
from bolster.data_sources.psni import hate_crime as hc
from bolster.data_sources.psni._base import PSNIDataNotFoundError, PSNIValidationError

# Areas in each cube, not counting the Northern Ireland total row.
_AREA_COUNTS = {"assembly_area": 18, "health_trust": 5, "urban_rural": 2, "lgd": 11, "dea": 80, "ward": 462}
_CRIMES_ONLY = {"assembly_area", "health_trust", "urban_rural"}
_EXACT = [name for name, spec in hc.GEOGRAPHIES.items() if spec.parts_sum_to_ni]
_INEXACT = [name for name, spec in hc.GEOGRAPHIES.items() if not spec.parts_sum_to_ni]


class TestEveryGeography:
    """Each geography's cube, loaded and checked on its own."""

    @pytest.fixture(scope="class", params=list(hc.GEOGRAPHIES))
    def geography(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def frames(self):
        return {}

    @pytest.fixture(scope="class")
    def data(self, geography, frames):
        if geography not in frames:
            frames[geography] = hc.get_latest_hate_crime(geography)
        return frames[geography]

    def test_columns(self, data):
        assert list(data.columns) == hc.OUTPUT_COLUMNS

    def test_validates(self, data):
        assert hc.validate_hate_crime(data) is True

    def test_ni_total_row_left_out_by_default(self, data):
        assert not data["is_ni_total"].any()
        assert hc.NI_CODE not in set(data["geography_code"])

    def test_area_count(self, data, geography):
        assert data["geography_code"].nunique() == _AREA_COUNTS[geography]

    def test_financial_years_2004_05_to_latest(self, data):
        periods = sorted(data["period"].unique())
        assert len(periods) == 22
        assert periods[0] == "2004/05"
        assert data["year"].max() >= 2025
        assert sorted(data["year"].unique()) == list(range(2004, int(data["year"].max()) + 1))

    def test_measures_match_cube(self, data, geography):
        measures = set(data["measure"])
        assert measures == ({"crimes"} if geography in _CRIMES_ONLY else {"crimes", "incidents"})

    def test_all_three_motivations(self, data):
        assert set(data["motivation"]) == set(hc.MOTIVATIONS)

    def test_counts_are_whole_numbers(self, data):
        counts = data["value"].dropna()
        assert (counts >= 0).all()
        assert (counts == counts.round()).all()

    def test_one_row_per_area_series_and_year(self, data):
        key = ["geography_code", "motivation", "measure", "period"]
        assert not data.duplicated(key).any()
        # every area has a value slot for every series and every year
        series = data.groupby(["geography_code", "motivation", "measure"]).size()
        assert (series == 22).all()


class TestNorthernIrelandTotals:
    @pytest.fixture(scope="class")
    def totals(self):
        return hc.get_hate_crime_ni_totals()

    def test_validates(self, totals):
        assert hc.validate_hate_crime(totals) is True

    def test_level_and_flag(self, totals):
        assert set(totals["geography_level"]) == {"northern_ireland"}
        assert totals["is_ni_total"].all()
        assert set(totals["geography_code"]) == {hc.NI_CODE}

    def test_six_series_of_22_years(self, totals):
        assert len(totals) == 6 * 22
        assert (totals.groupby(["motivation", "measure"]).size() == 22).all()

    def test_incidents_start_in_2007_08(self, totals):
        incidents = totals[totals["measure"] == "incidents"]
        first = incidents.dropna(subset=["value"]).groupby("motivation")["year"].min()
        assert (first == 2007).all()

    def test_only_published_gaps_are_missing(self, totals):
        missing = totals[totals["value"].isna()]
        crimes = missing[missing["measure"] == "crimes"]
        assert set(zip(crimes["motivation"], crimes["period"], strict=True)) == {("sectarian", "2004/05")}
        assert missing["year"].max() <= 2006

    def test_crimes_do_not_exceed_incidents(self, totals):
        wide = totals.pivot_table(index=["motivation", "period"], columns="measure", values="value").dropna()
        assert len(wide) >= 3 * 18
        assert (wide["crimes"] <= wide["incidents"]).all()

    def test_filters(self):
        racist = hc.get_hate_crime_ni_totals(motivation="racist", measure="crimes")
        assert set(racist["motivation"]) == {"racist"}
        assert set(racist["measure"]) == {"crimes"}
        assert len(racist) == 22

    def test_latest_racist_crimes_and_incidents(self, totals):
        latest = totals[totals["period"] == totals["period"].max()].set_index(["motivation", "measure"])["value"]
        assert latest[("racist", "crimes")] > 0
        assert latest[("racist", "incidents")] >= latest[("racist", "crimes")]


class TestNorthernIrelandRowAgreesAcrossCubes:
    """Every cube carries the same Northern Ireland row, so each area frame's total matches."""

    @pytest.fixture(scope="class")
    def totals(self):
        return hc.get_hate_crime_ni_totals().set_index(["motivation", "measure", "period"])["value"]

    @pytest.mark.parametrize("geography", list(hc.GEOGRAPHIES))
    def test_ni_row_matches_totals(self, geography, totals):
        with_total = hc.get_latest_hate_crime(geography, include_ni_total=True)
        ni_row = with_total[with_total["is_ni_total"]].set_index(["motivation", "measure", "period"])["value"]
        joined = pd.concat([ni_row.rename("cube"), totals.rename("lgd")], axis=1, join="inner")
        assert len(joined) == len(ni_row)
        assert (joined["cube"].fillna(-1) == joined["lgd"].fillna(-1)).all()


class TestPartsAgainstNorthernIreland:
    @pytest.mark.parametrize("geography", _EXACT)
    def test_exact_cubes_add_up(self, geography):
        gap = hc.get_unallocated(geography)
        assert len(gap) >= 100
        assert (gap["unallocated"] == 0).all()

    @pytest.fixture(scope="class")
    def inexact_gaps(self):
        return {name: hc.get_unallocated(name) for name in _INEXACT}

    @pytest.mark.parametrize("geography", _INEXACT)
    def test_inexact_cubes_fall_short_by_a_few(self, geography, inexact_gaps):
        gap = inexact_gaps[geography]
        assert (gap["unallocated"] >= 0).all()
        assert gap["unallocated"].max() <= 15
        assert (gap["unallocated"] > 0).any()
        assert set(gap["measure"]) == {"crimes"}

    def test_inexact_cubes_share_the_same_gap(self, inexact_gaps):
        key = ["motivation", "measure", "period"]
        frames = [inexact_gaps[name].set_index(key)["unallocated"] for name in _INEXACT]
        for other in frames[1:]:
            assert other.equals(frames[0])


class TestRacistCountsAgreeWithRacialEqualityIndicators:
    """Racist-motivation counts are also published as the ``RACEREI`` cube of the racial equality indicators."""

    @pytest.fixture(scope="class")
    def police(self):
        frame = rei.get_latest_racial_equality_indicators("racist_incidents_crimes")
        return frame.pivot_table(index="period", columns="statistic", values="value")

    @pytest.fixture(scope="class")
    def racist(self):
        return hc.get_hate_crime_ni_totals(motivation="racist").pivot_table(
            index="period", columns="measure", values="value"
        )

    @pytest.mark.parametrize(("measure", "statistic"), [("crimes", "RACECRREI"), ("incidents", "RACEINREI")])
    def test_northern_ireland_counts_match(self, racist, police, measure, statistic):
        joined = pd.concat([racist[measure].rename("hate"), police[statistic].rename("rei")], axis=1).dropna()
        assert len(joined) == len(police)
        assert (joined["hate"] == joined["rei"]).all()

    def test_district_racist_crimes_add_up_to_racial_equality_total(self, police):
        districts = hc.get_latest_hate_crime("lgd", motivation="racist", measure="crimes")
        by_year = districts.groupby("period")["value"].sum()
        joined = pd.concat([by_year.rename("districts"), police["RACECRREI"].rename("rei")], axis=1).dropna()
        assert len(joined) == len(police)
        assert (joined["districts"] == joined["rei"]).all()


# ---------------------------------------------------------------------------
# Offline: validation and accessors on hand-built frames
# ---------------------------------------------------------------------------


def _raw(
    stat="allraccrm",
    period="2025/26",
    codes=("N09000003", "N92000002"),
    names=("Belfast", "Northern Ireland"),
    values=(300.0, 1507.0),
):
    return pd.DataFrame(
        {
            "STATISTIC": [stat] * len(codes),
            "TLIST(A1)": [period] * len(codes),
            "LGD2014": list(codes),
            "Local Government District": list(names),
            "UNIT": ["number"] * len(codes),
            "VALUE": list(values),
        }
    )


class TestTidyCube:
    def test_columns_and_values(self):
        tidy = hc.tidy_cube("lgd", _raw())
        assert list(tidy.columns) == hc.OUTPUT_COLUMNS
        assert tidy["is_ni_total"].tolist() == [False, True]
        assert set(tidy["motivation"]) == {"racist"}
        assert set(tidy["measure"]) == {"crimes"}
        assert tidy["year"].tolist() == [2025, 2025]
        assert tidy["value"].tolist() == [300.0, 1507.0]
        assert set(tidy["cube"]) == {"HATELGD"}

    def test_every_statistic_maps(self):
        assert set(hc.STATISTICS.values()) == {(m, k) for m in hc.MOTIVATIONS for k in hc.MEASURES}

    def test_suppressed_cell_is_nan_not_zero(self):
        tidy = hc.tidy_cube("lgd", _raw(values=(None, 5.0)))
        assert tidy["value"].isna().tolist() == [True, False]

    def test_whitespace_in_labels_collapsed(self):
        tidy = hc.tidy_cube("lgd", _raw(names=("Belfast   City ", "Northern Ireland")))
        assert tidy["geography"].iloc[0] == "Belfast City"

    def test_unknown_geography_raises(self):
        with pytest.raises(ValueError, match="geography must be one of"):
            hc.tidy_cube("county", _raw())

    def test_missing_column_raises_not_found(self):
        raw = _raw().drop(columns=["LGD2014"])
        with pytest.raises(PSNIDataNotFoundError, match="HATELGD"):
            hc.tidy_cube("lgd", raw)

    def test_unknown_statistic_raises_instead_of_dropping(self):
        with pytest.raises(PSNIValidationError, match="allfaithcrm"):
            hc.tidy_cube("lgd", _raw(stat="allfaithcrm"))

    def test_bad_period_raises(self):
        with pytest.raises(PSNIValidationError, match="2025"):
            hc.tidy_cube("lgd", _raw(period="2025"))


class TestAccessorsOffline:
    @pytest.fixture
    def patched(self, monkeypatch):
        calls = []

        def fake(matrix, *args, **kwargs):
            calls.append(matrix)
            return pd.concat([_raw(), _raw(stat="allsoinc", values=(10.0, 40.0))], ignore_index=True)

        monkeypatch.setattr(hc, "read_dataset", fake)
        return calls

    def test_ni_row_excluded_by_default_and_available_on_request(self, patched):
        assert not hc.get_latest_hate_crime("lgd")["is_ni_total"].any()
        assert hc.get_latest_hate_crime("lgd", include_ni_total=True)["is_ni_total"].sum() == 2
        assert patched == ["HATELGD", "HATELGD"]

    def test_filters(self, patched):
        out = hc.get_latest_hate_crime("lgd", motivation="sexual_orientation", measure="incidents")
        assert out["value"].tolist() == [10.0]

    def test_ni_totals_use_the_lgd_cube(self, patched):
        out = hc.get_hate_crime_ni_totals()
        assert patched == ["HATELGD"]
        assert set(out["geography_level"]) == {"northern_ireland"}
        assert sorted(out["value"]) == [40.0, 1507.0]

    def test_unallocated(self, patched):
        gap = hc.get_unallocated("lgd")
        assert gap["unallocated"].tolist() == [1207.0, 30.0]
        assert list(gap.columns) == ["motivation", "measure", "period", "year", "ni_total", "allocated", "unallocated"]

    def test_unallocated_raises_when_areas_exceed_total(self, monkeypatch):
        monkeypatch.setattr(hc, "read_dataset", lambda *_a, **_k: _raw(values=(2000.0, 1507.0)))
        with pytest.raises(PSNIValidationError, match="more than Northern Ireland"):
            hc.get_unallocated("lgd")

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"geography": "county"}, "geography must be one of"),
            ({"motivation": "faith"}, "motivation must be one of"),
            ({"measure": "arrests"}, "measure must be one of"),
        ],
    )
    def test_bad_arguments_raise_before_any_request(self, patched, kwargs, message):
        with pytest.raises(ValueError, match=message):
            hc.get_latest_hate_crime(**kwargs)
        assert patched == []

    def test_unallocated_unknown_geography(self):
        with pytest.raises(ValueError, match="geography must be one of"):
            hc.get_unallocated("county")

    def test_list_geographies(self):
        listing = hc.list_geographies()
        assert list(listing.columns) == ["geography", "cube", "title", "parts_sum_to_ni"]
        assert len(listing) == len(hc.GEOGRAPHIES)
        assert listing["cube"].is_unique


class TestValidation:
    def _good(self):
        return hc.tidy_cube("lgd", _raw())

    def test_good_frame_passes(self):
        assert hc.validate_hate_crime(self._good()) is True

    def test_empty_frame_fails(self):
        with pytest.raises(PSNIValidationError, match="empty"):
            hc.validate_hate_crime(self._good().iloc[0:0])

    def test_missing_column_fails(self):
        with pytest.raises(PSNIValidationError, match="lacks column"):
            hc.validate_hate_crime(self._good().drop(columns=["period"]))

    def test_negative_count_fails(self):
        bad = self._good()
        bad.loc[0, "value"] = -1.0
        with pytest.raises(PSNIValidationError, match="negative"):
            hc.validate_hate_crime(bad)

    def test_all_nan_fails(self):
        bad = self._good()
        bad["value"] = float("nan")
        with pytest.raises(PSNIValidationError, match="no counts"):
            hc.validate_hate_crime(bad)

    def test_unknown_motivation_fails(self):
        bad = self._good()
        bad["motivation"] = "faith"
        with pytest.raises(PSNIValidationError, match="Unknown motivation"):
            hc.validate_hate_crime(bad)

    def test_duplicate_rows_fail(self):
        bad = pd.concat([self._good(), self._good()], ignore_index=True)
        with pytest.raises(PSNIValidationError, match="duplicated"):
            hc.validate_hate_crime(bad)
