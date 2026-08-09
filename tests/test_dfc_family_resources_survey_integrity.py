"""Data integrity tests for the DfC Family Resources Survey NI module.

Network tests use real workbooks from communities-ni.gov.uk with ``scope="class"``
fixtures so each chapter is downloaded once. Parsing helpers are exercised
separately with no network access.
"""

import pandas as pd
import pytest

from bolster.data_sources.dfc import family_resources_survey as frs

DISTRICTS = {
    "Antrim & Newtownabbey",
    "Ards & North Down",
    "Belfast City",
    "Derry City & Strabane",
    "Fermanagh & Omagh",
    "Lisburn & Castlereagh",
    "Mid & East Antrim",
    "Mid Ulster",
    "Newry, Mourne & Down",
}


def assert_percentage_column(df: pd.DataFrame, column: str) -> None:
    """Every non-suppressed value in ``column`` must be a plausible percentage."""
    values = df[column].dropna()
    assert not values.empty, f"{column} is entirely suppressed"
    assert (values >= 0).all(), f"{column} has negative values"
    assert (values <= 100).all(), f"{column} exceeds 100"


# ---------------------------------------------------------------------------
# Edition and chapter discovery
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestEditionDiscovery:
    """Tests for runtime discovery of the current edition and its workbooks."""

    @pytest.fixture(scope="class")
    def edition(self) -> tuple[str, str]:
        return frs.find_latest_edition()

    @pytest.fixture(scope="class")
    def chapter_urls(self) -> dict[str, str]:
        return frs.get_chapter_urls()

    def test_edition_is_financial_year(self, edition):
        """The resolved edition must be a YYYY/YY financial year."""
        financial_year, _ = edition
        assert len(financial_year) == 7
        start, end = financial_year.split("/")
        assert int(end) == (int(start) + 1) % 100

    def test_edition_not_older_than_first_machine_readable(self, edition):
        """Discovery must not walk back past the first workbook edition."""
        financial_year, _ = edition
        assert int(financial_year.split("/")[0]) >= frs.EARLIEST_MACHINE_READABLE_EDITION

    def test_edition_url_is_communities_ni(self, edition):
        """The edition page must be served from communities-ni.gov.uk."""
        _, url = edition
        assert url.startswith("https://www.communities-ni.gov.uk/publications/")

    def test_chapter_urls_are_xlsx(self, chapter_urls):
        """Every discovered chapter must point at an absolute .xlsx URL."""
        assert chapter_urls, "No chapter workbooks discovered"
        for chapter, url in chapter_urls.items():
            assert url.startswith("https://"), f"{chapter} URL is not absolute"
            assert url.endswith(".xlsx"), f"{chapter} URL is not an .xlsx"

    def test_chapters_used_by_accessors_are_published(self, chapter_urls):
        """The chapters the accessors read from must exist in this edition."""
        for chapter in ("food_security", "income", "tenure", "carers_disability"):
            assert chapter in chapter_urls, f"Missing chapter workbook: {chapter}"

    def test_chapter_urls_are_subset_of_known_chapters(self, chapter_urls):
        """Discovery must not invent chapter keys."""
        assert set(chapter_urls) <= set(frs.CHAPTERS)

    def test_list_chapters_covers_known_keys(self):
        assert {"income", "tenure", "pensions", "food_security"} <= set(frs.list_chapters())

    def test_unknown_chapter_raises(self):
        """Reading an unpublished chapter raises FRSDataNotFoundError."""
        with pytest.raises(frs.FRSDataNotFoundError):
            frs._read_table("no_such_chapter", "T1.1")

    def test_unknown_sheet_raises(self):
        """Reading a missing sheet raises FRSDataNotFoundError."""
        with pytest.raises(frs.FRSDataNotFoundError):
            frs._read_table("food_security", "T99.9")


