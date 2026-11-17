"""Offline tests for the LFS filename parsing in ``nisra.labour_market``.

NISRA has named the quarterly tables file with full month names
(``July-September-25``) and with abbreviations (``Jul-Sep-26``); both must parse.
"""

import pytest

from bolster.data_sources.nisra import labour_market
from bolster.data_sources.nisra._base import NISRADataNotFoundError

PREFIX = "lmr-labour-force-survey-quarterly-tables-"


class TestQuarterFilename:
    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [
            ("July-September-25.xlsx", ("2025", "Jul-Sep")),
            ("Jul-Sep-26.xlsx", ("2026", "Jul-Sep")),
            ("January-March-24.xlsx", ("2024", "Jan-Mar")),
            ("Jan-Mar-24.xlsx", ("2024", "Jan-Mar")),
            ("April-June-25.xlsx", ("2025", "Apr-Jun")),
            ("Oct-Dec-25.xlsx", ("2025", "Oct-Dec")),
            ("October-December-23.xlsx", ("2023", "Oct-Dec")),
        ],
    )
    def test_full_and_abbreviated_months(self, suffix, expected):
        assert labour_market._parse_lfs_quarter_filename(PREFIX + suffix) == expected

    @pytest.mark.parametrize(
        "suffix",
        ["jul-sep-26.xlsx", "JUL-SEP-26.xlsx", "JULY-SEPTEMBER-26.xlsx", "jUl-SeP-26.xlsx"],
    )
    def test_letter_case_is_ignored(self, suffix):
        assert labour_market._parse_lfs_quarter_filename(PREFIX + suffix) == ("2026", "Jul-Sep")

    def test_sept_is_accepted(self):
        assert labour_market._parse_lfs_quarter_filename(PREFIX + "July-Sept-26.xlsx") == ("2026", "Jul-Sep")

    def test_mixed_full_and_abbreviated(self):
        assert labour_market._parse_lfs_quarter_filename(PREFIX + "Jul-September-26.xlsx") == ("2026", "Jul-Sep")
        assert labour_market._parse_lfs_quarter_filename(PREFIX + "July-Sep-26.xlsx") == ("2026", "Jul-Sep")

    def test_year_is_two_digits_expanded_to_2000s(self):
        assert labour_market._parse_lfs_quarter_filename(PREFIX + "Jan-Mar-07.xlsx") == ("2007", "Jan-Mar")

    @pytest.mark.parametrize(
        "filename",
        [
            PREFIX + "2026.xlsx",
            PREFIX + "Jul-Sep.xlsx",
            PREFIX + "Foo-Bar-26.xlsx",
            "something-else.xlsx",
            "",
        ],
    )
    def test_no_match_raises_naming_the_filename(self, filename):
        with pytest.raises(NISRADataNotFoundError, match="Could not extract quarter and year") as exc:
            labour_market._parse_lfs_quarter_filename(filename)
        assert filename in str(exc.value)

    def test_does_not_match_inside_other_words(self):
        # "summary-march-26" must not be read as a Mar-?? quarter via the "mar" in "summary"
        with pytest.raises(NISRADataNotFoundError):
            labour_market._parse_lfs_quarter_filename("lmr-summary-march-26.xlsx")


class TestMonthNumber:
    @pytest.mark.parametrize(
        ("token", "number"),
        [("January", 1), ("jan", 1), ("March", 3), ("Sept", 9), ("september", 9), ("Dec", 12), ("december", 12)],
    )
    def test_month_number(self, token, number):
        assert labour_market._month_number(token) == number
