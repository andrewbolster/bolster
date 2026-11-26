"""Offline unit tests for the NISRA Economic Trade Statistics (NIETS) module.

These tests use small hand-built frames shaped like the PxStat matrices (including the quirks of the
real ones: differently cased headers, undefined flow and destination cells, suppressed values) and
patch out the network. Live checks against the real matrices are in
``test_nisra_economic_trade_statistics_integrity.py``.
"""

import numpy as np
import pandas as pd
import pytest

from bolster.data_sources.nisra import economic_trade_statistics as niets
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError

STATS = ["BESESVALUE", "LOWER_CONF_INTERVAL", "UPPER_CONF_INTERVAL", "CV", "BESESCOUNT"]


def _industry_raw(*, label_case: str = "Trade partner", years=(2024, 2025)) -> pd.DataFrame:
    """A NIETS02-shaped frame: 2 years x 2 flows x 3 destinations x 2 industries x 5 statistics."""
    rows = []
    for year in years:
        for flow, flow_label in (("SALES", "Sales"), ("PURCH", "Purchases")):
            for destination, partner in (
                ("ALL", "All countries"),
                ("NI", "Northern Ireland"),
                ("EXPORT", "Exports (outside UK)"),
            ):
                for industry, industry_label in (
                    ("ALL", "All industries"),
                    ("A", "(A) Agriculture, Forestry And Fishing"),
                ):
                    for position, statistic in enumerate(STATS):
                        value = float(100 + position + (year - 2024)) if industry == "ALL" else np.nan
                        if statistic == "LOWER_CONF_INTERVAL":
                            value = 90.0 + (year - 2024) if industry == "ALL" else np.nan
                        if statistic == "UPPER_CONF_INTERVAL":
                            value = 120.0 + (year - 2024) if industry == "ALL" else np.nan
                        rows.append(
                            {
                                "STATISTIC": statistic,
                                # Deliberately drifting statistic label case: the code is what is used.
                                "Statistic Label": "Value of Trade" if year == 2024 else "Value of trade",
                                "TLIST(A1)": year,
                                "Year": year,
                                "FLOW": flow,
                                "Flow Label": flow_label,
                                "TRANSACTION": "ALL",
                                "Transaction Label": "All Transactions",
                                "BROADDEST": destination,
                                label_case: partner,
                                "RUSECTION": industry,
                                "Industry sector": industry_label,
                                "UNIT": "x",
                                "VALUE": value,
                            }
                        )
    return pd.DataFrame(rows)


def _raw_for(table: str) -> pd.DataFrame:
    """A minimal valid raw frame for any table, built from the module's own dimension spec."""
    row = {"TLIST(A1)": 2025}
    for _, _, code_raw, label_raw in niets._DIMENSIONS[table]:
        row[code_raw] = "ALL" if code_raw not in ("FLOW",) else "SALES"
        row[label_raw] = "label"
    rows = []
    for statistic in STATS:
        if statistic == "BESESCOUNT" and table in ("partner", "sic2"):
            continue
        rows.append({**row, "STATISTIC": statistic, "VALUE": 1.0})
    return pd.DataFrame(rows)


@pytest.fixture
def patch_read(monkeypatch):
    """Patch ``read_dataset`` in the module; returns the list of (matrix, timeout) calls made."""
    calls: list[tuple[str, int]] = []

    def install(frame_for):
        def fake(matrix, timeout=30):
            calls.append((matrix, timeout))
            return frame_for(matrix)

        monkeypatch.setattr(niets, "read_dataset", fake)
        return calls

    return install


