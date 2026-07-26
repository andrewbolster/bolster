"""Integrity tests for DfC Child Maintenance Service statistics.

Tests use real data from the Department for Communities (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures. Parsing and
validation edge cases are covered by network-free unit tests.
"""

import datetime

import pandas as pd
import pytest

from bolster.data_sources.dfc import child_maintenance as cm


@pytest.fixture(scope="session")
def cms_publications():
    """Publication list for the whole session, doubling as a reachability probe.

    The DfC site answers 503 to CI runner IPs, and the shared session's retry
    ladder makes every blocked call cost ~90 seconds. Probing once keeps a bad
    day cheap instead of timing the job out.
    """
    try:
        return cm.list_publications()
    except cm.CMSDataNotFoundError as e:
        pytest.skip(f"communities-ni.gov.uk unavailable: {e}")


@pytest.fixture(autouse=True)
def _require_cms_service(request):
    if request.node.get_closest_marker("integration"):
        request.getfixturevalue("cms_publications")


def _fetch(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except cm.CMSDataNotFoundError as e:
        pytest.skip(f"communities-ni.gov.uk unavailable: {e}")


@pytest.mark.integration
class TestPublicationDiscovery:
    """Publications are discovered from the topic page."""

    @pytest.fixture(scope="class")
    def publications(self, cms_publications):
        return cms_publications

    def test_publications_found(self, publications):
        assert len(publications) >= 10

    def test_publications_have_period(self, publications):
        for publication in publications:
            assert 2015 <= publication["year"] <= datetime.date.today().year + 1
            assert publication["month"] in {3, 6, 9, 12}

    def test_publications_newest_first(self, publications):
        periods = [(p["year"], p["month"]) for p in publications]
        assert periods == sorted(periods, reverse=True)

    def test_publication_urls_unique(self, publications):
        urls = [p["url"] for p in publications]
        assert len(set(urls)) == len(urls)

    def test_xlsx_locatable(self, publications):
        url = _fetch(cm.find_publication_xlsx, publications[0]["url"])
        assert url.lower().endswith(".xlsx")

    def test_missing_publication_raises(self):
        with pytest.raises(cm.CMSDataNotFoundError):
            cm.find_publication_xlsx("https://www.communities-ni.gov.uk/publications/no-such-publication-data-june-2020")


@pytest.mark.integration
class TestLatestPublication:
    """The most recent workbook parses into a well-formed tidy frame."""

    @pytest.fixture(scope="class")
    def df(self):
        return _fetch(cm.get_latest_data)

    def test_validates(self, df):
        assert cm.validate_data(df)

    def test_all_tables_present(self, df):
        assert set(df["table"]) == set(cm.list_tables())

    def test_no_duplicate_observations(self, df):
        keys = ["table", "date", "category", "subcategory", "measure"]
        assert not df.duplicated(subset=keys).any()

    def test_dates_are_quarter_ends(self, df):
        assert (df["date"] == df["date"] + pd.offsets.QuarterEnd(0)).all()

    def test_measures_match_tables(self, df):
        money = df[df["table"].isin({"maintenance", "enforcement"})]
        assert set(money["measure"]) == {"amount_gbp"}
        assert "amount_gbp" not in set(df[~df["table"].isin({"maintenance", "enforcement"})]["measure"])

    def test_labels_are_clean(self, df):
        for column in ("category", "subcategory"):
            assert not df[column].str.strip().ne(df[column]).any()
            assert not df[column].str.contains("  ").any()

    def test_enforcement_components_do_not_exceed_total(self, df):
        enforcement = df[df["table"] == "enforcement"]
        latest = enforcement[enforcement["date"] == enforcement["date"].max()]
        total = latest[latest["subcategory"] == "Total"]["value"].iloc[0]
        components = latest[latest["subcategory"] != "Total"]["value"].sum()
        # Rounding to the nearest 100 keeps components within ~1% of the total
        assert components == pytest.approx(total, rel=0.01)

    def test_maintenance_paid_below_due(self, df):
        maintenance = df[df["table"] == "maintenance"]
        pivot = maintenance.pivot_table(index="date", columns="subcategory", values="value")
        assert (pivot["Maintenance paid through Collect & Pay"] <= pivot["Maintenance due to be paid through Collect & Pay"]).all()

    def test_characteristics_proportions_sum_per_group(self, df):
        characteristics = df[(df["table"] == "paying_parent_characteristics") & (df["measure"] == "proportion")]
        for (_, category), group in characteristics.groupby(["date", "category"]):
            if category == "Total":
                continue
            assert group["value"].sum() == pytest.approx(1.0, abs=0.02)


@pytest.mark.integration
class TestHistoricalStitching:
    """Merging releases extends short tables without double-counting."""

    @pytest.fixture(scope="class")
    def df(self):
        return _fetch(cm.get_historical_data, max_publications=6)

    def test_validates(self, df):
        assert cm.validate_data(df)

    def test_no_duplicate_observations(self, df):
        keys = ["table", "date", "category", "subcategory", "measure"]
        assert not df.duplicated(subset=keys).any()

    def test_extends_beyond_single_release(self, df):
        latest = _fetch(cm.get_latest_data)
        assert df["date"].min() < latest["date"].min()

    def test_characteristics_gain_quarters(self, df):
        latest = _fetch(cm.get_latest_data)
        table = "paying_parent_characteristics"
        assert df[df["table"] == table]["date"].nunique() > latest[latest["table"] == table]["date"].nunique()

    def test_enforcement_and_maintenance_stay_separate(self, df):
        """Older releases number the money tables differently; see _table_for_sheet."""
        enforcement = set(df[df["table"] == "enforcement"]["subcategory"])
        maintenance = set(df[df["table"] == "maintenance"]["subcategory"])
        assert "Liability Order" in enforcement
        assert not maintenance & enforcement

    def test_series_are_contiguous(self, df):
        """A renamed label would show as a series that stops when its twin starts."""
        for (table, subcategory, measure), group in df.groupby(["table", "subcategory", "measure"]):
            dates = sorted(group["date"])
            expected = pd.date_range(dates[0], dates[-1], freq="QE")
            missing = set(expected) - set(dates)
            assert not missing, f"{table}/{subcategory}/{measure} missing {sorted(missing)}"


@pytest.mark.integration
class TestTableAccessors:
    """Per-table helpers slice the frame they are given."""

    @pytest.fixture(scope="class")
    def df(self):
        return _fetch(cm.get_latest_data)

    @pytest.mark.parametrize(
        ("accessor", "table"),
        [
            (cm.get_applications, "applications"),
            (cm.get_clearances, "clearances"),
            (cm.get_arrangements, "arrangements"),
            (cm.get_children_covered, "children_covered"),
            (cm.get_paying_parents, "paying_parents"),
            (cm.get_characteristics, "paying_parent_characteristics"),
            (cm.get_maintenance, "maintenance"),
            (cm.get_enforcement, "enforcement"),
        ],
    )
    def test_accessor_returns_its_table(self, df, accessor, table):
        subset = accessor(df)
        assert not subset.empty
        assert set(subset["table"]) == {table}

    def test_list_tables_from_frame(self, df):
        assert cm.list_tables(df) == sorted(cm.list_tables())


class TestSheetIdentification:
    """Sheets are identified by title because their numbering shifts."""

    @staticmethod
    def _sheet(*rows):
        return pd.DataFrame([[row] for row in rows])

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Table 1. Applications to the Northern Ireland Child Maintenance Service", "applications"),
            ("Table 2. Application Clearances", "clearances"),
            ("Table 3. Composition of Child Maintenance Arrangements", "arrangements"),
            ("Table 4. Children Covered1 by the Northern Ireland Child Maintenance Service", "children_covered"),
            ("Table 5. Paying Parents Compliance", "paying_parents"),
            ("Table 5. Paying Parents Due to Pay Child Maintenance", "paying_parents"),
            ("Table 6. Paying Parent Characteristics", "paying_parent_characteristics"),
            ("Table 6. Money Due and Paid", "maintenance"),
            ("Table 7. Money Due and Paid", "maintenance"),
            ("Table 7. Child Maintenance Due and Paid", "maintenance"),
            ("Table 7. Enforcement Collections", "enforcement"),
            ("Table 8. Enforcement Collections", "enforcement"),
        ],
    )
    def test_title_wins_over_number(self, title, expected):
        assert cm._table_for_sheet(self._sheet("Back to Contents", title)) == expected

    def test_front_matter_ignored(self):
        sheet = self._sheet("Northern Ireland Child Maintenance Service Statistics", "Contents")
        assert cm._table_for_sheet(sheet) is None

    def test_unknown_table_ignored(self):
        assert cm._table_for_sheet(self._sheet("Table 9. Something New")) is None

    def test_title_beyond_search_window_ignored(self):
        rows = ["", "", "", "", "", "", "", "", "Table 1. Applications to the Northern Ireland CMS"]
        assert cm._table_for_sheet(self._sheet(*rows)) is None


