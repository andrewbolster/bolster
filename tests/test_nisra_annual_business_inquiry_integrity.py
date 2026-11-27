"""Integrity and validation tests for nisra.annual_business_inquiry.

Live tests run against the NISRA PxStat API (matrices ABI01 and ABI02). Offline tests feed small
fixtures through the same code paths by replacing ``read_dataset``.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from bolster.cli import cli
from bolster.data_sources.nisra import annual_business_inquiry as abi
from bolster.data_sources.nisra import business_register, index_of_production
from bolster.data_sources.nisra._base import NISRADataError, NISRADataNotFoundError, NISRAValidationError

VALUE_COLUMNS = ["value", "ci_lower", "ci_upper", "cv_pct"]


class TestSectorIntegrity:
    @pytest.fixture(scope="class")
    def sector(self):
        return abi.get_by_sector()

    def test_required_columns(self, sector):
        assert list(sector.columns) == ["year", "measure", "sector_code", "sector", *VALUE_COLUMNS]

    def test_validate_passes(self, sector):
        assert abi.validate_data(sector, level="sector") is True

    def test_covers_every_year_measure_and_sector(self, sector):
        years = sorted(sector["year"].unique())
        assert years[0] == 2008
        assert years == list(range(years[0], years[-1] + 1))
        assert set(sector["measure"]) == set(abi.MEASURES)
        assert len(sector) == len(years) * len(abi.MEASURES) * sector["sector_code"].nunique()

    def test_sector_codes_are_industry_letters_plus_all(self, sector):
        codes = set(sector["sector_code"])
        assert {"ALL", "A", "C", "G"} <= codes
        assert all(code == "ALL" or (len(code) == 1 and code.isalpha() and code.isupper()) for code in codes)

    def test_label_travels_with_code(self, sector):
        manufacturing = sector[sector["sector_code"] == "C"]["sector"].unique()
        assert len(manufacturing) == 1
        assert "manufacturing" in manufacturing[0].lower()

    def test_all_industries_turnover_is_plausible(self, sector):
        latest = sector[(sector["sector_code"] == "ALL") & (sector["measure"] == "turnover")].sort_values("year")
        assert 50_000 < latest["value"].iloc[-1] < 250_000  # pounds sterling, millions
        assert latest["value"].iloc[-1] > latest["value"].iloc[0]

    def test_aggregate_measures_order(self, sector):
        totals = sector[sector["sector_code"] == "ALL"].pivot(index="year", columns="measure", values="value")
        assert (totals["gva"] < totals["turnover"]).all()
        assert (totals["purchases"] < totals["turnover"]).all()

    def test_interval_brackets_value(self, sector):
        complete = sector.dropna(subset=["value", "ci_lower", "ci_upper"])
        assert len(complete) > 0.95 * len(sector)
        assert (complete["ci_lower"] <= complete["value"]).all()
        assert (complete["value"] <= complete["ci_upper"]).all()

    def test_all_industries_rows_are_never_suppressed(self, sector):
        assert not sector[sector["sector_code"] == "ALL"][VALUE_COLUMNS].isna().any().any()

    def test_sections_sum_to_slightly_less_than_the_total(self, sector):
        parts = sector[sector["sector_code"] != "ALL"].groupby(["year", "measure"])["value"].sum()
        totals = sector[sector["sector_code"] == "ALL"].set_index(["year", "measure"])["value"]
        ratio = parts / totals
        assert (ratio <= 1.001).all(), ratio[ratio > 1.001]
        assert (ratio >= 0.95).all(), ratio[ratio < 0.95]

    def test_turnover_and_purchases_are_not_negative(self, sector):
        money = sector[sector["measure"].isin(["turnover", "purchases"])]
        assert (money["value"].dropna() >= 0).all()


class TestSic2Integrity:
    @pytest.fixture(scope="class")
    def sic2(self):
        return abi.get_by_sic2()

    @pytest.fixture(scope="class")
    def sector(self):
        return abi.get_by_sector()

    def test_required_columns(self, sic2):
        assert list(sic2.columns) == ["year", "measure", "sic2_code", "industry", *VALUE_COLUMNS]

    def test_validate_passes(self, sic2):
        assert abi.validate_data(sic2, level="sic2") is True

    def test_covers_every_year_measure_and_division(self, sic2):
        years = sorted(sic2["year"].unique())
        assert years == list(range(years[0], years[-1] + 1))
        assert len(sic2) == len(years) * len(abi.MEASURES) * sic2["sic2_code"].nunique()

    def test_division_codes_are_two_digit_strings(self, sic2):
        codes = set(sic2["sic2_code"]) - {"ALL"}
        assert len(codes) > 60
        assert all(len(code) == 2 and code.isdigit() for code in codes)
        assert {"01", "10", "47", "86"} <= codes

    def test_label_travels_with_code(self, sic2):
        food = sic2[sic2["sic2_code"] == "10"]["industry"].unique()
        assert len(food) == 1
        assert "food" in food[0].lower()

    def test_all_industries_matches_the_section_matrix(self, sic2, sector):
        keys = ["year", "measure"]
        left = sic2[sic2["sic2_code"] == "ALL"].set_index(keys)[VALUE_COLUMNS]
        right = sector[sector["sector_code"] == "ALL"].set_index(keys)[VALUE_COLUMNS]
        assert left.index.equals(right.index)
        np.testing.assert_allclose(left.to_numpy(), right.to_numpy(), rtol=1e-6)

    def test_suppressed_value_never_has_an_interval(self, sic2):
        suppressed = sic2[sic2["value"].isna()]
        assert not suppressed[["ci_lower", "ci_upper", "cv_pct"]].notna().any().any()

    def test_suppression_is_nan_not_zero(self, sic2):
        assert sic2["value"].isna().sum() > 0
        assert not ((sic2["value"] == 0) & sic2["ci_lower"].isna()).any()

    def test_interval_brackets_value(self, sic2):
        complete = sic2.dropna(subset=["value", "ci_lower", "ci_upper"])
        assert (complete["ci_lower"] <= complete["value"]).all()
        assert (complete["value"] <= complete["ci_upper"]).all()

    def test_unsuppressed_divisions_do_not_exceed_the_total(self, sic2):
        parts = sic2[sic2["sic2_code"] != "ALL"].groupby(["year", "measure"])["value"].sum()
        totals = sic2[sic2["sic2_code"] == "ALL"].set_index(["year", "measure"])["value"]
        assert ((parts / totals) <= 1.001).all()

    def test_turnover_and_purchases_are_not_negative_but_gva_can_be(self, sic2):
        money = sic2[sic2["measure"].isin(["turnover", "purchases"])]
        assert (money["value"].dropna() >= 0).all()
        assert (sic2[sic2["measure"] == "gva"]["value"] < 0).any()


class TestLatestAndFilters:
    def test_latest_year_is_the_maximum_year(self):
        assert abi.get_latest_year() == int(abi.get_by_sector()["year"].max())

    def test_latest_data_serves_one_stated_year(self):
        latest = abi.get_latest_data()
        assert latest["year"].nunique() == 1
        assert latest["year"].iloc[0] == abi.get_latest_year()
        assert set(latest["measure"]) == set(abi.MEASURES)

    def test_year_and_measure_filters(self):
        year = abi.get_latest_year()
        one = abi.get_by_sector(year=year, measure="GVA")
        assert set(one["year"]) == {year}
        assert set(one["measure"]) == {"gva"}

    def test_unavailable_year_raises(self):
        with pytest.raises(NISRADataNotFoundError, match="no data for 1999"):
            abi.get_by_sector(year=1999)
        with pytest.raises(NISRADataNotFoundError, match="no data for 2999"):
            abi.get_by_sic2(year=2999)

    def test_unknown_measure_and_level_raise(self):
        with pytest.raises(ValueError, match="measure"):
            abi.get_by_sector(measure="profit")
        with pytest.raises(ValueError, match="level"):
            abi.get_latest_data("lgd")


STATISTICS = [
    ("ABIVALUE", "Value"),
    ("LOWER_CONF_INTERVAL", "95% confidence interval - lower"),
    ("UPPER_CONF_INTERVAL", "95% confidence interval - upper"),
    ("CV", "Coefficient of variation"),
]
PARAMETERS = [("TURNOVER", "Turnover"), ("PURCHASES", "Purchases"), ("GVA", "Approximate gross value added")]
CODES = [("ALL", "All industries"), ("A", "(A) Agriculture, forestry and fishing"), ("C", "(C) Manufacturing")]


def _raw(years=(2023, 2024), codes=CODES, label_column="Industry sector", suppress=(), negative_gva=False):
    """Build a raw PxStat-shaped ABI frame: each dimension is a code column then its label column."""
    rows = []
    for year in years:
        for parameter, parameter_label in PARAMETERS:
            for position, (code, label) in enumerate(codes):
                value = 100.0 + 10 * position + (year - years[0])
                if negative_gva and parameter == "GVA" and code == "C":
                    value = -5.0
                cells = {
                    "ABIVALUE": value,
                    "LOWER_CONF_INTERVAL": value - 10,
                    "UPPER_CONF_INTERVAL": value + 10,
                    "CV": -5.0 if value < 0 else 5.0,
                }
                for statistic, statistic_label in STATISTICS:
                    cell = np.nan if (year, parameter, code, statistic) in suppress else cells[statistic]
                    rows.append(
                        {
                            "STATISTIC": statistic,
                            "Statistic Label": statistic_label,
                            "TLIST(A1)": year,
                            "Year": year,
                            "PARAMETER": parameter,
                            "Parameter Label": parameter_label,
                            "RUSECTION": code,
                            label_column: label,
                            "UNIT": "Percentage %" if statistic == "CV" else "Pounds Sterling (£), Millions",
                            "VALUE": cell,
                        }
                    )
    return pd.DataFrame(rows)


@pytest.fixture
def fake_matrix(monkeypatch):
    def install(raw):
        monkeypatch.setattr(abi, "read_dataset", lambda matrix: raw)

    return install


class TestOfflineShape:
    def test_pivots_statistics_into_columns_keyed_by_code(self, fake_matrix):
        fake_matrix(_raw())
        df = abi.get_by_sector()
        assert list(df.columns) == ["year", "measure", "sector_code", "sector", *VALUE_COLUMNS]
        assert len(df) == 2 * 3 * 3
        row = df[(df["year"] == 2024) & (df["measure"] == "purchases") & (df["sector_code"] == "A")].iloc[0]
        assert (row["value"], row["ci_lower"], row["ci_upper"], row["cv_pct"]) == (111.0, 101.0, 121.0, 5.0)
        assert row["sector"] == "(A) Agriculture, forestry and fishing"

    def test_orders_by_year_then_measure_then_pxstat_code_order(self, fake_matrix):
        fake_matrix(_raw())
        df = abi.get_by_sector()
        assert list(df["measure"].iloc[:9].unique()) == ["turnover", "purchases", "gva"]
        assert list(df["sector_code"].iloc[:3]) == ["ALL", "A", "C"]
        assert df["year"].is_monotonic_increasing

    def test_suppressed_cells_stay_nan(self, fake_matrix):
        suppress = {(2024, "GVA", "C", s) for s, _ in STATISTICS}
        fake_matrix(_raw(suppress=suppress))
        df = abi.get_by_sector()
        row = df[(df["year"] == 2024) & (df["measure"] == "gva") & (df["sector_code"] == "C")].iloc[0]
        assert row[VALUE_COLUMNS].isna().all()
        assert abi.validate_data(df) is True

    def test_value_without_interval_is_kept(self, fake_matrix):
        suppress = {(2024, "GVA", "C", "LOWER_CONF_INTERVAL"), (2024, "GVA", "C", "UPPER_CONF_INTERVAL")}
        fake_matrix(_raw(suppress=suppress))
        row = abi.get_by_sector(year=2024, measure="gva").query("sector_code == 'C'").iloc[0]
        assert row["value"] > 0
        assert pd.isna(row["ci_lower"]) and pd.isna(row["ci_upper"])

    def test_label_column_name_and_label_case_may_drift(self, fake_matrix):
        raw = _raw(label_column="Industry Sector")
        raw.loc[raw["RUSECTION"] == "C", "Industry Sector"] = "(C) MANUFACTURING"
        raw.loc[(raw["RUSECTION"] == "C") & (raw["TLIST(A1)"] == 2024), "Industry Sector"] = "(C) manufacturing"
        fake_matrix(raw)
        df = abi.get_by_sector()
        assert df["sector_code"].nunique() == 3
        assert len(df) == 2 * 3 * 3
        assert df[df["sector_code"] == "C"]["sector"].nunique() == 1

    def test_sic2_level_uses_sic2_columns(self, fake_matrix):
        raw = _raw().rename(columns={"RUSECTION": "SIC2", "Industry sector": "Standard industrial classification"})
        fake_matrix(raw)
        df = abi.get_by_sic2(year=2023, measure="turnover")
        assert list(df.columns)[:4] == ["year", "measure", "sic2_code", "industry"]
        assert list(df["sic2_code"]) == ["ALL", "A", "C"]

    def test_latest_data_serves_the_latest_year_only(self, fake_matrix):
        fake_matrix(_raw(years=(2022, 2023, 2024)))
        latest = abi.get_latest_data()
        assert set(latest["year"]) == {2024}
        assert abi.get_latest_year() == 2024


class TestOfflineErrors:
    def test_missing_year_is_an_error_not_a_substitution(self, fake_matrix):
        fake_matrix(_raw(years=(2023, 2024)))
        with pytest.raises(NISRADataNotFoundError, match="no data for 2025; it covers 2023 to 2024"):
            abi.get_by_sector(year=2025)

    def test_missing_statistic_is_an_error(self, fake_matrix):
        raw = _raw()
        fake_matrix(raw[raw["STATISTIC"] != "CV"])
        with pytest.raises(NISRADataError, match="layout has changed"):
            abi.get_by_sector()

    def test_unexpected_statistic_is_an_error(self, fake_matrix):
        raw = _raw()
        raw.loc[raw["STATISTIC"] == "CV", "STATISTIC"] = "RSE"
        fake_matrix(raw)
        with pytest.raises(NISRADataError, match="RSE"):
            abi.get_by_sector()

    def test_missing_code_column_is_an_error(self, fake_matrix):
        fake_matrix(_raw().drop(columns=["RUSECTION"]))
        with pytest.raises(NISRADataError, match="RUSECTION"):
            abi.get_by_sector()

    def test_duplicate_cells_are_an_error(self, fake_matrix):
        raw = _raw()
        fake_matrix(pd.concat([raw, raw.iloc[:1]], ignore_index=True))
        with pytest.raises(NISRADataError, match="duplicate"):
            abi.get_by_sector()

    def test_filters_are_validated(self, fake_matrix):
        fake_matrix(_raw())
        with pytest.raises(ValueError, match="measure"):
            abi.get_by_sector(measure="profit")
        assert set(abi.get_by_sector(measure="Turnover")["measure"]) == {"turnover"}


class TestValidateData:
    @pytest.fixture
    def good(self, fake_matrix):
        fake_matrix(_raw())
        return abi.get_by_sector()

    def test_good_frame_passes(self, good):
        assert abi.validate_data(good) is True

    def test_negative_gva_is_allowed(self, fake_matrix):
        fake_matrix(_raw(negative_gva=True))
        df = abi.get_by_sector()
        assert (df["value"] < 0).any()
        assert abi.validate_data(df) is True

    def test_missing_columns_fail(self, good):
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            abi.validate_data(good.drop(columns=["ci_upper"]))

    def test_wrong_level_columns_fail(self, good):
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            abi.validate_data(good, level="sic2")

    def test_empty_frame_fails(self, good):
        with pytest.raises(NISRAValidationError, match="empty"):
            abi.validate_data(good.iloc[0:0])

    def test_year_gap_fails(self, good):
        gappy = good.copy()
        gappy.loc[gappy["year"] == 2024, "year"] = 2026
        with pytest.raises(NISRAValidationError, match="Years missing"):
            abi.validate_data(gappy)

    def test_missing_all_industries_row_fails(self, good):
        with pytest.raises(NISRAValidationError, match="'ALL'"):
            abi.validate_data(good[~((good["sector_code"] == "ALL") & (good["measure"] == "gva"))])

    def test_negative_turnover_fails(self, good):
        bad = good.copy()
        bad.loc[(bad["measure"] == "turnover") & (bad["sector_code"] == "A"), "value"] = -1.0
        with pytest.raises(NISRAValidationError, match="negative"):
            abi.validate_data(bad)

    def test_interval_that_misses_its_value_fails(self, good):
        bad = good.copy()
        bad.loc[bad.index[0], "ci_upper"] = bad.loc[bad.index[0], "value"] - 1
        with pytest.raises(NISRAValidationError, match="outside its confidence interval"):
            abi.validate_data(bad)

    def test_interval_without_a_value_fails(self, good):
        bad = good.copy()
        bad.loc[bad.index[1], "value"] = np.nan
        with pytest.raises(NISRAValidationError, match="interval or CV but no value"):
            abi.validate_data(bad)

    def test_negative_cv_on_a_positive_value_fails(self, good):
        bad = good.copy()
        bad.loc[bad.index[1], "cv_pct"] = -1.0
        with pytest.raises(NISRAValidationError, match="negative cv_pct"):
            abi.validate_data(bad)

    def test_unknown_level_raises(self, good):
        with pytest.raises(ValueError, match="level"):
            abi.validate_data(good, level="lgd")


class TestCli:
    @pytest.fixture
    def frame(self):
        return abi._tidy(_raw(years=(2023, 2024)), "RUSECTION", "sector_code", "sector")

    def _run(self, *args, **returns):
        targets = {name: returns.get(name) for name in ("get_latest_data", "get_by_sector", "get_by_sic2")}
        with (
            patch(
                "bolster.cli.nisra_annual_business_inquiry.get_latest_data", return_value=targets["get_latest_data"]
            ) as latest,
            patch(
                "bolster.cli.nisra_annual_business_inquiry.get_by_sector", return_value=targets["get_by_sector"]
            ) as sector,
            patch("bolster.cli.nisra_annual_business_inquiry.get_by_sic2", return_value=targets["get_by_sic2"]) as sic2,
        ):
            result = CliRunner().invoke(cli, ["nisra", "annual-business-inquiry", *args])
        return result, latest, sector, sic2

    def test_help_lists_the_options(self):
        result = CliRunner().invoke(cli, ["nisra", "annual-business-inquiry", "--help"])
        assert result.exit_code == 0
        for option in ("--level", "--measure", "--year", "--all-years", "--format", "--save"):
            assert option in result.output

    def test_default_serves_the_latest_year_and_says_which(self, frame):
        latest_year = frame[frame["year"] == 2024].reset_index(drop=True)
        result, latest, sector, sic2 = self._run("--format", "csv", get_latest_data=latest_year)
        assert result.exit_code == 0, result.output
        latest.assert_called_once_with(level="sector")
        sector.assert_not_called()
        sic2.assert_not_called()
        assert "Reference year: 2024" in result.output
        assert "2024,turnover,ALL,All industries,101.0,91.0,111.0,5.0" in result.output

    def test_measure_filters_the_latest_data_case_insensitively(self, frame):
        latest_year = frame[frame["year"] == 2024].reset_index(drop=True)
        result, *_ = self._run("--measure", "GVA", "--format", "csv", get_latest_data=latest_year)
        assert result.exit_code == 0, result.output
        assert ",gva," in result.output
        assert ",turnover," not in result.output

    def test_year_and_level_call_the_matching_getter(self, frame):
        result, latest, sector, sic2 = self._run(
            "--level", "sic2", "--year", "2023", "--measure", "gva", "--format", "csv", get_by_sic2=frame
        )
        assert result.exit_code == 0, result.output
        sic2.assert_called_once_with(year=2023, measure="gva")
        latest.assert_not_called()
        sector.assert_not_called()

    def test_all_years_asks_for_no_year(self, frame):
        result, _, sector, _ = self._run("--all-years", "--format", "csv", get_by_sector=frame)
        assert result.exit_code == 0, result.output
        sector.assert_called_once_with(year=None, measure=None)
        assert "Reference year: 2023 to 2024" in result.output

    def test_year_and_all_years_conflict(self):
        result, *_ = self._run("--year", "2023", "--all-years")
        assert result.exit_code == 2
        assert "cannot be used together" in result.output

    def test_saves_csv_and_json(self, frame, tmp_path):
        latest_year = frame[frame["year"] == 2024].reset_index(drop=True)
        csv_path = tmp_path / "abi.csv"
        result, *_ = self._run("--save", str(csv_path), get_latest_data=latest_year)
        assert result.exit_code == 0, result.output
        assert pd.read_csv(csv_path).shape == latest_year.shape
        json_path = tmp_path / "abi.json"
        result, *_ = self._run("--save", str(json_path), get_latest_data=latest_year)
        assert result.exit_code == 0, result.output
        assert len(pd.read_json(json_path)) == len(latest_year)

    def test_table_output_blanks_suppressed_cells(self, frame):
        suppressed = frame[frame["year"] == 2024].reset_index(drop=True)
        suppressed.loc[0, VALUE_COLUMNS] = np.nan
        result, *_ = self._run(get_latest_data=suppressed)
        assert result.exit_code == 0, result.output
        assert "nan" not in result.output.lower()

    def test_unavailable_year_is_reported_and_aborts(self):
        with patch(
            "bolster.cli.nisra_annual_business_inquiry.get_by_sector",
            side_effect=NISRADataNotFoundError("The Annual Business Inquiry has no data for 1999"),
        ):
            result = CliRunner().invoke(cli, ["nisra", "annual-business-inquiry", "--year", "1999"])
        assert result.exit_code != 0
        assert "no data for 1999" in result.output


# Business-register industry groups against ABI section codes. Production and "other services"
# span several sections, trade spans three register groups, and the register has no counterpart
# for ABI-excluded sections K and O.
REGISTER_TO_ABI = {
    "A": ["Agriculture, forestry & fishing"],
    "B-E": ["Production"],
    "F": ["Construction"],
    "G": ["Motor trades", "Wholesale", "Retail"],
    "H": ["Transport & storage (inc. postal)"],
    "I": ["Accommodation & food services"],
    "J": ["Information & communication"],
    "L": ["Property"],
    "M": ["Professional, scientific & technical"],
    "N": ["Business administration and support services"],
    "P": ["Education"],
    "Q": ["Health"],
    "R-S": ["Arts, entertainment, recreation and other services"],
}
REGISTER_ONLY = {"Finance & insurance", "Public administration and defence"}


def _abi_codes(key):
    return {"B-E": list("BCDE"), "R-S": ["R", "S"]}.get(key, [key])


class TestCrossValidation:
    @pytest.fixture(scope="class")
    def sector(self):
        return abi.get_by_sector()

    def test_production_turnover_growth_tracks_the_index_of_production(self, sector):
        index = index_of_production.get_latest_iop().groupby("year")["ni_index"].mean().pct_change()
        turnover = (
            sector[(sector["measure"] == "turnover") & sector["sector_code"].isin(list("BCDE"))]
            .groupby("year")["value"]
            .sum()
            .pct_change()
        )
        joined = pd.concat([turnover.rename("abi"), index.rename("index")], axis=1, join="inner").dropna()
        assert len(joined) >= 10
        assert joined["abi"].corr(joined["index"]) > 0.3

    def test_register_groups_map_to_abi_sections_except_finance_and_public_administration(self, sector):
        groups = set(business_register.get_businesses_by_industry()["industry_group"]) - {"All Industries"}
        mapped = {group for groups_for_key in REGISTER_TO_ABI.values() for group in groups_for_key}
        assert mapped <= groups
        assert groups - mapped == REGISTER_ONLY
        codes = set(sector["sector_code"])
        assert all(set(_abi_codes(key)) <= codes for key in REGISTER_TO_ABI)
        assert not {"K", "O"} & codes

    def test_mapped_sections_account_for_the_all_industries_turnover(self, sector):
        latest = sector[(sector["year"] == sector["year"].max()) & (sector["measure"] == "turnover")]
        mapped_codes = [code for key in REGISTER_TO_ABI for code in _abi_codes(key)]
        mapped = latest[latest["sector_code"].isin(mapped_codes)]["value"].sum()
        total = latest[latest["sector_code"] == "ALL"]["value"].iloc[0]
        assert mapped / total == pytest.approx(1.0, abs=0.02)