class TestTidy:
    def test_statistics_become_columns_keyed_by_code(self):
        df = niets._tidy(_industry_raw(), "industry")
        assert {"value_gbp_m", "ci_lower_gbp_m", "ci_upper_gbp_m", "cv_pct", "n_businesses"} <= set(df.columns)
        # 2 years x 2 flows x 3 destinations x 2 industries, minus purchases-EXPORT (2 years x 2 industries)
        assert len(df) == 2 * 2 * 3 * 2 - 2 * 2
        row = df[
            (df["year"] == 2025)
            & (df["flow"] == "SALES")
            & (df["destination"] == "ALL")
            & (df["industry_code"] == "ALL")
        ].iloc[0]
        assert row["value_gbp_m"] == pytest.approx(101.0)
        assert row["cv_pct"] == pytest.approx(104.0)
        assert row["destination_label"] == "All countries"

    def test_suppressed_cells_stay_nan_and_the_row_is_kept(self):
        df = niets._tidy(_industry_raw(), "industry")
        suppressed = df[df["industry_code"] == "A"]
        assert len(suppressed) > 0
        assert (
            suppressed[["value_gbp_m", "ci_lower_gbp_m", "ci_upper_gbp_m", "cv_pct", "n_businesses"]].isna().all().all()
        )

    def test_undefined_flow_destination_combinations_are_dropped(self):
        df = niets._tidy(_industry_raw(), "industry")
        pairs = set(zip(df["flow"], df["destination"], strict=True))
        assert ("SALES", "EXPORT") in pairs
        assert ("PURCH", "EXPORT") not in pairs

    def test_header_case_is_irrelevant(self):
        a = niets._tidy(_industry_raw(label_case="Trade partner"), "industry")
        b = niets._tidy(_industry_raw(label_case="TRADE PARTNER"), "industry")
        pd.testing.assert_frame_equal(a, b)

    def test_statistic_label_case_drift_does_not_matter(self):
        df = niets._tidy(_industry_raw(), "industry")
        assert df["value_gbp_m"].notna().any()

    def test_label_change_does_not_change_the_codes(self):
        raw = _industry_raw()
        raw["Industry sector"] = raw["Industry sector"].str.upper()
        a = niets._tidy(_industry_raw(), "industry")
        b = niets._tidy(raw, "industry")
        assert list(a["industry_code"]) == list(b["industry_code"])
        assert list(a["value_gbp_m"].fillna(-1)) == list(b["value_gbp_m"].fillna(-1))

    def test_matrices_without_a_count_have_no_n_businesses(self):
        assert "n_businesses" not in niets._tidy(_raw_for("partner"), "partner").columns
        assert "n_businesses" not in niets._tidy(_raw_for("sic2"), "sic2").columns
        assert "n_businesses" in niets._tidy(_raw_for("lgd"), "lgd").columns

    def test_unknown_statistic_is_an_error(self):
        raw = _industry_raw()
        raw.loc[0, "STATISTIC"] = "SOMETHING_NEW"
        with pytest.raises(NISRAValidationError, match="unexpected statistics"):
            niets._tidy(raw, "industry")

    def test_missing_column_is_an_error_naming_the_column(self):
        with pytest.raises(NISRAValidationError, match="RUSECTION"):
            niets._tidy(_industry_raw().drop(columns=["RUSECTION"]), "industry")

    def test_duplicate_cells_are_an_error(self):
        raw = _industry_raw()
        with pytest.raises(NISRAValidationError, match="more than one row"):
            niets._tidy(pd.concat([raw, raw.iloc[[0]]], ignore_index=True), "industry")


