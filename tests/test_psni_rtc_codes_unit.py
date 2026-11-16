"""Offline unit tests for the PSNI Road Traffic Collision code maps, decoding and HGV helpers.

No network access: the OpenDataNI search, the CSV downloads and the per-year loaders are replaced
with small hand-built inputs.
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import road_traffic_collisions as rtc

# Vehicle type (v_type) and casualty class (c_class) lists as printed in PSNI's yearly Data Guides.
# The guides for 2013 to 2025 carry identical lists. Transcribed independently of the module so that
# an accidental edit to the module's maps is caught.
GUIDE_VEHICLE_TYPES = {
    0: "Unknown",
    1: "Pedal cycle",
    2: "Motorcycle - moped",
    4: "Motorcycle (under 125cc)",
    5: "Motorcycle (125cc and above)",
    6: "Invalid vehicle / other 3 wheeler",
    7: "Car - taxi (hackney)",
    8: "Car",
    9: "Motor caravan",
    14: "Other motor vehicle",
    15: "Goods 3.5 tonnes or less",
    16: "Goods exceeding 3.5 tonnes but less than 7.5 tonnes",
    17: "Goods 7.5 tonnes or over",
    18: "Car (used as taxi)",
    19: "Minibus (8-16 passengers)",
    20: "Bus or coach (17+ passengers)",
    21: "Ridden horse",
    22: "Other non motor vehicle",
    23: "Motorcycle (engine size unknown)",
    24: "Goods vehicle (gross weight unknown)",
    25: "Agricultural vehicle",
}
GUIDE_CASUALTY_CLASSES = {
    1: "Driver",
    2: "Pillion passenger",
    3: "Vehicle passenger - front",
    4: "Vehicle passenger - rear",
    5: "Pedestrian",
    6: "Motorcyclist",
    7: "Pedal cyclist",
}


class TestCodeMaps:
    def test_vehicle_type_codes_match_the_data_guide(self):
        assert rtc.VEHICLE_TYPE_CODES == GUIDE_VEHICLE_TYPES

    def test_casualty_class_codes_match_the_data_guide(self):
        assert rtc.CASUALTY_CLASS_CODES == GUIDE_CASUALTY_CLASSES

    def test_labels_are_unique(self):
        assert len(set(rtc.VEHICLE_TYPE_CODES.values())) == len(rtc.VEHICLE_TYPE_CODES)
        assert len(set(rtc.CASUALTY_CLASS_CODES.values())) == len(rtc.CASUALTY_CLASS_CODES)

    @pytest.mark.parametrize("code", [3, 10, 11, 12, 13])
    def test_codes_the_guide_does_not_list_are_unmapped(self, code):
        assert code not in rtc.VEHICLE_TYPE_CODES

    def test_pedal_cyclist_has_a_casualty_class(self):
        assert rtc.CASUALTY_CLASS_CODES[7] == "Pedal cyclist"

    def test_hgv_codes_are_goods_over_3_5_tonnes_including_unknown_weight(self):
        assert frozenset({16, 17, 24}) == rtc.HGV_VEHICLE_TYPE_CODES
        for code in rtc.HGV_VEHICLE_TYPE_CODES:
            assert rtc.VEHICLE_TYPE_CODES[code].startswith("Goods")
        assert 15 not in rtc.HGV_VEHICLE_TYPE_CODES  # 3.5 tonnes or less


class TestDecodeCodes:
    def test_integer_codes(self):
        labels = rtc._decode_codes(pd.Series([8, 1, 24]), rtc.VEHICLE_TYPE_CODES)
        assert labels.tolist() == ["Car", "Pedal cycle", "Goods vehicle (gross weight unknown)"]

    def test_text_column_with_a_stray_blank(self):
        # Some years' files hold a blank cell, which loads the whole column as text
        labels = rtc._decode_codes(pd.Series(["8", " ", "17", ""]), rtc.VEHICLE_TYPE_CODES)
        assert labels.tolist() == ["Car", "Not recorded", "Goods 7.5 tonnes or over", "Not recorded"]

    def test_unlisted_code_is_labelled_not_dropped(self):
        labels = rtc._decode_codes(pd.Series([8, 99, 3]), rtc.VEHICLE_TYPE_CODES)
        assert labels.tolist() == ["Car", "Unknown (code 99)", "Unknown (code 3)"]

    def test_missing_values(self):
        labels = rtc._decode_codes(pd.Series([None, float("nan"), pd.NA, 5], dtype="object"), rtc.VEHICLE_TYPE_CODES)
        assert labels.tolist() == ["Not recorded", "Not recorded", "Not recorded", "Motorcycle (125cc and above)"]

    def test_float_codes_from_a_numeric_column_with_nan(self):
        labels = rtc._decode_codes(pd.Series([8.0, float("nan"), 23.0]), rtc.VEHICLE_TYPE_CODES)
        assert labels.tolist() == ["Car", "Not recorded", "Motorcycle (engine size unknown)"]

    def test_keeps_index_and_length_and_never_returns_nan(self):
        codes = pd.Series([8, 99, None, "x"], index=[10, 20, 30, 40], dtype="object")
        labels = rtc._decode_codes(codes, rtc.VEHICLE_TYPE_CODES)
        assert list(labels.index) == [10, 20, 30, 40]
        assert not labels.isna().any()

    def test_to_code_is_nullable_integer(self):
        coded = rtc._to_code(pd.Series(["8", "", "x", "24"]))
        assert str(coded.dtype) == "Int64"
        assert coded.tolist()[0] == 8
        assert coded.isna().tolist() == [False, True, True, False]


class TestDatasetDiscovery:
    @staticmethod
    def _package(name: str, title: str) -> dict:
        return {"id": name, "name": name, "title": title, "resources": []}

    def test_is_collision_dataset(self):
        base = "police-recorded-injury-road-traffic-collision-statistics-northern-ireland"
        assert rtc._is_collision_dataset(base)  # the 2015 dataset has no year suffix
        assert rtc._is_collision_dataset(f"{base}-2024")
        assert not rtc._is_collision_dataset("northern-ireland-road-safety-partnership-2011-2021")
        assert not rtc._is_collision_dataset("northern-ireland-road-safety-partnership-statistics-2020-2024")

    def test_available_years_exclude_road_safety_partnership_datasets(self, monkeypatch):
        base = "police-recorded-injury-road-traffic-collision-statistics-northern-ireland"
        packages = [
            self._package(
                f"{base}-2024", "Police Recorded Injury Road Traffic Collision Statistics Northern Ireland 2024"
            ),
            self._package(
                f"{base}-2020", "Police Recorded Injury Road Traffic Collision Statistics Northern Ireland 2020"
            ),
            self._package(base, "Police Recorded Injury Road Traffic Collision Statistics Northern Ireland 2015"),
            self._package(
                "northern-ireland-road-safety-partnership-2011-2021",
                "Northern Ireland Road Safety Partnership 2011-2019",
            ),
            self._package(
                "northern-ireland-road-safety-partnership-statistics-2020-2024",
                "Northern Ireland Road Safety Partnership statistics 2020-2024",
            ),
        ]

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"success": True, "result": {"results": packages}}

        monkeypatch.setattr(rtc.session, "get", lambda *args, **kwargs: FakeResponse())
        assert rtc.get_available_years() == [2024, 2020, 2015]


def _vehicles() -> pd.DataFrame:
    """Four collisions: 1 has a 3.5t-or-less van, 2 an HGV, 3 a weight-unknown goods vehicle, 4 a car."""
    codes = [15, 17, 24, 8, 8]
    refs = [1, 2, 3, 4, 2]
    df = pd.DataFrame({"ref": refs, "vehicle_type_code": pd.array(codes, dtype="Int64")})
    df["is_hgv"] = df["vehicle_type_code"].isin(rtc.HGV_VEHICLE_TYPE_CODES)
    return df


def _casualties() -> pd.DataFrame:
    # (ref, severity): collision 1 has a van (not an HGV), 2 an HGV and a car, 3 an unknown-weight goods vehicle
    rows = [(1, 1), (2, 1), (2, 2), (2, 3), (3, 2), (3, 3), (4, 1), (4, 2)]
    return pd.DataFrame(rows, columns=["ref", "severity_code"])


class TestHgvKsiCasualties:
    @pytest.fixture(autouse=True)
    def _loaders(self, monkeypatch):
        monkeypatch.setattr(rtc, "get_vehicles", lambda year, force_refresh=False: _vehicles())
        monkeypatch.setattr(rtc, "get_casualties", lambda year, force_refresh=False: _casualties())
        monkeypatch.setattr(rtc, "get_available_years", lambda: [2024, 2023])

    def test_counts_ksi_casualties_in_collisions_involving_an_hgv(self):
        result = rtc.get_hgv_ksi_casualties([2024])
        row = result.iloc[0]
        # Collision 2 (code 17): fatal + serious; collision 3 (code 24): serious. Slight casualties and
        # the van and car collisions are excluded.
        assert row["ksi_casualties"] == 3
        assert row["fatal"] == 1
        assert row["serious"] == 2
        assert row["all_ksi_casualties"] == 6
        assert row["hgv_share_pct"] == 50.0

    def test_defaults_to_every_available_year_in_order(self):
        result = rtc.get_hgv_ksi_casualties()
        assert result["year"].tolist() == [2023, 2024]

    def test_does_not_swallow_a_missing_year(self, monkeypatch):
        def missing(year, force_refresh=False):
            raise rtc.PSNIDataNotFoundError(f"No data available for year {year}")

        monkeypatch.setattr(rtc, "get_vehicles", missing)
        with pytest.raises(rtc.PSNIDataNotFoundError, match="2024"):
            rtc.get_hgv_ksi_casualties([2024])


class TestRoadUserGrouping:
    def test_pedal_cyclists_are_counted(self, monkeypatch):
        casualties = pd.DataFrame(
            {
                "casualty_id": range(1, 8),
                "casualty_class_code": pd.array([1, 3, 4, 5, 6, 7, 7], dtype="Int64"),
                "severity_code": [3, 3, 2, 1, 2, 3, 3],
            }
        )
        casualties["casualty_class"] = rtc._decode_codes(casualties["casualty_class_code"], rtc.CASUALTY_CLASS_CODES)
        monkeypatch.setattr(rtc, "get_casualties", lambda year=None, force_refresh=False: casualties)

        result = rtc.get_casualties_by_road_user(2024).set_index("casualty_class")
        assert result.loc["Pedal cyclist", "casualties"] == 2
        assert result["casualties"].sum() == len(casualties)  # nothing dropped
        assert "Motorcyclist" in result.index
        assert "Vehicle passenger - front" in result.index


class TestLoadersWithStrayBlankCells:
    def _patch_download(self, monkeypatch, tmp_path, name: str, text: str):
        path = tmp_path / name
        path.write_text(text)
        monkeypatch.setattr(rtc, "_get_resource_url", lambda year, kind: "unused")
        monkeypatch.setattr(rtc, "download_file", lambda *args, **kwargs: path)

    def test_vehicles_decode_when_v_type_has_a_blank_cell(self, monkeypatch, tmp_path):
        # A blank in v_type loads the column as text; the codes must still decode
        csv = "a_year,a_ref,v_id,v_type\n2018,1,1,8\n2018,2,1,\n2018,3,1,17\n2018,4,1,24\n2018,5,1,15\n"
        self._patch_download(monkeypatch, tmp_path, "vehicle2018.csv", csv)

        df = rtc.get_vehicles(2018)
        assert str(df["vehicle_type_code"].dtype) == "Int64"
        assert df["vehicle_type"].tolist() == [
            "Car",
            "Not recorded",
            "Goods 7.5 tonnes or over",
            "Goods vehicle (gross weight unknown)",
            "Goods 3.5 tonnes or less",
        ]
        assert df["is_hgv"].tolist() == [False, False, True, True, False]

    def test_vehicles_without_decoding_keep_numeric_codes(self, monkeypatch, tmp_path):
        csv = "a_year,a_ref,v_id,v_type\n2018,1,1,8\n2018,2,1,\n"
        self._patch_download(monkeypatch, tmp_path, "vehicle2018.csv", csv)

        df = rtc.get_vehicles(2018, decode_values=False)
        assert "vehicle_type" not in df.columns
        assert df["vehicle_type_code"].isna().tolist() == [False, True]

    def test_casualties_decode_with_the_guide_classes(self, monkeypatch, tmp_path):
        csv = (
            "a_year,a_ref,v_id,c_id,c_class,c_sex,c_agegroup,c_sever,c_vtype\n"
            "2024,1,1,1,1,1,3,1,8\n"
            "2024,1,1,2,3,2,4,3,8\n"
            "2024,2,1,1,7,1,5,2,1\n"
            "2024,3,1,1,6,1,5,2,5\n"
            "2024,4,1,1,9,1,5,2,99\n"
        )
        self._patch_download(monkeypatch, tmp_path, "casualty2024.csv", csv)

        df = rtc.get_casualties(2024)
        assert df["casualty_class"].tolist() == [
            "Driver",
            "Vehicle passenger - front",
            "Pedal cyclist",
            "Motorcyclist",
            "Unknown (code 9)",
        ]
        assert df["vehicle_type"].tolist()[-1] == "Unknown (code 99)"
        assert df["vehicle_type"].tolist()[3] == "Motorcycle (125cc and above)"
