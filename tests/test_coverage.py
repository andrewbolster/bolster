"""Offline tests for matching publication titles against the implemented-module catalogue."""

from pathlib import Path

import click
import pytest

from bolster.utils.coverage import (
    COVERED,
    NOT_COVERED,
    POSSIBLE_OVERLAP,
    Catalogue,
    CatalogueEntry,
    build_catalogue,
    command_entries,
    match_title,
    module_entries,
    tokenise,
)


def _module(name: str, doc: str, getters: str = "") -> CatalogueEntry:
    own = name.split("/", 1)[-1].replace("_", " ")
    return CatalogueEntry(
        "module", name, doc, tokenise(f"{name.replace('_', ' ').replace('/', ' ')} {doc} {getters}"), tokenise(own)
    )


@pytest.fixture(scope="module")
def synthetic() -> Catalogue:
    """A small catalogue shaped like the real one, with deliberately confusable neighbours."""
    return Catalogue.from_entries(
        [
            _module(
                "nisra/deaths", "Weekly and monthly deaths registered in Northern Ireland, with demographic breakdowns"
            ),
            _module("nisra/births", "Monthly births registered in Northern Ireland"),
            _module("nisra/marriages", "Monthly marriages registered in Northern Ireland"),
            _module("nisra/baby_names", "Baby names registered each year, drawn from births registrations"),
            _module("nisra/registrar_general", "Registrar General quarterly births, deaths and marriages tables"),
            _module("justice/nicts_quarterly", "NI Courts and Tribunals Service quarterly provisional figures"),
            _module("psni/stop_and_search", "Stop and search statistics from the Police Service of Northern Ireland"),
            _module("psni/pace", "Police and Criminal Evidence Act arrests and detentions"),
            _module(
                "dfe/higher_level_apprenticeships", "Higher level apprenticeships in higher education institutions"
            ),
            _module(
                "dfe/further_education_outcomes",
                "Further education leaver destinations: employment, learning, unemployed",
            ),
            _module("nisra/cancer_waiting_times", "Cancer waiting times: 14, 31 and 62 day targets"),
            _module(
                "nisra/business_register",
                "Annual count of VAT and PAYE registered businesses from the Inter-Departmental Business Register",
            ),
            _module("nisra/labour_market", "Labour market statistics: employment, unemployment, economic inactivity"),
            _module("nisra/ashe", "Annual Survey of Hours and Earnings; weekly pay and the labour market"),
        ]
    )


class TestTokenise:
    def test_drops_years_months_quarters_and_generic_words(self):
        assert (
            tokenise("Quarterly Statistics for Northern Ireland, Q2 2026/27, period ending 30 September 2026")
            == frozenset()
        )

    def test_keeps_the_distinctive_words(self):
        assert {"labour", "market"} <= tokenise("NI Labour Market statistics: November 2026")

    @pytest.mark.parametrize("variant", ["registrations", "registered", "register", "Registering"])
    def test_stems_agree_across_word_forms(self, variant):
        assert tokenise(variant) == tokenise("register")

    def test_plural_and_singular_agree(self):
        assert tokenise("marriages") == tokenise("marriage")
        assert tokenise("casualties") == tokenise("casualty")


class TestWeights:
    def test_rare_tokens_weigh_more_than_common_ones(self, synthetic):
        assert synthetic.weight(next(iter(tokenise("apprenticeships")))) > synthetic.weight(
            next(iter(tokenise("registered")))
        )

    def test_unknown_token_is_maximally_distinctive(self, synthetic):
        assert synthetic.weight("zzzzzz") >= max(synthetic.weights.values())