# ---------------------------------------------------------------------------
# Chapter 6 - food security and food bank usage
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestFoodSecurity:
    """Tests for the chapter 6 food security cross-tabulations."""

    @pytest.fixture(scope="class")
    def by_region(self) -> pd.DataFrame:
        return frs.get_food_security_by_region()

    @pytest.fixture(scope="class")
    def by_composition(self) -> pd.DataFrame:
        return frs.get_food_security_by_composition()

    @pytest.fixture(scope="class")
    def by_disability(self) -> pd.DataFrame:
        return frs.get_food_security_by_disability()

    @pytest.fixture(scope="class")
    def by_state_support(self) -> pd.DataFrame:
        return frs.get_food_security_by_state_support()

    @pytest.fixture(scope="class")
    def by_tenure(self) -> pd.DataFrame:
        return frs.get_food_security_by_tenure()

    def test_region_covers_uk_countries(self, by_region):
        """All four UK countries plus the UK total must be present."""
        areas = set(by_region["area"])
        assert {"United Kingdom", "England", "Wales", "Scotland", "Northern Ireland"} <= areas

    def test_region_covers_english_regions(self, by_region):
        """The nine English regions give NI a comparable baseline."""
        areas = set(by_region["area"])
        assert {"North East", "North West", "South East", "South West"} <= areas

    def test_region_security_bands_sum_to_total(self, by_region):
        """High plus marginal must reconcile with the food secure total."""
        rows = by_region.dropna(subset=["high_pct", "marginal_pct", "food_secure_pct"])
        assert not rows.empty
        combined = rows["high_pct"] + rows["marginal_pct"]
        assert (combined - rows["food_secure_pct"]).abs().max() <= 1.5

    def test_region_secure_and_insecure_sum_to_100(self, by_region):
        """Secure and insecure shares must partition each area."""
        rows = by_region.dropna(subset=["food_secure_pct", "food_insecure_pct"])
        total = rows["food_secure_pct"] + rows["food_insecure_pct"]
        assert (total - 100).abs().max() <= 1.5

    def test_region_percentages_in_range(self, by_region):
        """All published percentage columns stay within 0-100."""
        for column in (
            "high_pct",
            "marginal_pct",
            "low_pct",
            "very_low_pct",
            "food_secure_pct",
            "food_insecure_pct",
            "food_bank_30_day_pct",
            "food_bank_12_month_pct",
        ):
            assert_percentage_column(by_region, column)

    def test_region_sample_sizes_positive(self, by_region):
        """Every area must carry a positive achieved sample."""
        assert (by_region["sample_size"].dropna() > 0).all()

    def test_ni_is_more_food_secure_than_uk(self, by_region):
        """NI has consistently reported above-UK food security."""
        indexed = by_region.set_index("area")["food_secure_pct"]
        assert indexed["Northern Ireland"] >= indexed["United Kingdom"]

    def test_composition_has_section_column(self, by_composition):
        """Nested adult-count rows must be resolved by their parent block."""
        sections = set(by_composition["section"])
        assert {"Without children", "With children"} <= sections

    def test_composition_rows_are_unique(self, by_composition):
        """The section column must make repeated labels distinguishable."""
        keys = by_composition[["household_composition", "section"]]
        assert not keys.duplicated().any()

    def test_composition_has_no_structural_blank_rows(self, by_composition):
        """Layout sub-headings carry no data and must be dropped."""
        numeric = by_composition[["food_secure_pct", "total_pct", "sample_size"]]
        assert not numeric.isna().all(axis=1).all()

    def test_composition_labels_non_empty(self, by_composition):
        """Every retained row must be labelled."""
        assert (by_composition["household_composition"].str.len() > 0).all()

    def test_households_with_children_less_secure(self, by_composition):
        """Households with children report lower food security than those without."""
        indexed = by_composition.set_index("household_composition")["food_secure_pct"]
        assert indexed["All households with children"] < indexed["All households without children"]

    @pytest.mark.parametrize(
        ("fixture_name", "dimension"),
        [
            ("by_composition", "household_composition"),
            ("by_disability", "disability_in_household"),
            ("by_state_support", "state_support_received"),
            ("by_tenure", "tenure"),
        ],
    )
    def test_cross_tabs_share_shape(self, request, fixture_name, dimension):
        """Tables 6.2-6.5 must all parse to the same tidy shape."""
        df = request.getfixturevalue(fixture_name)
        assert dimension in df.columns
        for column in ("food_secure_pct", "food_insecure_pct", "total_pct", "sample_size"):
            assert column in df.columns
        assert len(df) > 0

    @pytest.mark.parametrize(
        "fixture_name",
        ["by_composition", "by_disability", "by_state_support", "by_tenure"],
    )
    def test_cross_tab_totals_are_100(self, request, fixture_name):
        """The published All column must total 100 for every retained row."""
        df = request.getfixturevalue(fixture_name)
        totals = df["total_pct"].dropna()
        assert not totals.empty
        assert (totals - 100).abs().max() <= 0.5

    @pytest.mark.parametrize(
        "fixture_name",
        ["by_composition", "by_disability", "by_state_support", "by_tenure"],
    )
    def test_cross_tab_all_households_row(self, request, fixture_name):
        """Each cross-tabulation is anchored on the same all-households total."""
        df = request.getfixturevalue(fixture_name)
        dimension = df.columns[0]
        assert "All households" in set(df[dimension])

    def test_disabled_households_less_food_secure(self, by_disability):
        """Households containing a disabled adult report lower food security."""
        indexed = by_disability.set_index("disability_in_household")["food_secure_pct"]
        with_disability = [k for k in indexed.index if k.lower().startswith("one or more")]
        without_disability = [k for k in indexed.index if k.lower().startswith("no disabled")]
        assert with_disability and without_disability
        assert max(indexed[with_disability]) < min(indexed[without_disability])

    def test_income_related_benefits_least_food_secure(self, by_state_support):
        """Income-related benefit recipients are the least food secure group."""
        indexed = by_state_support.set_index("state_support_received")["food_secure_pct"]
        assert indexed.idxmin() == "On any income-related benefit"

    def test_social_renters_least_food_secure(self, by_tenure):
        """Social renters report the lowest food security of any tenure."""
        indexed = by_tenure.set_index("tenure")["food_secure_pct"]
        assert indexed.idxmin() == "Social renting sector"

    def test_owners_more_food_secure_than_renters(self, by_tenure):
        """Owner-occupiers outrank both rented sectors."""
        indexed = by_tenure.set_index("tenure")["food_secure_pct"]
        assert indexed["All owners"] > indexed["Private renting sector"]
        assert indexed["All owners"] > indexed["Social renting sector"]


