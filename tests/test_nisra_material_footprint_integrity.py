"""Data integrity tests for the NISRA Northern Ireland Material Footprint.

Live tests read the datavis report found through GOV.UK; the tests from ``TestValidation`` onwards run on
hand-built frames and fake responses and need no network.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import material_footprint as mf
from bolster.data_sources.nisra import population
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError
from bolster.utils.embedded_downloads import EmbeddedTable

MATERIAL_VALUES = {"biomass": 9.0, "metal_ores": 2.0, "fossil_fuels": 8.0, "non_metallic_minerals": 10.0, "total": 29.0}


def _footprint_rows(years=(2020, 2021), values=None):
    values = values or MATERIAL_VALUES
    return pd.DataFrame(
        [(y, m, mf.MEASURE_FOOTPRINT, v) for y in years for m, v in values.items()],
        columns=["year", "material", "measure", "value"],
    )


class TestPublicationDiscovery:
    def test_url_is_datavis_page(self):
        url = mf.get_latest_publication_url()
        assert url.startswith("https://datavis.nisra.gov.uk/")
        assert "footprint" in url.lower()


class TestLatestData:
    @pytest.fixture(scope="class")
    def data(self):
        return mf.get_latest_data()

    def test_columns(self, data):
        assert list(data.columns) == ["year", "material", "measure", "value"]

    def test_measures(self, data):
        assert set(data["measure"]) == {mf.MEASURE_FOOTPRINT, mf.MEASURE_PER_CAPITA}

    def test_materials(self, data):
        footprint = data[data["measure"] == mf.MEASURE_FOOTPRINT]
        assert set(footprint["material"]) == {*mf.MATERIALS, "total"}
        per_capita = data[data["measure"] == mf.MEASURE_PER_CAPITA]
        assert set(per_capita["material"]) == {"total"}

    def test_series_starts_in_2001_and_reaches_2023(self, data):
        assert data["year"].min() == 2001
        assert data["year"].max() >= 2023

    def test_years_contiguous_for_every_series(self, data):
        for (measure, material), group in data.groupby(["measure", "material"]):
            years = sorted(group["year"])
            assert years == list(range(years[0], years[-1] + 1)), (measure, material)

    def test_totals_are_plausible_million_tonnes(self, data):
        totals = data[(data["measure"] == mf.MEASURE_FOOTPRINT) & (data["material"] == "total")]["value"]
        assert totals.between(25, 45).all(), totals.describe()

    def test_per_capita_is_plausible(self, data):
        per_capita = data[data["measure"] == mf.MEASURE_PER_CAPITA]["value"]
        assert per_capita.between(10, 30).all(), per_capita.describe()

    def test_no_missing_values(self, data):
        assert data["value"].notna().all()

    def test_validates(self, data):
        assert mf.validate_data(data) is True

    def test_groups_sum_to_total_within_rounding(self, data):
        wide = data[data["measure"] == mf.MEASURE_FOOTPRINT].pivot(index="year", columns="material", values="value")
        gap = (wide[list(mf.MATERIALS)].sum(axis=1) - wide["total"]).abs()
        assert gap.max() <= mf.SUM_TOLERANCE_MT

    def test_per_capita_follows_from_total_and_population(self, data):
        footprint = data[data["measure"] == mf.MEASURE_FOOTPRINT]
        per_capita = mf.get_per_capita()
        assert mf.validate_per_capita(footprint, per_capita) is True


class TestPopulationCrossValidation:
    """Figure 2's population denominator is NISRA's mid-year estimate, so it can be checked against the population module."""

    @pytest.fixture(scope="class")
    def per_capita(self):
        return mf.get_per_capita().set_index("year")

    @pytest.fixture(scope="class")
    def ni_population(self):
        pop = population.get_latest_population(area="Northern Ireland")
        return pop[pop["sex"] == "All persons"].groupby("year")["population"].sum()

    def test_population_matches_mid_year_estimates(self, per_capita, ni_population):
        # Both are NISRA mid-year estimates. A later rebase can revise earlier years, so allow 0.5% (about 9,500
        # people): enough for revisions, far tighter than a misread column or the wrong geography.
        common = per_capita.index.intersection(ni_population.index)
        assert len(common) == len(per_capita), "every footprint year should have a mid-year estimate"
        relative = (per_capita.loc[common, "population"] / ni_population.loc[common] - 1).abs()
        assert relative.max() < 0.005, relative.sort_values().tail(3)


class TestValidation:
    def test_valid_frame(self):
        assert mf.validate_data(_footprint_rows()) is True

    def test_missing_columns(self):
        with pytest.raises(NISRAValidationError, match="Missing columns"):
            mf.validate_data(_footprint_rows().drop(columns=["measure"]))

    def test_empty_frame(self):
        with pytest.raises(NISRAValidationError, match="No material footprint rows"):
            mf.validate_data(_footprint_rows().iloc[0:0])

    def test_non_footprint_rows_only(self):
        frame = _footprint_rows().assign(measure=mf.MEASURE_PER_CAPITA)
        with pytest.raises(NISRAValidationError, match="No material footprint rows"):
            mf.validate_data(frame)

    def test_non_positive_value(self):
        frame = _footprint_rows()
        frame.loc[0, "value"] = 0.0
        with pytest.raises(NISRAValidationError, match="positive"):
            mf.validate_data(frame)

    def test_gap_in_years(self):
        with pytest.raises(NISRAValidationError, match="contiguous"):
            mf.validate_data(_footprint_rows(years=(2018, 2020)))

    def test_missing_material(self):
        values = {k: v for k, v in MATERIAL_VALUES.items() if k != "fossil_fuels"}
        with pytest.raises(NISRAValidationError, match="Missing materials"):
            mf.validate_data(_footprint_rows(values=values))

    def test_groups_not_adding_to_total(self):
        values = {**MATERIAL_VALUES, "total": 33.0}
        with pytest.raises(NISRAValidationError, match="differ from the total"):
            mf.validate_data(_footprint_rows(values=values))

    def test_rounding_sized_gap_is_allowed(self):
        values = {**MATERIAL_VALUES, "total": 29.2}
        assert mf.validate_data(_footprint_rows(values=values)) is True

    def test_kilotonnes_are_refused_not_converted(self):
        values = {k: v * 1000 for k, v in MATERIAL_VALUES.items()}
        with pytest.raises(NISRAValidationError, match="cannot be million tonnes"):
            mf.validate_data(_footprint_rows(values=values))

    def test_per_capita_consistent(self):
        footprint = _footprint_rows(years=(2020,))
        per_capita = pd.DataFrame({"year": [2020], "population": [1_900_000], "per_capita_tonnes": [15.3]})
        assert mf.validate_per_capita(footprint, per_capita) is True

    def test_per_capita_inconsistent(self):
        footprint = _footprint_rows(years=(2020,))
        per_capita = pd.DataFrame({"year": [2020], "population": [1_900_000], "per_capita_tonnes": [20.0]})
        with pytest.raises(NISRAValidationError, match="differ from total / population"):
            mf.validate_per_capita(footprint, per_capita)

    def test_per_capita_years_differ(self):
        footprint = _footprint_rows(years=(2020, 2021))
        per_capita = pd.DataFrame({"year": [2020], "population": [1_900_000], "per_capita_tonnes": [15.3]})
        with pytest.raises(NISRAValidationError, match="years differ"):
            mf.validate_per_capita(footprint, per_capita)


class TestTableFinding:
    @staticmethod
    def _table(title, **columns):
        return EmbeddedTable(label="Figure", title=title, data=pd.DataFrame(columns))

    def test_found_by_title_not_position(self):
        tables = {
            "Figure 1": self._table("Figure 1: Material footprint per capita, Northern Ireland", year=[2020]),
            "Figure 2": self._table("Figure 2: Material footprint trends, total and by material group", year=[2020]),
        }
        found = mf._find_table(tables, mf._FOOTPRINT_TITLE_RE, "trends")
        assert "trends" in found.title

    def test_missing_table_names_what_was_found(self):
        tables = {"Figure 1": self._table("Figure 1: Something else", year=[2020])}
        with pytest.raises(NISRADataNotFoundError, match="Something else"):
            mf._find_table(tables, mf._FOOTPRINT_TITLE_RE, "trends")

    def test_ambiguous_title_is_refused(self):
        title = "Figure 1: Material footprint per capita, Northern Ireland"
        tables = {"Figure 1": self._table(title, year=[2020]), "Figure 2": self._table(title, year=[2020])}
        with pytest.raises(NISRAValidationError, match="2 tables match"):
            mf._find_table(tables, mf._PER_CAPITA_TITLE_RE, "per capita")

    def test_old_column_name_is_mapped(self):
        table = self._table(
            "x",
            year=[2020],
            biomass=[1.0],
            ore_materials=[2.0],
            fossil_fuels=[3.0],
            non_metallic_minerals=[4.0],
            total=[10.0],
        )
        frame = mf._numeric_frame(table, ["year", *mf.MATERIALS, "total"], "trends")
        assert frame.loc[0, "metal_ores"] == 2.0

    def test_missing_column_is_named(self):
        table = self._table("x", year=[2020], biomass=[1.0])
        with pytest.raises(NISRADataNotFoundError, match="metal_ores"):
            mf._numeric_frame(table, ["year", "biomass", "metal_ores"], "trends")

    def test_blank_cell_is_refused(self):
        table = self._table("x", year=[2020, 2021], biomass=[1.0, None])
        with pytest.raises(NISRAValidationError, match="blank or unreadable"):
            mf._numeric_frame(table, ["year", "biomass"], "trends")

    def test_empty_spacer_rows_are_dropped(self):
        table = self._table("x", year=[2020, None], biomass=[1.0, None])
        frame = mf._numeric_frame(table, ["year", "biomass"], "trends")
        assert len(frame) == 1


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestDiscoveryRules:
    """The latest edition only: an older edition is never returned in its place."""

    SEARCH = {
        "results": [
            {
                "title": "Material Footprint in Northern Ireland 2001 to 2022",
                "link": "/government/publications/old-edition",
                "public_timestamp": "2025-12-18T09:30:00+00:00",
            },
            {
                "title": "Northern Ireland's Material Footprint: 2001 to 2023",
                "link": "/government/statistics/new-edition",
                "public_timestamp": "2026-10-21T09:30:00+01:00",
            },
            {
                "title": "UK material footprint",
                "link": "/government/statistics/uk-edition",
                "public_timestamp": "2026-11-30T09:30:00+00:00",
            },
        ]
    }

    @staticmethod
    def _fake_get(search, content):
        def fake(url, **kwargs):
            if url.endswith("search.json"):
                return _FakeResponse(search)
            return _FakeResponse(content[url.removeprefix(mf.CONTENT_API_URL)])

        return fake

    def test_newest_northern_ireland_edition_wins(self, monkeypatch):
        content = {
            "/government/statistics/new-edition": {
                "details": {"attachments": [{"url": "https://datavis.nisra.gov.uk/new.html"}]}
            },
            "/government/publications/old-edition": {
                "details": {"attachments": [{"url": "https://datavis.nisra.gov.uk/old.html"}]}
            },
        }
        monkeypatch.setattr(mf.session, "get", self._fake_get(self.SEARCH, content))
        assert mf.get_latest_publication_url() == "https://datavis.nisra.gov.uk/new.html"

    def test_latest_without_datavis_page_raises_rather_than_using_older_edition(self, monkeypatch):
        content = {
            "/government/statistics/new-edition": {
                "details": {"attachments": [{"url": "https://example.org/report.pdf"}]}
            },
            "/government/publications/old-edition": {
                "details": {"attachments": [{"url": "https://datavis.nisra.gov.uk/old.html"}]}
            },
        }
        monkeypatch.setattr(mf.session, "get", self._fake_get(self.SEARCH, content))
        with pytest.raises(NISRADataNotFoundError, match="earlier edition is not substituted"):
            mf.get_latest_publication_url()

    def test_no_editions_found(self, monkeypatch):
        monkeypatch.setattr(mf.session, "get", self._fake_get({"results": []}, {}))
        with pytest.raises(NISRADataNotFoundError, match="No Northern Ireland material footprint release"):
            mf.get_latest_publication_url()
