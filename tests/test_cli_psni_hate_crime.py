"""CLI tests for ``bolster psni hate-crime``; no network (the data functions are replaced)."""

import json

import pandas as pd
import pytest
from click.testing import CliRunner

from bolster.cli import cli
from bolster.data_sources.psni import hate_crime as hc


def _frame(is_total=False):
    raw = pd.DataFrame(
        {
            "STATISTIC": ["allraccrm"] * 4,
            "TLIST(A1)": ["2024/25", "2024/25", "2025/26", "2025/26"],
            "LGD2014": ["N09000003", "N92000002", "N09000003", "N92000002"],
            "Local Government District": ["Belfast", "Northern Ireland", "Belfast", "Northern Ireland"],
            "VALUE": [250.0, 1187.0, 300.0, 1507.0],
        }
    )
    tidy = hc.tidy_cube("lgd", raw)
    return tidy[tidy["is_ni_total"]] if is_total else tidy[~tidy["is_ni_total"]]


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(hc, "get_latest_hate_crime", lambda *_a, **_k: _frame())
    monkeypatch.setattr(hc, "get_hate_crime_ni_totals", lambda *_a, **_k: _frame(is_total=True))
    monkeypatch.setattr(
        hc,
        "get_unallocated",
        lambda *_a, **_k: pd.DataFrame(
            {
                "motivation": ["racist"],
                "measure": ["crimes"],
                "period": ["2025/26"],
                "year": [2025],
                "ni_total": [1507.0],
                "allocated": [1500.0],
                "unallocated": [7.0],
            }
        ),
    )


def test_help_lists_command(runner):
    result = runner.invoke(cli, ["psni", "--help"])
    assert result.exit_code == 0
    assert "hate-crime" in result.output


def test_list_geographies(runner):
    result = runner.invoke(cli, ["psni", "hate-crime", "--list-geographies"])
    assert result.exit_code == 0
    for cube in ("HATEAA", "HATEHSCT", "HATEUR", "HATELGD", "HATEDEA", "HATEWARD"):
        assert cube in result.output


def test_table_defaults_to_latest_year(runner, patched):
    result = runner.invoke(cli, ["psni", "hate-crime"])
    assert result.exit_code == 0
    # one district, one latest year (the table truncates cell text, so count rows)
    assert "1 rows" in result.output


def test_csv_keeps_every_year_and_has_no_footer(runner, patched):
    result = runner.invoke(cli, ["psni", "hate-crime", "--format", "csv"])
    assert result.exit_code == 0
    assert "2024/25" in result.output and "2025/26" in result.output
    assert "rows" not in result.output.splitlines()[-1]


def test_year_filter(runner, patched):
    result = runner.invoke(cli, ["psni", "hate-crime", "--format", "csv", "--year", "2024"])
    assert result.exit_code == 0
    assert "2024/25" in result.output
    assert "2025/26" not in result.output


def test_year_with_no_rows_is_an_error(runner, patched):
    result = runner.invoke(cli, ["psni", "hate-crime", "--year", "1999"])
    assert result.exit_code != 0
    assert "No rows for financial year starting 1999" in result.output


def test_ni_totals(runner, patched):
    result = runner.invoke(cli, ["psni", "hate-crime", "--ni-totals", "--format", "csv"])
    assert result.exit_code == 0
    assert "1507.0" in result.output
    assert "300.0" not in result.output


def test_unallocated(runner, patched):
    result = runner.invoke(cli, ["psni", "hate-crime", "--unallocated", "--format", "csv"])
    assert result.exit_code == 0
    assert "unallocated" in result.output
    assert "7.0" in result.output


def test_save_json(runner, patched, tmp_path):
    target = tmp_path / "out.json"
    result = runner.invoke(cli, ["psni", "hate-crime", "--format", "csv", "--save", str(target)])
    assert result.exit_code == 0
    assert len(json.loads(target.read_text())) == 2


def test_invalid_choices_rejected(runner):
    assert runner.invoke(cli, ["psni", "hate-crime", "--geography", "county"]).exit_code != 0
    assert runner.invoke(cli, ["psni", "hate-crime", "--motivation", "faith"]).exit_code != 0
    assert runner.invoke(cli, ["psni", "hate-crime", "--measure", "arrests"]).exit_code != 0
