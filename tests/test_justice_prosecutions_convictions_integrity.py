"""Integrity tests for the DoJ prosecutions and convictions module.

Tests use real data downloaded from justice-ni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures and cached for
the duration of the test session. Parsing and validation edge cases are
covered by network-free unit tests.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import prosecutions_convictions as pcd
from bolster.data_sources.justice.prosecutions_convictions import (
    ProsecutionsDataNotFoundError,
    ProsecutionsValidationError,
)


class TestPublicationDiscovery:
    """Discovery of annual bulletins from the DoJ series page."""

    @pytest.fixture(scope="class")
    def publications(self):
        return pcd.list_publications()

    def test_publications_found(self, publications):
        assert len(publications) >= 10

    def test_required_columns(self, publications):
        assert set(publications.columns) == {"year", "title", "url"}

    def test_years_plausible(self, publications):
        assert publications.year.between(2007, 2100).all()

    def test_sorted_newest_first(self, publications):
        assert list(publications.year) == sorted(publications.year, reverse=True)

    def test_urls_unique(self, publications):
        assert publications.url.is_unique

    def test_urls_absolute(self, publications):
        assert publications.url.str.startswith("https://").all()

    def test_latest_is_recent(self, publications):
        """The series is annual, so the newest bulletin should be current."""
        assert publications.year.max() >= 2025

    def test_find_publication_defaults_to_latest(self, publications):
        assert pcd.find_publication()["year"] == publications.year.max()

    def test_find_publication_by_year(self):
        assert pcd.find_publication(2022)["year"] == 2022

    def test_find_publication_unknown_year_raises(self):
        with pytest.raises(ProsecutionsDataNotFoundError, match="No publication found for year"):
            pcd.find_publication(1990)


class TestWorkbookDiscovery:
    """Resolution of a publication page to its ODS workbook."""

    @pytest.fixture(scope="class")
    def data_url(self):
        return pcd.get_data_file_url(str(pcd.find_publication()["url"]))

    def test_is_ods(self, data_url):
        assert data_url.lower().endswith(".ods")

    def test_prefers_accessibility_format(self, data_url):
        assert "accessib" in data_url.lower()

    def test_download_returns_existing_file(self, data_url):
        path = pcd.download_file(data_url)
        assert path.exists()
        assert path.stat().st_size > 10_000


class TestFullDatasetIntegrity:
    """Integrity of the combined long frame across every sub-table."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return pcd.get_latest_data()

    def test_required_columns(self, latest_data):
        expected = {"table_id", "table_title", "row_label", "row_group", "column", "value"}
        assert set(latest_data.columns) == expected

    def test_not_empty(self, latest_data):
        assert len(latest_data) > 1500

    def test_many_subtables(self, latest_data):
        """The bulletin spans roughly thirty sub-tables across 16 worksheets."""
        assert latest_data.table_id.nunique() >= 25

    def test_table_titles_populated(self, latest_data):
        assert (latest_data.table_title.str.len() > 0).all()

    def test_no_note_refs_left_in_titles(self, latest_data):
        assert not latest_data.table_title.str.contains(r"\[note", case=False).any()

    def test_no_note_refs_left_in_labels(self, latest_data):
        assert not latest_data.row_label.str.contains(r"\[note", case=False).any()

    def test_no_filler_columns(self, latest_data):
        """Spreadsheet autofill leaves 'Column1' headers past the real data."""
        assert not latest_data.column.str.fullmatch(r"Column\d+", case=False).any()

    def test_values_non_negative(self, latest_data):
        assert (latest_data.value.dropna() >= 0).all()

    def test_values_mostly_populated(self, latest_data):
        """Suppression markers exist but should be a small minority."""
        assert latest_data.value.isna().mean() < 0.05

    def test_large_values_parsed(self, latest_data):
        """Court disposals run to tens of thousands; catches separator bugs."""
        assert latest_data.value.max() > 20_000

    def test_row_group_used_by_some_tables(self, latest_data):
        """Two-label tables (e.g. disposal by gender) populate row_group."""
        assert latest_data.row_group.notna().any()

    def test_row_group_absent_from_most(self, latest_data):
        assert latest_data.row_group.isna().mean() > 0.5

    def test_validate_passes(self, latest_data):
        assert pcd.validate_data(latest_data) is True