class TestLabelCleaning:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("6Regular Deduction Order", "Regular Deduction Order"),
            ("Children Covered1", "Children Covered"),
            ("Paid up to 90% of Child  Maintenance", "Paid up to 90% of Child Maintenance"),
            ("  Direct Pay  ", "Direct Pay"),
            (">1 Case", ">1 Case"),
            ("1 Qualifing Child", "1 Qualifing Child"),
            ("20-29", "20-29"),
            (None, ""),
            (float("nan"), ""),
        ],
    )
    def test_clean_label(self, raw, expected):
        assert cm._clean_label(raw) == expected


class TestValueParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (1234, 1234.0),
            (12.5, 12.5),
            ("1,234", 1234.0),
            ("£1,234", 1234.0),
            ("45%", None),
            ("-", None),
            (":", None),
            ("", None),
            (None, None),
            (float("nan"), None),
            ("not a number", None),
        ],
    )
    def test_parse_value(self, raw, expected):
        assert cm._parse_value(raw) == expected


class TestQuarterParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Dec-20", datetime.date(2020, 12, 31)),
            ("Mar-26", datetime.date(2026, 3, 31)),
            (datetime.date(2021, 3, 31), datetime.date(2021, 3, 31)),
            (pd.Timestamp("2021-06-30"), datetime.date(2021, 6, 30)),
            # Dates are stamped at the first of the quarter's final month
            (pd.Timestamp("2021-06-01"), datetime.date(2021, 6, 30)),
        ],
    )
    def test_parses(self, raw, expected):
        assert cm._parse_quarter(raw).date() == expected

    @pytest.mark.parametrize(
        "raw", ["", None, "Total", "Source: DfC", "December 2020", 42]
    )
    def test_rejects(self, raw):
        assert cm._parse_quarter(raw) is None