class TestMatchTitle:
    @pytest.mark.parametrize(
        ("title", "module"),
        [
            ("Deaths Registered in Northern Ireland - Week ending 13 November 2026", "nisra/deaths"),
            ("Monthly Marriages (Northern Ireland): October 2026", "nisra/marriages"),
            ("Monthly Births (Northern Ireland): October 2026", "nisra/births"),
            ("NI Labour Market statistics: November 2026", "nisra/labour_market"),
            (
                "Stop and Search statistics for Northern Ireland, period ending 30 September 2026",
                "psni/stop_and_search",
            ),
            ("NICTS Quarterly Provisional Figures April to June 2026", "justice/nicts_quarterly"),
            ("Registrar General Northern Ireland Annual Report 2025", "nisra/registrar_general"),
        ],
    )
    def test_covered_names_the_module_named_after_the_topic(self, synthetic, title, module):
        match = match_title(title, synthetic)
        assert match.label == COVERED, match
        assert match.entry.name == module

    def test_one_shared_word_is_not_coverage(self, synthetic):
        """'death' alone must not make a different publication covered by the deaths module."""
        match = match_title("Time Taken To Register a Death in NI, 2025", synthetic)
        assert match.label != COVERED
        assert match.entry.name == "nisra/deaths"

    @pytest.mark.parametrize(
        "title", ["Widget Fabrication Output Report 2026", "Quarterly Gadget Insulation Survey: Q2 2026"]
    )
    def test_unrelated_titles_are_not_covered(self, synthetic, title):
        assert match_title(title, synthetic).label == NOT_COVERED

    def test_a_sibling_series_is_a_possible_overlap_not_coverage(self, synthetic):
        """ApprenticeshipsNI is a different series from Higher Level Apprenticeships."""
        match = match_title("ApprenticeshipsNI Statistical Bulletin - Oct 19 to Apr 26", synthetic)
        assert match.label == POSSIBLE_OVERLAP
        assert match.entry.name == "dfe/higher_level_apprenticeships"

    def test_a_related_publication_with_extra_distinctive_words_is_not_covered(self, synthetic):
        match = match_title("Further Education Sector Activity Northern Ireland: 21/22 - 25/26", synthetic)
        assert match.label != COVERED

    def test_a_title_with_extra_distinctive_words_names_the_module_but_is_not_covered(self, synthetic):
        """A title that carries more than the module's name is a possible overlap for a human to judge."""
        match = match_title(
            "Northern Ireland Cancer Waiting Times - Revised 62 Day Waits for Quarters Ending December 2025", synthetic
        )
        assert match.label == POSSIBLE_OVERLAP
        assert match.entry.name == "nisra/cancer_waiting_times"

    def test_a_different_publication_containing_the_module_name_is_not_covered(self, synthetic):
        """BRES (employee jobs) is not the IDBR business count that the business_register module serves."""
        match = match_title("Business Register and Employment Survey Northern Ireland, 2024", synthetic)
        assert match.label == POSSIBLE_OVERLAP
        assert match.entry.name == "nisra/business_register"

    def test_name_beats_a_module_that_only_mentions_the_topic(self, synthetic):
        """baby_names and registrar_general both mention births; the births module is the one named for it."""
        assert match_title("Monthly Births (Northern Ireland): October 2026", synthetic).entry.name == "nisra/births"
        assert (
            match_title("Monthly Marriages (Northern Ireland): October 2026", synthetic).entry.name == "nisra/marriages"
        )

    def test_returns_runner_ups_for_a_human_to_judge(self, synthetic):
        match = match_title("Time Taken To Register a Death in NI, 2025", synthetic, alternatives=2)
        assert 1 <= len(match.alternatives) <= 2
        assert all(score <= match.score + 0.31 for _, score in match.alternatives)

    def test_empty_title_matches_nothing(self, synthetic):
        match = match_title("2026", synthetic)
        assert (match.label, match.entry) == (NOT_COVERED, None)


