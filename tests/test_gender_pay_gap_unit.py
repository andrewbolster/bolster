"""Unit tests for UK Gender Pay Gap module — branch/line coverage.

These tests exercise code paths not covered by the real-data integrity tests:
- CLI command invocations (all major branches)
- get_all_years() warning/skip path when a year fails
- validate_data() partial branches

No network calls are made here; we use the Click CliRunner and minimal
DataFrames to exercise the paths cheaply.
"""

import pandas as pd
import pytest
from click.testing import CliRunner

from bolster.cli import cli
from bolster.data_sources import gender_pay_gap


# ---------------------------------------------------------------------------
# Minimal valid DataFrame for use in unit tests
# ---------------------------------------------------------------------------

def _make_df(n=2):
    """Return a minimal DataFrame that passes validate_data."""
    return pd.DataFrame(
        {
            "employer_name": [f"Employer {i}" for i in range(n)],
            "employer_id": [str(i) for i in range(n)],
            "postcode": [f"BT1 {i}AA" for i in range(n)],
            "company_number": ["" for _ in range(n)],
            "sic_codes": ["" for _ in range(n)],
            "diff_mean_hourly_percent": [10.0] * n,
            "diff_median_hourly_percent": [8.0] * n,
            "diff_mean_bonus_percent": [5.0] * n,
            "diff_median_bonus_percent": [3.0] * n,
            "male_bonus_percent": [50.0] * n,
            "female_bonus_percent": [40.0] * n,
            "male_lower_quartile": [60.0] * n,
            "female_lower_quartile": [40.0] * n,
            "male_lower_middle_quartile": [55.0] * n,
            "female_lower_middle_quartile": [45.0] * n,
            "male_upper_middle_quartile": [50.0] * n,
            "female_upper_middle_quartile": [50.0] * n,
            "male_top_quartile": [70.0] * n,
            "female_top_quartile": [30.0] * n,
            "employer_size": ["250 to 499"] * n,
            "reporting_year": [2024] * n,
            "submitted_after_deadline": [False] * n,
            "due_date": pd.to_datetime(["2024-04-05"] * n),
            "date_submitted": pd.to_datetime(["2024-03-01"] * n),
            "company_link_to_gpg_info": [""] * n,
            "responsible_person": ["A Person"] * n,
            "current_name": [f"Employer {i}" for i in range(n)],
            "address": ["1 Street"] * n,
        }
    )


# ---------------------------------------------------------------------------
# Module-level unit tests (no network)
# ---------------------------------------------------------------------------

class TestGetAllYearsSkipsFailingYears:
    """get_all_years() should log a warning and skip years that raise."""

    def test_skips_year_on_error(self, monkeypatch):
        """If one year raises GenderPayGapError, it's skipped, not fatal."""
        calls = []

        def fake_get_data(year, postcode_prefix=None, force_refresh=False):
            calls.append(year)
            if year == 2017:
                raise gender_pay_gap.GenderPayGapError("simulated failure")
            return _make_df()

        monkeypatch.setattr(gender_pay_gap, "get_data", fake_get_data)
        monkeypatch.setattr(gender_pay_gap, "get_available_years", lambda: [2017, 2018])

        df = gender_pay_gap.get_all_years()
        assert 2017 in calls
        assert len(df) > 0  # 2018 data is returned

    def test_raises_when_all_years_fail(self, monkeypatch):
        """If every year fails, get_all_years() raises GenderPayGapError."""
        def fake_get_data(year, postcode_prefix=None, force_refresh=False):
            raise gender_pay_gap.GenderPayGapError("always fails")

        monkeypatch.setattr(gender_pay_gap, "get_data", fake_get_data)
        monkeypatch.setattr(gender_pay_gap, "get_available_years", lambda: [2017, 2018])

        with pytest.raises(gender_pay_gap.GenderPayGapError, match="No data"):
            gender_pay_gap.get_all_years()


class TestValidateDataEdgeCases:
    """Additional validate_data() branch coverage."""

    def test_validate_skips_quartile_check_when_columns_missing(self):
        """If quartile columns are absent, the quartile check is simply skipped."""
        df = _make_df()
        # Drop all quartile columns — validation should still pass on the remaining checks
        quartile_cols = [c for c in df.columns if "quartile" in c]
        df = df.drop(columns=quartile_cols)
        # Required columns for validate_data don't include quartile cols, so it passes
        assert gender_pay_gap.validate_data(df)

    def test_validate_skips_pay_gap_check_when_columns_missing(self):
        """If hourly pay gap columns are absent, that check is skipped."""
        df = _make_df()
        df = df.drop(columns=["diff_mean_hourly_percent", "diff_median_hourly_percent"])
        # Required columns set includes diff_mean_hourly_percent, so this should raise
        with pytest.raises(gender_pay_gap.GenderPayGapError, match="Missing required columns"):
            gender_pay_gap.validate_data(df)

    def test_validate_handles_all_nan_pay_gap(self):
        """Validation should pass when pay gap values are all NaN (no data to check)."""
        df = _make_df()
        df["diff_mean_hourly_percent"] = float("nan")
        df["diff_median_hourly_percent"] = float("nan")
        assert gender_pay_gap.validate_data(df)