# ---------------------------------------------------------------------------
# Chapter 2 - income and state support
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestIncomeAndStateSupport:
    """Tests for the chapter 2 income and state support tables."""

    @pytest.fixture(scope="class")
    def income_sources(self) -> pd.DataFrame:
        return frs.get_income_sources()

    @pytest.fixture(scope="class")
    def support_by_country(self) -> pd.DataFrame:
        return frs.get_state_support_by_country()

    @pytest.fixture(scope="class")
    def support_trend(self) -> pd.DataFrame:
        return frs.get_state_support_trend()

    def test_income_covers_ni_and_uk(self, income_sources):
        """Both the NI figures and the UK comparator must be parsed."""
        assert set(income_sources["area"]) == {"NI", "UK"}

    def test_income_areas_balanced(self, income_sources):
        """NI and UK must be reported for the same years and sources."""
        counts = income_sources.groupby("area").size()
        assert counts["NI"] == counts["UK"]

    def test_income_sources_sum_to_all_sources(self, income_sources):
        """Component shares must reconcile with the published All sources row."""
        components = income_sources[income_sources["income_source"] != "All sources"]
        summed = components.groupby(["financial_year", "area"])["percentage"].sum()
        assert (summed - 100).abs().max() <= 1.5

    def test_income_all_sources_is_100(self, income_sources):
        """The All sources row is published as exactly 100."""
        totals = income_sources[income_sources["income_source"] == "All sources"]["percentage"]
        assert (totals == 100).all()

    def test_income_years_are_financial(self, income_sources):
        """Years must be normalised to YYYY/YY."""
        assert income_sources["financial_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_income_sample_sizes_positive(self, income_sources):
        """Each row carries the achieved sample for its year and area."""
        assert (income_sources["sample_size"] > 0).all()

    def test_uk_sample_larger_than_ni(self, income_sources):
        """The UK sample is an order of magnitude larger than the NI boost."""
        by_area = income_sources.groupby("area")["sample_size"].max()
        assert by_area["UK"] > by_area["NI"] * 5

    def test_ni_more_reliant_on_state_support(self, income_sources):
        """NI households draw a larger income share from state support than the UK."""
        latest = income_sources["financial_year"].max()
        support = income_sources[
            (income_sources["financial_year"] == latest) & (income_sources["income_source"] == "State Support")
        ].set_index("area")["percentage"]
        assert support["NI"] > support["UK"]

    def test_support_by_country_columns(self, support_by_country):
        """The country comparison exposes both NI and UK percentage columns."""
        for column in ("state_support_received", "northern_ireland_pct", "united_kingdom_pct"):
            assert column in support_by_country.columns

    def test_support_by_country_percentages_in_range(self, support_by_country):
        """Both country columns stay within 0-100."""
        assert_percentage_column(support_by_country, "northern_ireland_pct")
        assert_percentage_column(support_by_country, "united_kingdom_pct")

    def test_support_receipt_partitions(self, support_by_country):
        """In receipt and not in receipt must partition households in each country."""
        indexed = support_by_country.set_index("state_support_received")
        receiving = [k for k in indexed.index if k.lower().startswith("all in receipt")]
        not_receiving = [k for k in indexed.index if k.lower().startswith("all not in receipt")]
        assert receiving and not_receiving
        for column in ("northern_ireland_pct", "united_kingdom_pct"):
            total = indexed.loc[receiving[0], column] + indexed.loc[not_receiving[0], column]
            assert abs(total - 100) <= 1.0

    def test_ni_support_receipt_above_uk(self, support_by_country):
        """A larger share of NI households receive state support than UK-wide."""
        indexed = support_by_country.set_index("state_support_received")
        receiving = [k for k in indexed.index if k.lower().startswith("all in receipt")][0]
        assert indexed.loc[receiving, "northern_ireland_pct"] > indexed.loc[receiving, "united_kingdom_pct"]

    def test_support_trend_has_multiple_years(self, support_trend):
        """The trend must span at least three published years."""
        assert support_trend["financial_year"].nunique() >= 3

    def test_support_trend_years_are_financial(self, support_trend):
        """Trend years must be normalised to YYYY/YY."""
        assert support_trend["financial_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_support_trend_percentages_in_range(self, support_trend):
        """Trend percentages stay within 0-100."""
        assert_percentage_column(support_trend, "percentage")

    def test_support_trend_types_consistent_across_years(self, support_trend):
        """Every year must report the same set of support types."""
        by_year = support_trend.groupby("financial_year")["state_support_type"].apply(frozenset)
        assert by_year.nunique() == 1

    def test_support_trend_total_exceeds_components(self, support_trend):
        """The all-recipients figure must be at least the income-related share."""
        pivot = support_trend.pivot_table(index="financial_year", columns="state_support_type", values="percentage")
        total = [c for c in pivot.columns if c.lower().startswith("all in receipt")][0]
        income_related = [c for c in pivot.columns if c.lower().startswith("on any income")][0]
        assert (pivot[total] >= pivot[income_related]).all()


# ---------------------------------------------------------------------------
# Chapter 3 - tenure
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestTenure:
    """Tests for the chapter 3 tenure and housing cost tables."""

    @pytest.fixture(scope="class")
    def trend(self) -> pd.DataFrame:
        return frs.get_tenure_trend()

    @pytest.fixture(scope="class")
    def by_district(self) -> pd.DataFrame:
        return frs.get_tenure_by_district()

    @pytest.fixture(scope="class")
    def cost_burden(self) -> pd.DataFrame:
        return frs.get_housing_cost_burden()

    def test_trend_covers_all_tenures(self, trend):
        """All four published tenure categories must be present."""
        tenures = set(trend["tenure"])
        assert {
            "Owned outright",
            "Buying with a mortgage",
            "Social rented sector",
            "Private rented sector",
        } <= tenures

    def test_trend_sums_to_100_per_year(self, trend):
        """Tenure shares must partition households in every year."""
        totals = trend.groupby("financial_year")["percentage"].sum()
        assert (totals - 100).abs().max() <= 1.5

    def test_trend_years_are_financial(self, trend):
        """Trend years must be normalised to YYYY/YY."""
        assert trend["financial_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_trend_has_multiple_years(self, trend):
        """The tenure series must span at least three published years."""
        assert trend["financial_year"].nunique() >= 3

    def test_trend_owner_occupation_is_majority(self, trend):
        """Owner-occupation remains the majority NI tenure in every year."""
        owned = trend[trend["tenure"].isin(["Owned outright", "Buying with a mortgage"])]
        by_year = owned.groupby("financial_year")["percentage"].sum()
        assert (by_year > 50).all()

    def test_district_coverage(self, by_district):
        """All eleven Local Government Districts must be present."""
        districts = set(by_district["district"])
        assert districts >= DISTRICTS
        assert len(districts) == 11

    def test_district_tenures_consistent(self, by_district):
        """Every district must report the same tenure breakdown."""
        by_area = by_district.groupby("district")["tenure"].apply(frozenset)
        assert by_area.nunique() == 1

    def test_district_percentages_in_range(self, by_district):
        """District percentages stay within 0-100."""
        assert_percentage_column(by_district, "percentage")

    def test_district_sample_sizes_positive(self, by_district):
        """Pooled district samples must be positive."""
        assert (by_district["sample_size"].dropna() > 0).all()

    def test_district_owners_component_reconciles(self, by_district):
        """All owners must equal outright plus mortgage in each district."""
        pivot = by_district.pivot_table(index="district", columns="tenure", values="percentage")
        combined = pivot["Owned outright"] + pivot["Buying with a mortgage"]
        assert (combined - pivot["All owners"]).abs().max() <= 1.5

    def test_belfast_has_lowest_owner_occupation(self, by_district):
        """Belfast City is the least owner-occupied district in NI."""
        owners = by_district[by_district["tenure"] == "All owners"].set_index("district")["percentage"]
        assert owners.idxmin() == "Belfast City"

    def test_cost_burden_columns(self, cost_burden):
        """The housing cost table exposes year, measure and percentage."""
        for column in ("financial_year", "measure", "percentage"):
            assert column in cost_burden.columns

    def test_cost_burden_years_are_financial(self, cost_burden):
        """Housing cost years must be normalised to YYYY/YY."""
        assert cost_burden["financial_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_cost_burden_percentages_in_range(self, cost_burden):
        """Housing cost shares stay within 0-100."""
        assert_percentage_column(cost_burden, "percentage")

    def test_cost_burden_measures_consistent_across_years(self, cost_burden):
        """Every year must report the same measures."""
        by_year = cost_burden.groupby("financial_year")["measure"].apply(frozenset)
        assert by_year.nunique() == 1

    def test_cost_burden_renter_basis_is_higher(self, cost_burden):
        """The renters and mortgage-holders basis exceeds the all-households basis."""
        measures = sorted(set(cost_burden["measure"]))
        assert len(measures) == 2
        pivot = cost_burden.pivot_table(index="financial_year", columns="measure", values="percentage")
        higher = pivot.mean().idxmax()
        lower = pivot.mean().idxmin()
        assert (pivot[higher] >= pivot[lower]).all()


# ---------------------------------------------------------------------------
# Chapter 5 - carers and disability
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestCarersAndDisability:
    """Tests for the chapter 5 carer and disability prevalence tables."""

    @pytest.fixture(scope="class")
    def carers(self) -> pd.DataFrame:
        return frs.get_carer_prevalence()

    @pytest.fixture(scope="class")
    def disability(self) -> pd.DataFrame:
        return frs.get_disability_prevalence()

    @pytest.fixture(scope="class")
    def disability_districts(self) -> pd.DataFrame:
        return frs.get_disability_by_district()

    @pytest.mark.parametrize("fixture_name", ["carers", "disability"])
    def test_prevalence_shape(self, request, fixture_name):
        """Both prevalence series share the same tidy shape."""
        df = request.getfixturevalue(fixture_name)
        for column in ("financial_year", "age_group", "percentage", "sample_size"):
            assert column in df.columns
        assert df["financial_year"].nunique() >= 3

    @pytest.mark.parametrize("fixture_name", ["carers", "disability"])
    def test_prevalence_years_are_financial(self, request, fixture_name):
        """Prevalence years must be normalised to YYYY/YY."""
        df = request.getfixturevalue(fixture_name)
        assert df["financial_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    @pytest.mark.parametrize("fixture_name", ["carers", "disability"])
    def test_prevalence_percentages_in_range(self, request, fixture_name):
        """Prevalence percentages stay within 0-100."""
        assert_percentage_column(request.getfixturevalue(fixture_name), "percentage")

    @pytest.mark.parametrize("fixture_name", ["carers", "disability"])
    def test_prevalence_sample_sizes_positive(self, request, fixture_name):
        """Individual-level samples must be positive."""
        df = request.getfixturevalue(fixture_name)
        assert (df["sample_size"].dropna() > 0).all()

    @pytest.mark.parametrize("fixture_name", ["carers", "disability"])
    def test_prevalence_age_groups_consistent(self, request, fixture_name):
        """Every year must report the same age groups."""
        df = request.getfixturevalue(fixture_name)
        by_year = df.groupby("financial_year")["age_group"].apply(frozenset)
        assert by_year.nunique() == 1

    def test_carer_age_groups(self, carers):
        """The carer table breaks down by working and pension age."""
        assert {"Working age adults", "State pension age adults", "All adults"} <= set(carers["age_group"])

    def test_carer_prevalence_plausible(self, carers):
        """Around one in ten NI adults report caring responsibilities."""
        adults = carers[carers["age_group"] == "All adults"]["percentage"].dropna()
        assert adults.between(5, 20).all()

    def test_disability_age_groups(self, disability):
        """The disability table covers children, adults and all individuals."""
        assert {"Children", "Working age adults", "All adults", "All individuals"} <= set(disability["age_group"])

    def test_disability_rises_with_age(self, disability):
        """Disability prevalence is higher among adults than children."""
        pivot = disability.pivot_table(index="financial_year", columns="age_group", values="percentage")
        assert (pivot["All adults"] > pivot["Children"]).all()

    def test_disability_all_individuals_between_children_and_adults(self, disability):
        """The all-individuals rate must sit between the child and adult rates."""
        pivot = disability.pivot_table(index="financial_year", columns="age_group", values="percentage")
        assert (pivot["All individuals"] <= pivot["All adults"]).all()
        assert (pivot["All individuals"] >= pivot["Children"]).all()

    def test_disability_district_coverage(self, disability_districts):
        """All eleven districts plus the NI total must be present."""
        districts = set(disability_districts["district"])
        assert districts >= DISTRICTS
        assert "Northern Ireland" in districts
        assert len(districts) == 12

    def test_disability_district_percentages_in_range(self, disability_districts):
        """District disability rates stay within 0-100."""
        assert_percentage_column(disability_districts, "percentage")

    def test_disability_district_spread_is_plausible(self, disability_districts):
        """District rates must straddle the NI average without extreme outliers."""
        indexed = disability_districts.set_index("district")["percentage"]
        northern_ireland = indexed["Northern Ireland"]
        districts = indexed.drop("Northern Ireland")
        assert districts.min() < northern_ireland < districts.max()
        assert districts.max() - districts.min() < 30


# ---------------------------------------------------------------------------
# Parsing helpers - no network access required
# ---------------------------------------------------------------------------


class TestParsingHelpers:
    """Unit tests for the sheet-parsing helpers."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("12", 12.0),
            (12, 12.0),
            (12.5, 12.5),
            ("1,234", 1234.0),
            ("45%", 45.0),
            ("£1,200", 1200.0),
            ("-", 0.0),
        ],
    )
    def test_clean_value_parses(self, value, expected):
        """Published numeric formats normalise to floats."""
        assert frs._clean_value(value) == expected

    @pytest.mark.parametrize("value", ["..", "", "   ", "n/a", None])
    def test_clean_value_suppressed_is_nan(self, value):
        """Suppressed, blank and unparseable cells become NaN."""
        assert pd.isna(frs._clean_value(value))

    def test_label_trims(self):
        """Labels are trimmed and stringified."""
        assert frs._label("  Belfast City  ") == "Belfast City"
        assert frs._label(3) == "3"

    def test_label_of_missing_is_empty(self):
        """Missing labels normalise to the empty string."""
        assert frs._label(None) == ""
        assert frs._label(float("nan")) == ""

    @pytest.mark.parametrize("text", ["Notes", "note 1", "Sample size (=100%)", "Source: DfC"])
    def test_is_footer_detects_footers(self, text):
        """Footer blocks terminate the data region."""
        assert frs._is_footer(text)

    @pytest.mark.parametrize("text", ["All households", "Belfast City", "Owned outright", ""])
    def test_is_footer_ignores_data_labels(self, text):
        """Data labels must not be mistaken for footers."""
        assert not frs._is_footer(text)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("2024-25", "2024/25"), ("2024/25", "2024/25"), (" 2023-24 ", "2023/24")],
    )
    def test_normalise_year(self, value, expected):
        """Year labels render consistently as YYYY/YY."""
        assert frs._normalise_year(value) == expected

    def test_find_header_row(self):
        """The header row is located by its leading label."""
        frame = pd.DataFrame([["Table 3.1", None], ["Tenure", "%"], ["All owners", 70]])
        assert frs._find_header_row(frame, "tenure") == 1

    def test_find_header_row_is_case_insensitive(self):
        """Header matching ignores case."""
        frame = pd.DataFrame([["TENURE", "%"], ["All owners", 70]])
        assert frs._find_header_row(frame, "Tenure") == 0

    def test_find_header_row_missing_raises(self):
        """A missing header row raises FRSDataNotFoundError."""
        frame = pd.DataFrame([["Something else", None]])
        with pytest.raises(frs.FRSDataNotFoundError):
            frs._find_header_row(frame, "tenure")

    def test_data_rows_skips_blanks_and_stops_at_footer(self):
        """Blank labels are skipped and the footer ends the block."""
        frame = pd.DataFrame(
            [
                ["Tenure", "%"],
                ["All owners", 70],
                [None, None],
                ["Social rented sector", 12],
                ["Sample size (=100%)", 1739],
                ["Owned outright", 41],
            ]
        )
        assert frs._data_rows(frame, 1) == [1, 3]

    def test_sample_sizes_keyed_by_column(self):
        """Sample sizes are extracted by column label."""
        frame = pd.DataFrame([["Tenure", "NI", "UK"], ["Sample size (=100%)", 1739, 16288]])
        assert frs._sample_sizes(frame, {1: "NI", 2: "UK"}) == {"NI": 1739.0, "UK": 16288.0}

    def test_sample_sizes_absent_returns_empty(self):
        """A table with no sample size row yields no sizes."""
        frame = pd.DataFrame([["Tenure", "NI"], ["All owners", 70]])
        assert frs._sample_sizes(frame, {1: "NI"}) == {}

    def test_composition_sections_carry_down_blocks(self):
        """Adult-count rows inherit the block heading above them."""
        labels = [
            "All households",
            "All households without children",
            "One adult",
            "Three or more adults",
            "All households with children",
            "One adult",
            "Three or more adults",
        ]
        assert frs._composition_sections(labels) == [
            "All households",
            "Without children",
            "Without children",
            "Without children",
            "With children",
            "With children",
            "With children",
        ]

    def test_composition_sections_reset_on_trailing_total(self):
        """A trailing all-households row leaves the nested blocks behind."""
        labels = ["All households with children", "One adult", "Households with one or more disabled"]
        assert frs._composition_sections(labels)[-1] == "All households"
