"""Tests for bolster.utils.fuzzy — pure logic, no network."""

from bolster.utils.fuzzy import fuzzy_match


class TestFuzzyMatch:
    def test_exact_substring_scores_one(self):
        result = fuzzy_match("cambria", ["Shankill, Cambria Street", "City Hall"])

        assert result == [("Shankill, Cambria Street", 1.0)]

    def test_substring_match_is_case_insensitive(self):
        result = fuzzy_match("CAMBRIA", ["shankill, cambria street"])

        assert result == [("shankill, cambria street", 1.0)]

    def test_typo_tolerance_via_difflib_ratio(self):
        result = fuzzy_match("victoria steet", ["Great Victoria Street", "City Hall"])

        assert len(result) == 1
        assert result[0][0] == "Great Victoria Street"
        assert 0 < result[0][1] < 1.0

    def test_unrelated_query_returns_empty(self):
        assert fuzzy_match("completely unrelated", ["Shankill, Cambria Street"]) == []

    def test_cutoff_filters_weak_matches(self):
        loose = fuzzy_match("xyz", ["City Hall"], cutoff=0.0)
        strict = fuzzy_match("xyz", ["City Hall"], cutoff=0.9)

        assert loose != []
        assert strict == []

    def test_n_truncates_results(self):
        candidates = ["Victoria Street", "Victoria Road", "Victoria Park", "Victoria Square"]

        result = fuzzy_match("victoria", candidates, n=2, cutoff=0.0)

        assert len(result) == 2

    def test_results_sorted_best_first(self):
        result = fuzzy_match("victoria street", ["Victoria Road", "Victoria Street"], cutoff=0.0)

        assert result[0][0] == "Victoria Street"
        assert result[0][1] >= result[1][1]

    def test_empty_candidates_returns_empty(self):
        assert fuzzy_match("anything", []) == []

    def test_empty_query_is_a_substring_of_everything(self):
        # "" is contained in every string, so every candidate matches at 1.0.
        result = fuzzy_match("", ["City Hall", "Victoria Street"])

        assert {name for name, _ in result} == {"City Hall", "Victoria Street"}
        assert all(score == 1.0 for _, score in result)