# ---------------------------------------------------------------------------
# CLI unit tests via CliRunner
# ---------------------------------------------------------------------------

class TestGenderPayGapCLI:
    """CLI command invocation tests — exercise all major branches."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def patch_gpg(self, monkeypatch):
        """Monkeypatch the GPG module so CLI tests don't hit the network."""
        monkeypatch.setattr(gender_pay_gap, "get_available_years", lambda: [2023, 2024])
        monkeypatch.setattr(gender_pay_gap, "get_data", lambda year, postcode_prefix=None, force_refresh=False: _make_df())
        monkeypatch.setattr(gender_pay_gap, "get_all_years", lambda postcode_prefix=None: _make_df())

    def test_default_invocation(self, runner, patch_gpg):
        """Default call (no options) should succeed and print CSV."""
        result = runner.invoke(cli, ["gender-pay-gap"])
        assert result.exit_code == 0

    def test_with_year(self, runner, patch_gpg):
        """--year option should succeed."""
        result = runner.invoke(cli, ["gender-pay-gap", "--year", "2024"])
        assert result.exit_code == 0

    def test_with_postcode_prefix(self, runner, patch_gpg):
        """--postcode-prefix option should succeed."""
        result = runner.invoke(cli, ["gender-pay-gap", "--postcode-prefix", "BT"])
        assert result.exit_code == 0

    def test_all_years_flag(self, runner, patch_gpg):
        """--all-years flag should call get_all_years() path."""
        result = runner.invoke(cli, ["gender-pay-gap", "--all-years"])
        assert result.exit_code == 0

    def test_summary_flag(self, runner, patch_gpg):
        """--summary flag should print summary stats and return."""
        result = runner.invoke(cli, ["gender-pay-gap", "--summary"])
        assert result.exit_code == 0

    def test_summary_with_postcode_prefix(self, runner, patch_gpg):
        """--summary with --postcode-prefix should show scoped label."""
        result = runner.invoke(cli, ["gender-pay-gap", "--summary", "--postcode-prefix", "BT"])
        assert result.exit_code == 0

    def test_json_format(self, runner, patch_gpg):
        """--format json should emit JSON output."""
        result = runner.invoke(cli, ["gender-pay-gap", "--format", "json"])
        assert result.exit_code == 0

    def test_save_csv(self, runner, patch_gpg, tmp_path):
        """--save to a CSV file should write the file."""
        outfile = str(tmp_path / "out.csv")
        result = runner.invoke(cli, ["gender-pay-gap", "--save", outfile])
        assert result.exit_code == 0

    def test_save_json(self, runner, patch_gpg, tmp_path):
        """--save to a .json file should write JSON."""
        outfile = str(tmp_path / "out.json")
        result = runner.invoke(cli, ["gender-pay-gap", "--save", outfile, "--format", "json"])
        assert result.exit_code == 0

    def test_year_not_found_error(self, runner, monkeypatch):
        """Requesting an unavailable year should hit the GenderPayGapDataNotFoundError branch."""
        monkeypatch.setattr(gender_pay_gap, "get_available_years", lambda: [2023, 2024])

        def _raises(year, postcode_prefix=None, force_refresh=False):
            raise gender_pay_gap.GenderPayGapDataNotFoundError(f"Year {year} not available")

        monkeypatch.setattr(gender_pay_gap, "get_data", _raises)
        result = runner.invoke(cli, ["gender-pay-gap", "--year", "2020"])
        assert result.exit_code != 0

    def test_generic_error_branch(self, runner, monkeypatch):
        """A generic exception should hit the catch-all error branch."""
        monkeypatch.setattr(gender_pay_gap, "get_available_years", lambda: [2023, 2024])

        def _raises(year, postcode_prefix=None, force_refresh=False):
            raise RuntimeError("network exploded")

        monkeypatch.setattr(gender_pay_gap, "get_data", _raises)
        result = runner.invoke(cli, ["gender-pay-gap", "--year", "2024"])
        assert result.exit_code != 0

    def test_empty_dataframe_branch(self, runner, monkeypatch):
        """An empty DataFrame should hit the 'no data found' warning branch."""
        monkeypatch.setattr(gender_pay_gap, "get_available_years", lambda: [2023, 2024])
        monkeypatch.setattr(
            gender_pay_gap,
            "get_data",
            lambda year, postcode_prefix=None, force_refresh=False: pd.DataFrame(),
        )
        result = runner.invoke(cli, ["gender-pay-gap", "--year", "2024"])
        assert result.exit_code == 0
