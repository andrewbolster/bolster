"""Offline tests for ``bolster nisra economic-trade-statistics``.

The getters are stubbed, so nothing here touches the network. Filter errors are raised before any
download, so those tests run the real getters.
"""

import json

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from bolster.cli import cli
from bolster.data_sources.nisra import economic_trade_statistics as niets

COMMAND = ["nisra", "economic-trade-statistics"]


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": [2025, 2025],
            "flow": ["SALES", "SALES"],
            "destination": ["ALL", "NI"],
            "value_gbp_m": [116769.5, np.nan],
        }
    )


@pytest.fixture
def stub(monkeypatch):
    """Replace every getter with one that records its kwargs and returns a small frame."""
    seen: list[tuple[str, dict]] = []

    def make(name):
        def getter(**kwargs):
            seen.append((name, kwargs))
            return _frame()

        return getter

    for name in ("get_by_partner", "get_by_industry", "get_by_sic2", "get_by_size_band", "get_by_lgd"):
        monkeypatch.setattr(niets, name, make(name))
    return seen


def _run(*args: str):
    return CliRunner().invoke(cli, [*COMMAND, *args])


class TestHelp:
    def test_help_lists_the_options_and_tables(self):
        result = _run("--help")
        assert result.exit_code == 0
        for text in ("--table", "--year", "--flow", "--destination", "--transaction", "NIETS05"):
            assert text in result.output

    def test_command_is_listed_under_nisra(self):
        result = CliRunner().invoke(cli, ["nisra", "--help"])
        assert "economic-trade-statistics" in result.output


class TestOutput:
    def test_default_is_the_latest_year_of_the_industry_table(self, stub):
        result = _run()
        assert result.exit_code == 0, result.output
        assert stub == [("get_by_industry", {"year": "latest", "flow": None})]
        assert "Rows: 2" in result.output
        assert "Suppressed (empty) values: 1 of 2" in result.output

    @pytest.mark.parametrize(
        ("table", "getter"),
        [
            ("partner", "get_by_partner"),
            ("industry", "get_by_industry"),
            ("sic2", "get_by_sic2"),
            ("size-band", "get_by_size_band"),
            ("lgd", "get_by_lgd"),
        ],
    )
    def test_each_table_calls_its_getter(self, stub, table, getter):
        assert _run("--table", table).exit_code == 0
        assert stub[0][0] == getter

    def test_year_all_means_every_year(self, stub):
        _run("--year", "all")
        assert stub[0][1]["year"] is None

    def test_a_numeric_year_is_passed_as_an_int(self, stub):
        _run("--year", "2019")
        assert stub[0][1]["year"] == 2019

    def test_filters_are_passed_through(self, stub):
        _run("--table", "industry", "--flow", "sales", "--destination", "IE", "--transaction", "goods")
        assert stub[0][1] == {"year": "latest", "flow": "sales", "destination": "IE", "transaction": "goods"}

    def test_csv_output(self, stub):
        result = _run("--format", "csv")
        assert "year,flow,destination,value_gbp_m" in result.output
        assert "2025,SALES,ALL,116769.5" in result.output

    def test_json_output_has_null_for_suppressed_values(self, stub):
        result = _run("--format", "json")
        records = json.loads(result.output[result.output.index("[") :])
        assert records[0]["value_gbp_m"] == 116769.5
        assert records[1]["value_gbp_m"] is None

    def test_save_writes_a_csv_file(self, stub, tmp_path):
        target = tmp_path / "out.csv"
        result = _run("--save", str(target))
        assert result.exit_code == 0
        assert pd.read_csv(target).shape == (2, 4)

    def test_save_as_json(self, stub, tmp_path):
        target = tmp_path / "out.json"
        _run("--save", str(target))
        assert json.loads(target.read_text())[1]["value_gbp_m"] is None


class TestErrors:
    def test_bad_year_is_a_usage_error(self, stub):
        result = _run("--year", "banana")
        assert result.exit_code == 2
        assert "must be a year" in result.output
        assert stub == []

    def test_destination_is_rejected_for_the_partner_table(self, stub):
        result = _run("--table", "partner", "--destination", "IE")
        assert result.exit_code == 2
        assert "not available for --table partner" in result.output
        assert stub == []

    def test_transaction_is_rejected_for_tables_without_one(self, stub):
        result = _run("--table", "lgd", "--transaction", "goods")
        assert result.exit_code == 2
        assert "only available for --table industry and size-band" in result.output

    def test_unknown_destination_is_a_usage_error_before_any_download(self):
        result = _run("--destination", "XX")
        assert result.exit_code == 2
        assert "destination must be one of" in result.output

    def test_undefined_flow_destination_is_a_usage_error_before_any_download(self):
        result = _run("--flow", "purchases", "--destination", "EXPORT")
        assert result.exit_code == 2
        assert "defined for sales only" in result.output

    def test_a_download_failure_aborts_with_troubleshooting(self, monkeypatch):
        def boom(**_kwargs):
            raise RuntimeError("PxStat is down")

        monkeypatch.setattr(niets, "get_by_industry", boom)
        result = _run()
        assert result.exit_code == 1
        assert "PxStat is down" in result.output
        assert "Troubleshooting" in result.output
