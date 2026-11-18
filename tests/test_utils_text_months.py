"""Offline tests for the shared month-name helpers in ``bolster.utils.text``."""

import re

import pytest

from bolster.utils.text import MONTH_TOKEN_PATTERN, month_number

FULL_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


class TestMonthNumber:
    @pytest.mark.parametrize(("number", "name"), list(enumerate(FULL_NAMES, start=1)))
    def test_full_names_and_abbreviations(self, number, name):
        assert month_number(name) == number
        assert month_number(name[:3]) == number
        assert month_number(name.upper()) == number
        assert month_number(name.title()) == number

    def test_sept(self):
        assert month_number("Sept") == 9
        assert month_number("SEPT") == 9

    def test_surrounding_whitespace_is_ignored(self):
        assert month_number(" Nov ") == 11

    @pytest.mark.parametrize("token", ["", "marc", "mayhem", "septem", "13", "q1", "janu", "decemberx"])
    def test_non_months_raise_with_the_token_in_the_message(self, token):
        with pytest.raises(ValueError, match="Not a month name"):
            month_number(token)


class TestMonthTokenPattern:
    pattern = re.compile(rf"(?<![a-z])({MONTH_TOKEN_PATTERN})(?![a-z])", re.IGNORECASE)

    @pytest.mark.parametrize("name", FULL_NAMES)
    def test_matches_full_and_abbreviated_names_in_a_slug(self, name):
        for spelling in (name, name[:3], name.upper(), name.title()):
            match = self.pattern.search(f"report-{spelling}-2026")
            assert match is not None
            assert match.group(1) == spelling
            assert month_number(match.group(1)) == FULL_NAMES.index(name) + 1

    def test_sept_matches_whole(self):
        assert self.pattern.search("report-sept-2026").group(1) == "sept"

    @pytest.mark.parametrize("slug", ["mayhem-2026", "summary-2026", "decimal-2026", "marcher-2026"])
    def test_month_inside_another_word_does_not_match(self, slug):
        assert self.pattern.search(slug) is None

    def test_has_no_capture_group_so_it_embeds_cleanly(self):
        assert re.compile(MONTH_TOKEN_PATTERN).groups == 0