class TestEntries:
    def test_module_entries_read_docstring_getters_and_skip_helpers(self, tmp_path: Path):
        provider = tmp_path / "psni"
        provider.mkdir()
        (provider / "__init__.py").write_text('"""Provider package."""\n')
        (provider / "_base.py").write_text('"""Shared helper that mentions everything."""\n')
        (provider / "stop_and_search.py").write_text(
            '"""Stop and search statistics.\n\nQuarterly data on police powers.\n"""\n\n\ndef get_latest_arrests_data():\n    pass\n\n\ndef _private():\n    pass\n'
        )
        (provider / "no_docstring.py").write_text("X = 1\n")
        entries = {entry.name: entry for entry in module_entries(tmp_path)}
        assert set(entries) == {"psni/stop_and_search", "psni/no_docstring"}
        stop = entries["psni/stop_and_search"]
        assert stop.summary == "Stop and search statistics."
        assert {"stop", "search", "arrest"} <= stop.tokens
        assert "psni" in stop.tokens
        assert "psni" not in stop.name_tokens, "the provider directory is not part of the module's own name"
        assert {"stop", "search"} <= stop.name_tokens

    def test_command_entries_flatten_the_click_tree(self):
        @click.group()
        def root():
            """Root."""

        @root.group()
        def nisra():
            """NISRA sources."""

        @nisra.command(name="labour-market")
        def labour_market():
            """Labour market statistics."""

        entries = {entry.name: entry for entry in command_entries(root)}
        assert set(entries) == {"nisra", "nisra labour-market"}
        assert {"labour", "market"} <= entries["nisra labour-market"].tokens
        assert entries["nisra labour-market"].name_tokens == frozenset(), "commands match by tokens only"

    def test_a_generically_named_command_cannot_cover_a_sibling_series(self):
        @click.group()
        def root():
            """Root."""

        @root.command(name="apprenticeships")
        def apprenticeships():
            """Higher level apprenticeships in higher education."""

        catalogue = build_catalogue(root, root=Path("/nonexistent"))
        assert match_title("ApprenticeshipsNI Statistical Bulletin - Oct 19 to Apr 26", catalogue).label != COVERED


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    """The real catalogue, built from this checkout's ``data_sources`` tree."""
    return build_catalogue()


class TestRealCatalogue:
    """Titles from the live NISRA feed that existing modules serve; these modules are not going away."""

    def test_catalogue_covers_the_data_source_tree(self, catalogue):
        modules = [entry for entry in catalogue.entries if entry.kind == "module"]
        assert len(modules) >= 100
        assert all(not entry.name.split("/")[-1].startswith("_") for entry in modules)

    @pytest.mark.parametrize(
        ("title", "module"),
        [
            ("NI Labour Market statistics: November 2026", "nisra/labour_market"),
            ("Monthly Births (Northern Ireland): October 2026", "nisra/births"),
            ("Monthly Marriages (Northern Ireland): October 2026", "nisra/marriages"),
            ("Monthly Stillbirths (Northern Ireland): October 2026", "nisra/stillbirths"),
            ("Deaths Registered in Northern Ireland - Week ending 13 November 2026", "nisra/deaths"),
            ("Northern Ireland House Price Index Quarter 3 2026", "ni_house_price_index"),
            ("Police recorded crime in Northern Ireland, period ending 31 October 2026", "psni/crime_statistics"),
            (
                "Stop and Search statistics for Northern Ireland, period ending 30 September 2026",
                "psni/stop_and_search",
            ),
            ("Hate incidents and crimes in Northern Ireland, period ending 30 September 2026", "psni/hate_crime"),
            ("Motoring offences statistics in Northern Ireland to 30 September 2026", "psni/motoring_offences"),
            ("General Medical Services Statistics for NI, Quarter 2 2026/27", "health_ni/gms"),
            (
                "Quarterly Child Protection Statistics for Northern Ireland (September 2026)",
                "health_ni/child_protection",
            ),
            ("Probation Board NI quarterly caseload, quarter 2, 2026/27", "justice/pbni_caseload"),
            ("Registrar General Northern Ireland Annual Report 2025", "nisra/registrar_general"),
            ("Young people not in education, employment or training (NEET), NI: July to September 2026", "nisra/neet"),
            ("Northern Ireland LAC municipal waste management statistics 2025/26 annual report", "daera_waste"),
        ],
    )
    def test_served_publications_are_covered_by_the_right_module(self, catalogue, title, module):
        match = match_title(title, catalogue)
        assert match.label == COVERED, match
        assert match.entry.name == module

    def test_time_taken_to_register_a_death_is_never_marked_covered_by_the_deaths_module(self, catalogue):
        """The old keyword check marked this covered because the title contains 'death'."""
        match = match_title("Time Taken To Register a Death in NI, 2025", catalogue)
        assert not (match.label == COVERED and match.entry.name == "nisra/deaths")

    def test_business_register_and_employment_survey_is_not_covered_by_the_idbr_business_register(self, catalogue):
        """BRES shares the words 'business register' with the IDBR module but is a different publication."""
        match = match_title("Business Register and Employment Survey Northern Ireland, 2024", catalogue)
        assert not (match.label == COVERED and match.entry.name == "nisra/business_register")