class TestSchemaStabilityAcrossYears:
    """Older bulletins must parse with the same schema."""

    @pytest.fixture(scope="class")
    def older_data(self):
        return pcd.get_latest_data(year=2022)

    def test_same_columns_as_latest(self, older_data):
        assert set(older_data.columns) == set(pcd.get_latest_data().columns)

    def test_not_empty(self, older_data):
        assert len(older_data) > 1500

    def test_values_mostly_populated(self, older_data):
        assert older_data.value.isna().mean() < 0.05

    def test_validate_passes(self, older_data):
        assert pcd.validate_data(older_data) is True


class TestListTables:
    """The table index derived from a bulletin."""

    @pytest.fixture(scope="class")
    def tables(self):
        return pcd.list_tables()

    def test_columns(self, tables):
        assert list(tables.columns) == ["table_id", "table_title", "records"]

    def test_ids_unique(self, tables):
        assert tables.table_id.is_unique

    def test_every_table_has_records(self, tables):
        assert (tables.records > 0).all()

    def test_sorted_numerically(self, tables):
        """'2a' must sort before '10', which string ordering would invert."""
        leading = tables.table_id.str.extract(r"^(\d+)")[0].astype(int)
        assert list(leading) == sorted(leading)


class TestCasesDealtWith:
    """Summary series of court versus out of court disposals."""

    @pytest.fixture(scope="class")
    def cases(self):
        return pcd.get_cases_dealt_with()

    def test_columns(self, cases):
        assert list(cases.columns) == ["year", "category", "cases"]

    def test_year_dtype_integer(self, cases):
        assert pd.api.types.is_integer_dtype(cases.year)

    def test_historical_coverage(self, cases):
        assert cases.year.max() - cases.year.min() >= 9

    def test_recent_coverage(self, cases):
        assert cases.year.max() >= 2025

    def test_years_contiguous(self, cases):
        years = sorted(cases.year.unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_expected_categories(self, cases):
        assert {"All cases disposed", "Court disposals", "Out of court disposals"} == set(cases.category)

    def test_components_sum_to_total(self, cases):
        """Court plus out of court disposals must equal all cases disposed."""
        wide = cases.pivot(index="year", columns="category", values="cases")
        components = wide["Court disposals"] + wide["Out of court disposals"]
        assert (components == wide["All cases disposed"]).all()

    def test_volumes_plausible(self, cases):
        """NI disposes of roughly 30,000-60,000 cases a year."""
        totals = cases[cases.category == "All cases disposed"].cases
        assert totals.between(20_000, 100_000).all()


class TestProsecutionsConvictions:
    """Conviction rates by court tier."""

    @pytest.fixture(scope="class")
    def convictions(self):
        return pcd.get_prosecutions_convictions()

    def test_columns(self, convictions):
        expected = ["year", "court", "convictions", "no_convictions", "total_findings", "conviction_rate"]
        assert list(convictions.columns) == expected

    def test_year_dtype_integer(self, convictions):
        assert pd.api.types.is_integer_dtype(convictions.year)

    def test_all_court_tiers_present(self, convictions):
        courts = {c.lower() for c in convictions.court}
        assert any("crown" in c for c in courts)
        assert any("magistrates" in c for c in courts)
        assert any("all courts" in c for c in courts)

    def test_conviction_rate_is_proportion(self, convictions):
        """Published as a percentage; the accessor scales it to [0, 1]."""
        assert convictions.conviction_rate.dropna().between(0, 1).all()

    def test_conviction_rate_plausible(self, convictions):
        """NI conviction rates sit in the low-to-high eighties."""
        assert convictions.conviction_rate.dropna().between(0.7, 0.95).all()

    def test_findings_sum(self, convictions):
        """Convictions plus non-convictions must equal total findings."""
        rows = convictions.dropna(subset=["convictions", "no_convictions", "total_findings"])
        assert (rows.convictions + rows.no_convictions == rows.total_findings).all()

    def test_rate_matches_components(self, convictions):
        """The published percentage must agree with the counts."""
        rows = convictions.dropna(subset=["convictions", "total_findings", "conviction_rate"])
        derived = rows.convictions / rows.total_findings
        assert (derived - rows.conviction_rate).abs().max() < 0.01

    def test_counts_non_negative(self, convictions):
        assert (convictions.convictions.dropna() >= 0).all()
        assert (convictions.no_convictions.dropna() >= 0).all()

    def test_all_courts_is_the_largest_tier(self, convictions):
        """The 'all courts' row must dominate each individual tier."""
        latest = convictions[convictions.year == convictions.year.max()]
        combined = latest[latest.court.str.contains("all courts", case=False)]
        tiers = latest[~latest.court.str.contains("all courts", case=False)]
        assert combined.total_findings.iloc[0] >= tiers.total_findings.max()


class TestOutOfCourtDisposals:
    """Disposal types issued without a court appearance."""

    @pytest.fixture(scope="class")
    def disposals(self):
        return pcd.get_out_of_court_disposals()

    def test_columns(self, disposals):
        assert list(disposals.columns) == ["year", "disposal_type", "disposals"]

    def test_year_dtype_integer(self, disposals):
        assert pd.api.types.is_integer_dtype(disposals.year)

    def test_expected_disposal_types(self, disposals):
        types = set(disposals.disposal_type)
        assert "Caution" in types
        assert "Total" in types
        assert any("Penalty Notice" in t for t in types)

    def test_components_sum_to_total(self, disposals):
        wide = disposals.pivot(index="year", columns="disposal_type", values="disposals")
        components = wide.drop(columns="Total").sum(axis=1)
        assert ((components - wide["Total"]).abs() <= 1).all()

    def test_values_non_negative(self, disposals):
        assert (disposals.disposals.dropna() >= 0).all()

    def test_totals_match_cases_dealt_with(self, disposals):
        """The out of court total must agree with the summary table."""
        cases = pcd.get_cases_dealt_with()
        summary = cases[cases.category == "Out of court disposals"].set_index("year").cases
        totals = disposals[disposals.disposal_type == "Total"].set_index("year").disposals
        shared = summary.index.intersection(totals.index)
        assert len(shared) >= 5
        assert (summary[shared] == totals[shared]).all()


class TestDiversionaryDisposals:
    """Diversionary disposals broken down by gender and age."""

    @pytest.fixture(scope="class")
    def by_gender(self):
        return pcd.get_diversionary_disposals(by="gender")

    @pytest.fixture(scope="class")
    def by_age(self):
        return pcd.get_diversionary_disposals(by="age")

    def test_gender_columns(self, by_gender):
        assert list(by_gender.columns) == ["year", "category", "disposals"]

    def test_gender_categories(self, by_gender):
        assert {"Male", "Female", "Total"}.issubset(set(by_gender.category))

    def test_age_bands_present(self, by_age):
        assert any("-" in c for c in by_age.category)

    def test_age_has_more_categories_than_gender(self, by_gender, by_age):
        assert by_age.category.nunique() > by_gender.category.nunique()

    def test_both_cover_same_years(self, by_gender, by_age):
        assert set(by_gender.year) == set(by_age.year)

    def test_gender_components_sum_to_total(self, by_gender):
        wide = by_gender.pivot(index="year", columns="category", values="disposals")
        components = wide.drop(columns="Total").sum(axis=1)
        assert ((components - wide["Total"]).abs() <= 1).all()

    def test_values_non_negative(self, by_gender, by_age):
        assert (by_gender.disposals.dropna() >= 0).all()
        assert (by_age.disposals.dropna() >= 0).all()

    def test_unknown_breakdown_raises(self):
        with pytest.raises(ValueError, match="Unknown breakdown"):
            pcd.get_diversionary_disposals(by="ethnicity")


class TestTableSelection:
    """Unit tests for title-based table selection - no network calls needed."""

    @staticmethod
    def _frame():
        return pd.DataFrame(
            {
                "table_title": ["Cases dealt with by outcome", "Out of court disposals by type"],
                "column": ["2024", "Percentage 2025"],
                "value": [1.0, 2.0],
            }
        )

    def test_selects_matching_title(self):
        selected = pcd._select_table(self._frame(), r"^Cases dealt with")
        assert len(selected) == 1

    def test_case_insensitive(self):
        assert len(pcd._select_table(self._frame(), r"^cases DEALT with")) == 1

    def test_no_match_raises(self):
        with pytest.raises(ProsecutionsDataNotFoundError, match="No table matching"):
            pcd._select_table(self._frame(), r"^Nonexistent table")

    def test_year_columns_drops_percentage_column(self):
        """'Percentage 2025' headers would break int coercion of the year."""
        kept = pcd._year_columns(self._frame())
        assert list(kept.column) == ["2024"]


class TestLabelColumnDetection:
    """Unit tests for label column counting - no network calls needed."""

    def test_single_label_column(self):
        rows = [["Caution", "100", "200"], ["Total", "300", "400"]]
        assert pcd._label_column_count(rows) == 1

    def test_two_label_columns(self):
        rows = [["Male", "Custody", "10"], ["Female", "Fine", "20"]]
        assert pcd._label_column_count(rows) == 2

    def test_never_returns_zero(self):
        """A fully numeric block still needs one column treated as a label."""
        assert pcd._label_column_count([["1", "2"], ["3", "4"]]) == 1

    def test_blank_cell_ends_label_run(self):
        rows = [["Caution", "Custody", "10"], ["Total", "", "20"]]
        assert pcd._label_column_count(rows) == 1

    def test_ragged_rows_tolerated(self):
        rows = [["Caution", "Custody", "10"], ["Total"]]
        assert pcd._label_column_count(rows) == 1


class TestBlockSplitting:
    """Unit tests for worksheet block splitting - no network calls needed."""

    def test_splits_on_table_markers(self):
        rows = [
            ["Table 2a: First table"],
            ["Year", "2024"],
            ["Caution", "10"],
            ["Table 2b: Second table"],
            ["Year", "2024"],
            ["Total", "20"],
        ]
        blocks = pcd._split_blocks(rows)
        assert len(blocks) == 2
        assert blocks[0][0] == "Table 2a: First table"
        assert blocks[1][0] == "Table 2b: Second table"

    def test_commentary_rows_ignored(self):
        rows = [["Table 1: Only table"], ["Source: DoJ NI"], ["Year", "2024"], ["Total", "5"]]
        blocks = pcd._split_blocks(rows)
        assert len(blocks) == 1
        assert len(blocks[0][1]) == 2

    def test_untitled_block(self):
        blocks = pcd._split_blocks([["Year", "2024"], ["Total", "5"]])
        assert blocks[0][0] is None

    def test_empty_input(self):
        assert pcd._split_blocks([]) == []


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    @staticmethod
    def _frame(n=1000, **overrides):
        data = {
            "table_id": ["2a"] * n,
            "table_title": ["Cases dealt with"] * n,
            "row_label": ["Total"] * n,
            "row_group": [None] * n,
            "column": ["2024"] * n,
            "value": [1.0] * n,
        }
        data.update(overrides)
        return pd.DataFrame(data)

    def test_validate_empty_dataframe(self):
        with pytest.raises(ProsecutionsValidationError, match="empty"):
            pcd.validate_data(pd.DataFrame())

    def test_validate_none(self):
        with pytest.raises(ProsecutionsValidationError, match="empty"):
            pcd.validate_data(None)

    def test_validate_missing_columns(self):
        with pytest.raises(ProsecutionsValidationError, match="Missing required columns"):
            pcd.validate_data(self._frame().drop(columns=["value"]))

    def test_validate_too_few_records(self):
        with pytest.raises(ProsecutionsValidationError, match="Too few records"):
            pcd.validate_data(self._frame(n=10))

    def test_validate_negative_values(self):
        with pytest.raises(ProsecutionsValidationError, match="Negative values"):
            pcd.validate_data(self._frame(value=[-1.0] * 1000))

    def test_validate_too_many_unparsed(self):
        values = [float("nan")] * 500 + [1.0] * 500
        with pytest.raises(ProsecutionsValidationError, match="Too many unparsed values"):
            pcd.validate_data(self._frame(value=values))

    def test_validate_custom_min_records(self):
        assert pcd.validate_data(self._frame(n=20), min_records=10) is True

    def test_validate_tolerates_some_suppression(self):
        values = [float("nan")] * 100 + [1.0] * 900
        assert pcd.validate_data(self._frame(value=values)) is True
