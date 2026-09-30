"""Data integrity tests for Neighbourhood Renewal Area profiles (DfC, NISRA datavis Plotly pages).

Runs against the live publication. Each profile page is ~5 MB, so the tests use three representative areas
rather than all 36: a plain one, one whose hub name differs from its page/series name (Greater Falls, whose
page says Falls_Clonard), and one with a slash in its name.
"""

import pandas as pd
import pytest

from bolster.data_sources.dfc import neighbourhood_renewal_profiles as nra

EXPECTED_SECTIONS = {"Population", "Employment", "Health", "Education", "Crime"}


class TestAreaList:
    @pytest.fixture(scope="class")
    def areas(self):
        return nra.list_areas()

    def test_lists_the_neighbourhood_renewal_areas(self, areas):
        assert len(areas) >= 30
        assert {"Andersonstown", "Armagh", "Waterside"} <= set(areas)

    def test_urls_are_datavis_profile_pages(self, areas):
        assert all(
            u.startswith("https://datavis.nisra.gov.uk/communities/") and u.endswith(".html") for u in areas.values()
        )
        assert len(set(areas.values())) == len(areas)

    def test_hub_and_page_names_can_differ_and_both_resolve(self, areas):
        assert "Greater Falls" in areas
        assert nra._resolve_area("greater falls", areas) == "Greater Falls"
        assert nra._resolve_area("Falls/Clonard", areas) == "Greater Falls"

    def test_unknown_area_raises(self, areas):
        with pytest.raises(nra.NRADataNotFoundError, match="Unknown"):
            nra._resolve_area("Atlantis", areas)


class TestAreaProfile:
    @pytest.fixture(scope="class", params=["Andersonstown", "Greater Falls", "Upper Springfield/Whiterock"])
    def profile(self, request):
        return nra.get_area_profile(request.param)

    def test_columns(self, profile):
        assert list(profile.columns) == ["nra", "section", "figure", "unit", "series", "category", "value", "is_area"]

    def test_has_the_expected_sections(self, profile):
        assert set(profile["section"]) >= EXPECTED_SECTIONS
        assert not profile["section"].str.contains("&amp;").any(), "entities are decoded"

    def test_has_the_area_and_the_ni_comparator(self, profile):
        assert profile["is_area"].any()
        assert (profile["series"] == "Northern Ireland").any()

    def test_values_are_sane(self, profile):
        assert profile["value"].notna().mean() > 0.95
        assert (profile["value"].dropna() >= 0).all()
        percentages = profile[profile["unit"] == "Percentage"]["value"].dropna()
        assert percentages.between(0, 100).all()

    def test_sex_split_sums_to_100_every_year(self, profile):
        sex = profile[profile["figure"].str.startswith("Population Distribution by Sex")]
        assert not sex.empty
        totals = sex.pivot_table(index="category", columns="series", values="value").sum(axis=1)
        assert (totals - 100).abs().max() < 0.5


class TestSeveralAreas:
    @pytest.fixture(scope="class")
    def combined(self):
        return nra.get_all_area_profiles(["Andersonstown", "falls clonard"])

    def test_concatenates_the_requested_areas_only(self, combined):
        assert set(combined["nra"]) == {"Andersonstown", "Greater Falls"}
        assert list(combined.columns) == ["nra", "section", "figure", "unit", "series", "category", "value", "is_area"]

    def test_each_area_is_complete(self, combined):
        for name, profile in combined.groupby("nra"):
            assert profile["figure"].nunique() >= 20, name
            assert profile["is_area"].any(), name
        assert combined.index.is_unique

    def test_unknown_area_in_the_list_raises(self):
        with pytest.raises(nra.NRADataNotFoundError, match="Unknown"):
            nra.get_all_area_profiles(["Andersonstown", "Atlantis"])


class TestSlugMismatchArea:
    """Greater Falls: hub name and page URL/series differ, so is_area must match the series 'Falls_Clonard'."""

    def test_area_series_is_recognised_despite_the_name_difference(self):
        profile = nra.get_area_profile("Greater Falls")
        assert profile["nra"].iloc[0] == "Greater Falls"
        assert "Falls_Clonard" in set(profile.loc[profile["is_area"], "series"])


class TestHelpers:
    """Unit tests for name handling and validation edge cases - no network calls needed."""

    def test_normalise(self):
        assert nra._normalise("Falls/Clonard") == nra._normalise("Falls_Clonard") == "fallsclonard"
        assert nra._normalise("Triax - Cityside") == nra._normalise("Triax_-_Cityside")

    def test_names_include_the_url_slug(self):
        url = "https://datavis.nisra.gov.uk/communities/Falls_Clonard_NRA_Area_Profile_2026.html"
        assert nra._names("Greater Falls", url) == {"greaterfalls", "fallsclonard"}
        assert nra._names("Armagh", "https://example.com/other.html") == {"armagh"}

    @staticmethod
    def _valid():
        rows = [
            {
                "nra": "A",
                "section": "S",
                "figure": f"F{i}",
                "unit": "Percentage",
                "series": series,
                "category": "2020",
                "value": 1.0,
                "is_area": series == "A",
            }
            for i in range(25)
            for series in ("A", "Northern Ireland")
        ]
        return pd.DataFrame(rows)

    def test_validate_accepts_valid_profile(self):
        assert nra.validate_data(self._valid()) is True

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            (lambda df: df.drop(columns=["is_area"]), "Missing expected columns"),
            (lambda df: df[df["figure"].isin([f"F{i}" for i in range(5)])], "Too few charts"),
            (lambda df: df.assign(is_area=False), "area itself"),
            (lambda df: df[df["series"] != "Northern Ireland"], "Northern Ireland comparator"),
            (lambda df: df.assign(value=float("nan")), "No numeric values"),
        ],
    )
    def test_validate_rejects_bad_profiles(self, mutate, message):
        with pytest.raises(nra.NRAValidationError, match=message):
            nra.validate_data(mutate(self._valid()))