class TestMeasureResolution:
    @pytest.mark.parametrize(
        ("table", "label", "expected"),
        [
            ("paying_parents", "Paid some Child Maintenance (%)", ("Paid some Child Maintenance", "proportion")),
            ("paying_parents", "Paid some Child Maintenance", ("Paid some Child Maintenance", "count")),
            ("clearances", "Proportion Currently Cleared", ("Proportion Currently Cleared", "proportion")),
            ("clearances", "Cleared within 6 weeks", ("Cleared within 6 weeks", "proportion")),
            ("enforcement", "Sanctions", ("Sanctions", "amount_gbp")),
            ("maintenance", "Maintenance paid through Collect & Pay", ("Maintenance paid through Collect & Pay", "amount_gbp")),
            ("applications", "Applications Received", ("Applications Received", "count")),
        ],
    )
    def test_measure_for(self, table, label, expected):
        assert cm._measure_for(table, label) == expected


class TestCategoryCanonicalisation:
    @pytest.mark.parametrize(
        ("table", "category", "subcategory", "expected"),
        [
            ("paying_parents", "Parents using the Collect & Pay Service who", "", "Collect & Pay"),
            ("paying_parents", "Collect & Pay", "", "Collect & Pay"),
            ("paying_parents", "", "Parents due to pay through Direct Pay", "Direct Pay"),
            ("paying_parents", "", "Are due to pay Child Maintenance", "Total"),
            ("applications", "", "Applications Received", "Total"),
        ],
    )
    def test_canonical_category(self, table, category, subcategory, expected):
        assert cm._canonical_category(table, category, subcategory) == expected

    def test_case_variants_collapse_newest_first(self):
        df = pd.DataFrame(
            {
                "table": ["children_covered"] * 2,
                "category": ["Total"] * 2,
                "subcategory": ["Collect & Pay - Not Paying", "Collect & Pay - not paying"],
            }
        )
        assert set(cm._canonicalise_labels(df)["subcategory"]) == {"Collect & Pay - Not Paying"}

    def test_distinct_labels_survive(self):
        df = pd.DataFrame(
            {
                "table": ["children_covered"] * 2,
                "category": ["Total"] * 2,
                "subcategory": ["Direct Pay", "Other"],
            }
        )
        assert list(cm._canonicalise_labels(df)["subcategory"]) == ["Direct Pay", "Other"]