class TestGetters:
    @pytest.mark.parametrize(
        ("getter", "table", "matrix"),
        [
            (niets.get_by_partner, "partner", "NIETS01"),
            (niets.get_by_industry, "industry", "NIETS02"),
            (niets.get_by_sic2, "sic2", "NIETS03"),
            (niets.get_by_size_band, "size_band", "NIETS04"),
            (niets.get_by_lgd, "lgd", "NIETS05"),
        ],
    )
    def test_each_getter_reads_its_matrix(self, patch_read, getter, table, matrix):
        calls = patch_read(lambda _matrix: _raw_for(table))
        df = getter()
        assert calls == [(matrix, niets._TIMEOUT_SECONDS)]
        assert len(df) == 1

    def test_latest_year_is_the_newest_and_is_stated_in_the_frame(self, patch_read):
        patch_read(lambda _m: _industry_raw(years=(2023, 2024, 2025)))
        df = niets.get_by_industry(year="latest")
        assert set(df["year"]) == {2025}
        assert niets.latest_year(df) == 2025

    def test_a_missing_year_raises_and_never_substitutes_another(self, patch_read):
        patch_read(lambda _m: _industry_raw(years=(2024, 2025)))
        with pytest.raises(NISRADataNotFoundError, match=r"no data for 2030.*2024 to 2025"):
            niets.get_by_industry(year=2030)

    def test_year_none_returns_every_year(self, patch_read):
        patch_read(lambda _m: _industry_raw(years=(2024, 2025)))
        assert set(niets.get_by_industry()["year"]) == {2024, 2025}

    def test_bad_year_string_is_rejected(self, patch_read):
        patch_read(lambda _m: _industry_raw())
        with pytest.raises(ValueError, match="year must be"):
            niets.get_by_industry(year="newest")

    def test_filters_are_case_insensitive_and_combine(self, patch_read):
        patch_read(lambda _m: _industry_raw())
        df = niets.get_by_industry(year=2025, flow="Purchases", destination="ni", transaction="all")
        assert set(df["flow"]) == {"PURCH"}
        assert set(df["destination"]) == {"NI"}
        assert set(df["year"]) == {2025}

    def test_flow_words_and_codes_are_equivalent(self, patch_read):
        patch_read(lambda _m: _industry_raw())
        a = niets.get_by_industry(flow="sales")
        b = niets.get_by_industry(flow="SALES")
        pd.testing.assert_frame_equal(a, b)

    @pytest.mark.parametrize(
        "kwargs",
        [{"flow": "x"}, {"destination": "XX"}, {"transaction": "ALLISH"}],
    )
    def test_unrecognised_filters_raise_before_any_download(self, patch_read, kwargs):
        calls = patch_read(lambda _m: _industry_raw())
        with pytest.raises(ValueError, match="must be one of|must be 'sales'"):
            niets.get_by_industry(**kwargs)
        assert calls == []

    @pytest.mark.parametrize(
        ("flow", "destination"),
        [("purchases", "EXPORT"), ("sales", "IMPORT")],
    )
    def test_undefined_flow_destination_is_an_error_not_an_empty_frame(self, patch_read, flow, destination):
        calls = patch_read(lambda _m: _industry_raw())
        with pytest.raises(ValueError, match="defined for"):
            niets.get_by_industry(flow=flow, destination=destination)
        assert calls == []

    def test_get_latest_data_dispatches_and_ignores_force_refresh(self, patch_read):
        calls = patch_read(lambda _m: _raw_for("lgd"))
        df = niets.get_latest_data("lgd", force_refresh=True)
        assert calls[0][0] == "NIETS05"
        assert len(df) == 1

    def test_get_latest_data_rejects_an_unknown_table(self):
        with pytest.raises(ValueError, match="table must be one of"):
            niets.get_latest_data("nope")

    def test_latest_year_of_an_empty_frame_is_an_error(self):
        with pytest.raises(NISRADataNotFoundError):
            niets.latest_year(pd.DataFrame({"year": []}))


class TestConstants:
    def test_every_published_destination_code_is_described(self):
        published = {"ALL", "NI", "GB", "IE", "REU", "ROW", "EXTERN", "EXPORT", "IMPORT"}
        assert set(niets.DESTINATIONS) == published

    def test_matrices_cover_the_five_published_cuts(self):
        assert niets.MATRICES == {
            "partner": "NIETS01",
            "industry": "NIETS02",
            "sic2": "NIETS03",
            "size_band": "NIETS04",
            "lgd": "NIETS05",
        }


class TestValidation:
    @pytest.fixture
    def good(self) -> pd.DataFrame:
        return niets._tidy(_raw_for("lgd"), "lgd")

    def test_a_good_frame_passes(self, good):
        assert niets.validate_data(good, "lgd") is True

    def test_empty_frame_fails(self):
        assert niets.validate_data(pd.DataFrame(), "lgd") is False

    def test_unknown_table_fails(self, good):
        assert niets.validate_data(good, "nope") is False

    def test_missing_columns_fail(self, good):
        assert niets.validate_data(good.drop(columns=["lgd_code"]), "lgd") is False

    def test_negative_value_fails(self, good):
        good.loc[0, "value_gbp_m"] = -1.0
        assert niets.validate_data(good, "lgd") is False

    def test_negative_cv_fails(self, good):
        good.loc[0, "cv_pct"] = -1.0
        assert niets.validate_data(good, "lgd") is False

    def test_interval_that_does_not_bracket_the_value_fails(self, good):
        good.loc[0, "ci_lower_gbp_m"] = good.loc[0, "value_gbp_m"] + 1
        assert niets.validate_data(good, "lgd") is False

    def test_a_negative_lower_bound_is_allowed(self, good):
        good.loc[0, "ci_lower_gbp_m"] = -5.0
        assert niets.validate_data(good, "lgd") is True

    def test_suppressed_values_are_allowed(self, good):
        good.loc[0, ["value_gbp_m", "ci_lower_gbp_m", "ci_upper_gbp_m", "cv_pct"]] = np.nan
        assert niets.validate_data(good, "lgd") is True