class TestValidation:
    @staticmethod
    def _frame(n: int = 500, **overrides) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "table": ["applications"] * n,
                "date": [pd.Timestamp("2024-03-31")] * n,
                "year": [2024] * n,
                "quarter": [1] * n,
                "category": ["Total"] * n,
                "subcategory": ["Applications Received"] * n,
                "measure": ["count"] * n,
                "value": [100.0] * n,
            }
        )
        for column, value in overrides.items():
            df[column] = value
        return df

    def test_valid_frame(self):
        assert cm.validate_data(self._frame())

    def test_empty_frame(self):
        with pytest.raises(cm.CMSValidationError, match="empty"):
            cm.validate_data(pd.DataFrame())

    def test_missing_columns(self):
        with pytest.raises(cm.CMSValidationError, match="column"):
            cm.validate_data(self._frame().drop(columns=["measure"]))

    def test_too_few_records(self):
        with pytest.raises(cm.CMSValidationError, match="records"):
            cm.validate_data(self._frame(n=10))

    def test_unknown_table(self):
        with pytest.raises(cm.CMSValidationError, match="table"):
            cm.validate_data(self._frame(table="mystery"))

    def test_unknown_measure(self):
        with pytest.raises(cm.CMSValidationError, match="measure"):
            cm.validate_data(self._frame(measure="furlongs"))

    def test_implausible_year(self):
        with pytest.raises(cm.CMSValidationError, match="Year"):
            cm.validate_data(self._frame(year=1999))

    def test_invalid_quarter(self):
        with pytest.raises(cm.CMSValidationError, match="[Qq]uarter"):
            cm.validate_data(self._frame(quarter=5))

    def test_negative_value(self):
        with pytest.raises(cm.CMSValidationError, match="[Nn]egative"):
            cm.validate_data(self._frame(value=-1.0))

    def test_proportion_above_one(self):
        with pytest.raises(cm.CMSValidationError, match="[Pp]roportion"):
            cm.validate_data(self._frame(measure="proportion", value=1.5))

    def test_min_records_configurable(self):
        assert cm.validate_data(self._frame(n=10), min_records=5)


@pytest.mark.integration
class TestCaching:
    def test_download_is_cached(self, cms_publications):
        url = _fetch(cm.find_publication_xlsx, cms_publications[0]["url"])
        first = _fetch(cm.download_file, url)
        second = _fetch(cm.download_file, url)
        assert first == second
        assert first.exists()

    def test_download_failure_raises(self):
        with pytest.raises(cm.CMSDataNotFoundError):
            cm.download_file("https://www.communities-ni.gov.uk/sites/default/files/no-such-file.xlsx")
