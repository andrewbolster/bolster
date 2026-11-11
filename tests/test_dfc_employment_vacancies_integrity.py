"""Integrity tests for DfC employment vacancies.

Tests use real data from the Department for Communities factsheets and NISRA
PxStat (no mocks). Network calls are made once per class via ``scope="class"``
fixtures. Parsing and validation edge cases are covered by network-free unit
tests that build small ODS workbooks.
"""

import pandas as pd
import pytest

from bolster.data_sources.dfc import employment_vacancies as ev

_QUARTER_STARTS = {1: 4, 2: 7, 3: 10, 4: 1}


@pytest.fixture(scope="session")
def vacancy_publications():
    """Publication list for the whole session, doubling as a reachability probe.

    The DfC site answers 503 to CI runner IPs, and the shared session's retry
    ladder makes every blocked call cost about 90 seconds. Probing once keeps a
    bad day cheap instead of timing the job out.
    """
    try:
        return ev.list_publications()
    except ev.VacanciesDataNotFoundError as e:
        pytest.skip(f"communities-ni.gov.uk unavailable: {e}")


@pytest.fixture(autouse=True)
def _require_dfc_site(request):
    if request.node.get_closest_marker("integration"):
        request.getfixturevalue("vacancy_publications")


@pytest.mark.integration
class TestPublicationDiscovery:
    """Factsheet publications are discovered from the topic page."""

    @pytest.fixture(scope="class")
    def publications(self, vacancy_publications):
        return vacancy_publications

    def test_publications_found(self, publications):
        assert len(publications) >= 10

    def test_newest_first_and_unique(self, publications):
        releases = [p["release"] for p in publications]
        assert releases == sorted(releases, reverse=True)
        assert len(releases) == len(set(releases))

    def test_releases_are_quarterly(self, publications):
        recent = [p for p in publications if p["year"] >= 2023]
        assert {p["month"] for p in recent} <= {2, 5, 8, 11}

    def test_urls_are_absolute_publication_pages(self, publications):
        for p in publications:
            assert p["url"].startswith(
                "https://www.communities-ni.gov.uk/publications/vacancies-statistical-factsheet-"
            )

    def test_factsheet_file_is_discovered_not_constructed(self, publications):
        url = ev.get_factsheet_url()
        assert url.startswith("https://www.communities-ni.gov.uk/")
        assert url.endswith(".ods")


@pytest.mark.integration
class TestQuarterly:
    """The NI quarterly series from the latest factsheet."""

    @pytest.fixture(scope="class")
    def quarterly(self, vacancy_publications):
        return ev.get_latest_data()

    @pytest.fixture(scope="class")
    def annual(self):
        return ev.get_annual_vacancies()

    def test_columns(self, quarterly):
        assert list(quarterly.columns) == ["financial_year", "quarter", "quarter_start", "vacancies"]

    def test_validates(self, quarterly):
        assert ev.validate_data(quarterly) is True

    def test_history_starts_at_2022_23(self, quarterly):
        assert len(quarterly) >= 17
        first = quarterly.iloc[0]
        assert (first["financial_year"], first["quarter"]) == ("2022/23", 1)
        assert first["quarter_start"] == pd.Timestamp("2022-04-01")

    def test_quarter_starts_match_financial_quarters(self, quarterly):
        assert (quarterly["quarter_start"].dt.month == quarterly["quarter"].map(_QUARTER_STARTS)).all()

    def test_complete_years_sum_to_annual_pxstat_total(self, quarterly, annual):
        """The factsheet and PxStat are different publications; they must agree for every complete year."""
        counts = quarterly.groupby("financial_year")["quarter"].count()
        complete = counts[counts == 4].index
        assert len(complete) >= 3
        totals = annual.set_index("financial_year")["vacancies"]
        for year in complete:
            published = quarterly.loc[quarterly["financial_year"] == year, "vacancies"].sum()
            assert published == totals[year], year

    def test_latest_release_resolves_by_month(self, vacancy_publications):
        latest = vacancy_publications[0]["release"]
        pd.testing.assert_frame_equal(ev.get_quarterly_vacancies(release=latest), ev.get_latest_data())


@pytest.mark.integration
class TestBreakdowns:
    """Each breakdown must reconcile with the quarterly series."""

    @pytest.fixture(scope="class")
    def quarterly(self, vacancy_publications):
        return ev.get_latest_data()

    @pytest.fixture(scope="class")
    def breakdowns(self, vacancy_publications):
        return {key: ev.get_vacancy_breakdown(key) for key in ev.list_breakdowns()}

    @pytest.mark.parametrize("key", ev.list_breakdowns())
    def test_validates(self, breakdowns, key):
        assert ev.validate_breakdown(breakdowns[key]) is True

    @pytest.mark.parametrize("key", ev.list_breakdowns())
    def test_categories_sum_to_the_quarterly_total(self, breakdowns, quarterly, key):
        df = breakdowns[key]
        published = quarterly.set_index(["financial_year", "quarter"])["vacancies"]
        sums = df.groupby(["financial_year", "quarter"])["vacancies"].sum()
        for index, total in sums.items():
            assert total == published[index], (key, index)

    def test_vacancy_type_categories(self, breakdowns):
        assert set(breakdowns["vacancy_type"]["category"]) == {"Casual", "Full-Time", "Part-Time"}

    def test_deprivation_has_five_quintiles_and_unknown(self, breakdowns):
        categories = set(breakdowns["nimdm"]["category"])
        assert sum(c.startswith("Quintile") for c in categories) == 5
        assert "Not known" in categories

    def test_soc_has_nine_major_groups_at_most(self, breakdowns):
        assert 8 <= breakdowns["soc"]["category"].nunique() <= 10

    def test_total_row_is_not_a_category(self, breakdowns):
        for df in breakdowns.values():
            assert "total" not in set(df["category"].str.casefold())

    def test_shares_are_fractions(self, breakdowns):
        for df in breakdowns.values():
            assert df["share"].between(0, 1).all()


@pytest.mark.integration
class TestMonthly:
    """The monthly view reconciles with the quarterly series."""

    @pytest.fixture(scope="class")
    def monthly(self, vacancy_publications):
        return ev.get_monthly_vacancies()

    @pytest.fixture(scope="class")
    def quarterly(self, vacancy_publications):
        return ev.get_latest_data()

    def test_columns(self, monthly):
        assert list(monthly.columns) == ["month", "full_time", "part_time", "casual", "total"]

    def test_total_is_sum_of_types(self, monthly):
        assert (monthly["total"] == monthly["full_time"] + monthly["part_time"] + monthly["casual"]).all()

    def test_months_are_consecutive_month_starts(self, monthly):
        assert (monthly["month"].dt.day == 1).all()
        steps = monthly["month"].diff().dropna().dt.days
        assert steps.between(28, 31).all()

    def test_complete_quarters_match_quarterly_series(self, monthly, quarterly):
        monthly = monthly.assign(quarter_start=monthly["month"].dt.to_period("Q-MAR").dt.start_time)
        # Financial quarters start in April/July/October/January; Q-MAR periods start on those months
        grouped = monthly.groupby("quarter_start").agg(total=("total", "sum"), months=("month", "count"))
        published = quarterly.set_index("quarter_start")["vacancies"]
        complete = grouped[grouped["months"] == 3]
        assert len(complete) >= 1
        for start, row in complete.iterrows():
            assert row["total"] == published[start], start


@pytest.mark.integration
class TestAnnualGeography:
    """Annual area figures from PxStat."""

    @pytest.fixture(scope="class")
    def annual(self):
        return ev.get_annual_vacancies()

    @pytest.fixture(scope="class")
    def geographies(self):
        return {key: ev.get_vacancies_by_geography(key) for key in ev.list_geographies()}

    def test_annual_history(self, annual):
        assert annual["financial_year"].iloc[0] == "2014/15"
        assert len(annual) >= 12
        assert annual["financial_year"].is_unique

    @pytest.mark.parametrize("key", ev.list_geographies())
    def test_validates_against_the_ni_total(self, geographies, annual, key):
        assert ev.validate_geography(geographies[key], annual) is True

    @pytest.mark.parametrize("key", ev.list_geographies())
    def test_ni_total_is_not_an_area(self, geographies, key):
        assert "N92000002" not in set(geographies[key]["geography_code"])

    @pytest.mark.parametrize(
        ("key", "areas"),
        [("lgd", 11), ("assembly_area", 18), ("hsct", 5), ("dea", 80)],
    )
    def test_area_counts(self, geographies, key, areas):
        assert geographies[key].groupby("financial_year")["geography_code"].nunique().eq(areas).all()

    def test_dea_starts_in_2018_19(self, geographies):
        assert geographies["dea"]["financial_year"].min() == "2018/19"

    def test_areas_fall_short_of_the_ni_total(self, geographies, annual):
        """Vacancies that cannot be placed in an area are in the NI total only."""
        totals = annual.set_index("financial_year")["vacancies"]
        sums = geographies["lgd"].groupby("financial_year")["vacancies"].sum()
        assert (sums < totals[sums.index]).all()


@pytest.mark.integration
class TestOlderReleases:
    """Older factsheets use older layouts; they parse where they can and fail clearly where they cannot."""

    def test_2023_11_breakdown_parses(self, vacancy_publications):
        df = ev.get_vacancy_breakdown("nimdm", release="2023-11")
        assert ev.validate_breakdown(df) is True
        assert df["financial_year"].iloc[0] == "2023/24"

    def test_banner_row_release_parses(self, vacancy_publications):
        """The November 2024 file carries an 'Official Sensitive' banner above its titles."""
        df = ev.get_vacancy_breakdown("vacancy_type", release="2024-11")
        assert ev.validate_breakdown(df) is True

    def test_quarterly_sheet_missing_from_old_release_is_named(self, vacancy_publications):
        with pytest.raises(ev.VacanciesDataNotFoundError, match="Quarterly"):
            ev.get_quarterly_vacancies(release="2024-02")

    def test_unrecognised_layout_raises_not_partial_data(self, vacancy_publications):
        with pytest.raises(ev.VacanciesDataError, match="not supported"):
            ev.get_vacancy_breakdown("soc", release="2022-01")

    def test_unknown_release_lists_the_available_ones(self, vacancy_publications):
        with pytest.raises(ev.VacanciesDataNotFoundError, match="Available releases"):
            ev.get_quarterly_vacancies(release="1999-01")


class TestParseQuarterLabel:
    """Quarter codes are financial-year quarters; no network."""

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Q1 2223", ("2022/23", 1, pd.Timestamp("2022-04-01"))),
            ("Q2 2223", ("2022/23", 2, pd.Timestamp("2022-07-01"))),
            ("Q3 2223", ("2022/23", 3, pd.Timestamp("2022-10-01"))),
            ("Q4 2223", ("2022/23", 4, pd.Timestamp("2023-01-01"))),
            ("Q1 9900", ("2099/00", 1, pd.Timestamp("2099-04-01"))),
            ("  Q2 2627 ", ("2026/27", 2, pd.Timestamp("2026-07-01"))),
        ],
    )
    def test_valid(self, label, expected):
        assert ev.parse_quarter_label(label) == expected

    @pytest.mark.parametrize("label", ["", "Q5 2223", "Q1 2022", "2223 Q1", "Quarter 1", "Q1 2224"])
    def test_invalid(self, label):
        with pytest.raises(ev.VacanciesDataError):
            ev.parse_quarter_label(label)


def _write_ods(path, sheets):
    with pd.ExcelWriter(path, engine="odf") as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, header=False, index=False)


@pytest.fixture
def synthetic_factsheet(tmp_path, monkeypatch):
    """Patch the factsheet download so parsers read a small hand-built workbook."""

    def install(sheets):
        path = tmp_path / "factsheet.ods"
        _write_ods(path, sheets)
        monkeypatch.setattr(
            ev, "_open_factsheet", lambda release, force_refresh: (pd.ExcelFile(path, engine="odf"), "2026-11")
        )

    return install


_TYPE_TITLE = "Employment Vacancies notified to DfC - Full-Time, Part-Time & Casual (Quarterly) 2026/27 (1), (2)"
_TYPE_HEADER = [
    "Vacancy Type",
    "Quarter 1 Vacancies Notified to DfC",
    "Quarter 1 Percentage",
    "Quarter 2 Vacancies Notified to DfC",
    "Quarter 2 Percentage",
]


def _type_rows():
    return [
        [_TYPE_TITLE],
        [],
        _TYPE_HEADER,
        ["Casual", 458, "6%", 652, "9%"],
        ["Full-Time", 4802, "64%", 4604, 0.62],
        ["Part-Time", 2243, "30%", 2210, 0.3],
        ["Total", 7503, "100%", 7466, 1.0],
        [],
        ["Notes:"],
        ["1) All statistics are derived from data extracted from the DfC JobApplyNI system."],
    ]


class TestBreakdownParsing:
    """Layout quirks, with hand-built workbooks and no network."""

    def test_counts_shares_and_dates(self, synthetic_factsheet):
        synthetic_factsheet({"FT-PT": _type_rows()})
        df = ev.get_vacancy_breakdown("vacancy_type")
        assert len(df) == 6
        row = df[(df["quarter"] == 2) & (df["category"] == "Full-Time")].iloc[0]
        assert row["vacancies"] == 4604
        assert row["financial_year"] == "2026/27"
        assert row["quarter_start"] == pd.Timestamp("2026-07-01")
        assert row["share"] == pytest.approx(4604 / 7466)

    def test_total_row_is_dropped_and_shares_sum_to_one(self, synthetic_factsheet):
        synthetic_factsheet({"FT-PT": _type_rows()})
        df = ev.get_vacancy_breakdown("vacancy_type")
        assert "Total" not in set(df["category"])
        assert ev.validate_breakdown(df) is True

    def test_published_percentages_are_ignored_whatever_their_format(self, synthetic_factsheet):
        """One table mixes '6%' strings with 0.62 fractions; shares come from the counts instead."""
        synthetic_factsheet({"FT-PT": _type_rows()})
        df = ev.get_vacancy_breakdown("vacancy_type")
        assert df["vacancies"].dtype.kind == "i"

    def test_banner_row_above_the_title(self, synthetic_factsheet):
        rows = [["Official Sensitive: prior to release at 9.30am on 06 November 2024."], *_type_rows()]
        synthetic_factsheet({"FT-PT": rows})
        df = ev.get_vacancy_breakdown("vacancy_type")
        assert df["financial_year"].iloc[0] == "2026/27"
        assert len(df) == 6

    def test_older_header_wording(self, synthetic_factsheet):
        rows = _type_rows()
        rows[2] = ["Vacancy Type", "Quarter 1-Vacancies notified", "%", "Quarter 2-Vacancies notified", "%"]
        synthetic_factsheet({"FT-PT": rows})
        assert len(ev.get_vacancy_breakdown("vacancy_type")) == 6

    def test_sheet_alias_for_jobs_and_benefits_offices(self, synthetic_factsheet):
        rows = _type_rows()
        rows[0] = ["Employment Vacancies notified to DfC - Jobs & Benefits Office (Quarterly) 2026/27"]
        rows[2][0] = "Office"
        synthetic_factsheet({"J&BO": rows})
        assert set(ev.get_vacancy_breakdown("jbo")["category"]) == {"Casual", "Full-Time", "Part-Time"}

    def test_missing_total_row_falls_back_to_the_category_sum(self, synthetic_factsheet):
        rows = [r for r in _type_rows() if not r or r[0] != "Total"]
        synthetic_factsheet({"FT-PT": rows})
        df = ev.get_vacancy_breakdown("vacancy_type")
        assert df.groupby("quarter")["share"].sum().tolist() == pytest.approx([1.0, 1.0])

    def test_unrecognised_layout_raises(self, synthetic_factsheet):
        rows = _type_rows()
        rows[2] = ["Vacancy Type", "Notified Vacancies", None, "Notified Vacancies", None]
        synthetic_factsheet({"FT-PT": rows})
        with pytest.raises(ev.VacanciesDataError, match="not supported"):
            ev.get_vacancy_breakdown("vacancy_type")

    def test_missing_count_raises(self, synthetic_factsheet):
        rows = _type_rows()
        rows[4][1] = "n/a"
        synthetic_factsheet({"FT-PT": rows})
        with pytest.raises(ev.VacanciesDataError, match="no count"):
            ev.get_vacancy_breakdown("vacancy_type")

    def test_title_without_a_financial_year_raises(self, synthetic_factsheet):
        rows = _type_rows()
        rows[0] = ["Employment Vacancies notified to DfC"]
        synthetic_factsheet({"FT-PT": rows})
        with pytest.raises(ev.VacanciesDataError, match="financial year"):
            ev.get_vacancy_breakdown("vacancy_type")

    def test_missing_sheet_names_the_alternatives(self, synthetic_factsheet):
        synthetic_factsheet({"Other": _type_rows()})
        with pytest.raises(ev.VacanciesDataNotFoundError, match="FT-PT"):
            ev.get_vacancy_breakdown("vacancy_type")

    def test_unknown_breakdown_lists_the_choices(self):
        with pytest.raises(ev.VacanciesDataError, match="vacancy_type"):
            ev.get_vacancy_breakdown("nonsense")


class TestQuarterlyAndMonthlyParsing:
    """The NI quarterly series and monthly view, with hand-built workbooks and no network."""

    def test_quarterly_rows_stop_at_the_notes(self, synthetic_factsheet):
        synthetic_factsheet(
            {
                "Quarterly": [
                    ["Quarterly Employment Vacancies notified to DfC 2022/23 to 2026/27 (1), (2)"],
                    [],
                    ["Quarter", "Vacancies Notified to DfC"],
                    ["Q1 2223", 21787],
                    ["Q2 2223", 16199],
                    [],
                    ["Notes:"],
                    ["Q9 9999 would not parse"],
                ]
            }
        )
        df = ev.get_quarterly_vacancies()
        assert df["vacancies"].tolist() == [21787, 16199]
        assert df["quarter_start"].tolist() == [pd.Timestamp("2022-04-01"), pd.Timestamp("2022-07-01")]
        assert ev.validate_data(df) is True

    def test_quarterly_bad_label_raises(self, synthetic_factsheet):
        synthetic_factsheet(
            {
                "Quarterly": [
                    ["Quarterly Employment Vacancies 2022/23"],
                    [],
                    ["Quarter", "Vacancies"],
                    ["Spring 2022", 100],
                ]
            }
        )
        with pytest.raises(ev.VacanciesDataError, match="Unrecognised quarter"):
            ev.get_quarterly_vacancies()

    def test_monthly(self, synthetic_factsheet):
        synthetic_factsheet(
            {
                "Monthly": [
                    ["Employment Vacancies notified to DfC - Monthly 2026/27 (1), (2)"],
                    [],
                    ["2026/27 Financial Year", "Full-time", "Part-time", "Casual", "Total"],
                    ["Apr 2026", 1657, 729, 73, 2459],
                    ["May 2026", "1,530", "578", 272, 2380],
                    [],
                    ["1) All statistics are derived from data extracted from the DfC JobApplyNI system."],
                ]
            }
        )
        df = ev.get_monthly_vacancies()
        assert df["month"].tolist() == [pd.Timestamp("2026-04-01"), pd.Timestamp("2026-05-01")]
        assert df["full_time"].tolist() == [1657, 1530]
        assert (df["total"] == df["full_time"] + df["part_time"] + df["casual"]).all()

    def test_monthly_missing_column_raises(self, synthetic_factsheet):
        synthetic_factsheet(
            {
                "Monthly": [
                    ["Monthly 2026/27"],
                    [],
                    ["2026/27 Financial Year", "Full-time", "Part-time", "Total"],
                    ["Apr 2026", 1, 2, 3],
                ]
            }
        )
        with pytest.raises(ev.VacanciesDataError, match="casual"):
            ev.get_monthly_vacancies()

    def test_monthly_bad_month_raises(self, synthetic_factsheet):
        synthetic_factsheet(
            {
                "Monthly": [
                    ["Monthly 2026/27"],
                    [],
                    ["2026/27 Financial Year", "Full-time", "Part-time", "Casual", "Total"],
                    ["April-ish", 1, 2, 3, 6],
                ]
            }
        )
        with pytest.raises(ev.VacanciesDataError, match="unrecognised month"):
            ev.get_monthly_vacancies()


def _matrix(label_column, code_column, rows):
    return pd.DataFrame(
        [
            {
                "STATISTIC": "EMPVAC",
                "Statistic Label": "Employment vacancies notified to DfC",
                "TLIST(A1)": year,
                "Financial Year": year,
                code_column: code,
                label_column: label,
                "UNIT": "Number",
                "VALUE": value,
            }
            for year, code, label, value in rows
        ]
    )


class TestGeographyParsing:
    """PxStat reshaping, with a hand-built matrix and no network."""

    @pytest.fixture
    def lgd(self, monkeypatch):
        df = _matrix(
            "Local Government District",
            "LGD2014",
            [
                ("2025/26", "N09000001", "Antrim and Newtownabbey", 100),
                ("2025/26", "N09000003", "Belfast", 300),
                ("2025/26", "N92000002", "Northern Ireland", 410),
                ("2024/25", "N09000001", "Antrim and Newtownabbey", 90),
                ("2024/25", "N09000003", "Belfast", 290),
                ("2024/25", "N92000002", "Northern Ireland", 385),
            ],
        )
        monkeypatch.setattr(ev, "_read_matrix", lambda matrix: df)
        return df

    def test_ni_total_row_is_removed_and_columns_renamed(self, lgd):
        out = ev.get_vacancies_by_geography("lgd")
        assert list(out.columns) == ["financial_year", "geography_code", "geography", "vacancies"]
        assert len(out) == 4
        assert "N92000002" not in set(out["geography_code"])
        assert out["financial_year"].tolist() == ["2024/25", "2024/25", "2025/26", "2025/26"]

    def test_annual_total_comes_from_the_ni_rows(self, monkeypatch):
        df = _matrix(
            "Health and Social Care Trust",
            "HSCT",
            [
                ("2025/26", "BHSCT", "Belfast", 100),
                ("2025/26", "N92000002", "Northern Ireland", 410),
                ("2024/25", "BHSCT", "Belfast", 90),
                ("2024/25", "N92000002", "Northern Ireland", 385),
            ],
        )
        monkeypatch.setattr(ev, "_read_matrix", lambda matrix: df)
        out = ev.get_annual_vacancies()
        assert out["financial_year"].tolist() == ["2024/25", "2025/26"]
        assert out["vacancies"].tolist() == [385, 410]

    def test_annual_total_without_ni_rows_raises(self, monkeypatch):
        df = _matrix("Health and Social Care Trust", "HSCT", [("2025/26", "BHSCT", "Belfast", 5)])
        monkeypatch.setattr(ev, "_read_matrix", lambda matrix: df)
        with pytest.raises(ev.VacanciesDataNotFoundError, match="Northern Ireland total"):
            ev.get_annual_vacancies()

    def test_unknown_geography_lists_the_choices(self):
        with pytest.raises(ev.VacanciesDataError, match="assembly_area"):
            ev.get_vacancies_by_geography("ward")

    def test_pxstat_failure_is_wrapped(self, monkeypatch):
        def boom(matrix):
            raise ev.PxStatError("503")

        monkeypatch.setattr(ev, "read_dataset", boom)
        with pytest.raises(ev.VacanciesDataNotFoundError, match="EMPVACLGD"):
            ev.get_vacancies_by_geography("lgd")


class TestValidation:
    """Validation edge cases; no network."""

    @staticmethod
    def _quarterly():
        return pd.DataFrame(
            {
                "financial_year": ["2022/23"] * 3,
                "quarter": [1, 2, 3],
                "quarter_start": pd.to_datetime(["2022-04-01", "2022-07-01", "2022-10-01"]),
                "vacancies": [10, 20, 30],
            }
        )

    def test_quarterly_valid(self):
        assert ev.validate_data(self._quarterly()) is True

    def test_quarterly_empty(self):
        with pytest.raises(ev.VacanciesValidationError, match="No quarterly"):
            ev.validate_data(self._quarterly().iloc[0:0])

    def test_quarterly_missing_columns(self):
        with pytest.raises(ev.VacanciesValidationError, match="Missing columns"):
            ev.validate_data(self._quarterly().drop(columns=["vacancies"]))

    def test_quarterly_non_positive(self):
        df = self._quarterly()
        df.loc[1, "vacancies"] = 0
        with pytest.raises(ev.VacanciesValidationError, match="positive"):
            ev.validate_data(df)

    def test_quarterly_duplicate(self):
        df = pd.concat([self._quarterly(), self._quarterly().iloc[[0]]], ignore_index=True)
        with pytest.raises(ev.VacanciesValidationError, match="Duplicate"):
            ev.validate_data(df)

    def test_quarterly_gap(self):
        df = self._quarterly().drop(index=1)
        with pytest.raises(ev.VacanciesValidationError, match="consecutive"):
            ev.validate_data(df)

    @staticmethod
    def _breakdown():
        return pd.DataFrame(
            {
                "breakdown": ["soc", "soc"],
                "financial_year": ["2026/27"] * 2,
                "quarter": [1, 1],
                "quarter_start": pd.to_datetime(["2026-04-01"] * 2),
                "category": ["A", "B"],
                "vacancies": [30, 70],
                "share": [0.3, 0.7],
            }
        )

    def test_breakdown_valid(self):
        assert ev.validate_breakdown(self._breakdown()) is True

    def test_breakdown_shares_not_summing(self):
        df = self._breakdown()
        df.loc[1, "share"] = 0.5
        with pytest.raises(ev.VacanciesValidationError, match="sum to 1"):
            ev.validate_breakdown(df)

    def test_breakdown_negative(self):
        df = self._breakdown()
        df.loc[0, "vacancies"] = -1
        with pytest.raises(ev.VacanciesValidationError, match="negative"):
            ev.validate_breakdown(df)

    def test_breakdown_duplicate(self):
        df = self._breakdown()
        df.loc[1, "category"] = "A"
        with pytest.raises(ev.VacanciesValidationError, match="Duplicate"):
            ev.validate_breakdown(df)

    def test_breakdown_empty_and_missing_columns(self):
        with pytest.raises(ev.VacanciesValidationError, match="No breakdown"):
            ev.validate_breakdown(self._breakdown().iloc[0:0])
        with pytest.raises(ev.VacanciesValidationError, match="Missing columns"):
            ev.validate_breakdown(self._breakdown().drop(columns=["share"]))

    @staticmethod
    def _geography(values=(60, 38)):
        return pd.DataFrame(
            {
                "financial_year": ["2025/26"] * 2,
                "geography_code": ["A", "B"],
                "geography": ["a", "b"],
                "vacancies": list(values),
            }
        )

    @staticmethod
    def _annual(total=100):
        return pd.DataFrame({"financial_year": ["2025/26"], "vacancies": [total]})

    def test_geography_valid_with_and_without_totals(self):
        assert ev.validate_geography(self._geography()) is True
        assert ev.validate_geography(self._geography(), self._annual()) is True

    def test_geography_exceeding_the_total(self):
        with pytest.raises(ev.VacanciesValidationError, match="NI total"):
            ev.validate_geography(self._geography((80, 40)), self._annual())

    def test_geography_covering_too_little(self):
        with pytest.raises(ev.VacanciesValidationError, match="NI total"):
            ev.validate_geography(self._geography((20, 20)), self._annual())

    def test_geography_year_without_a_total(self):
        annual = pd.DataFrame({"financial_year": ["2024/25"], "vacancies": [100]})
        with pytest.raises(ev.VacanciesValidationError, match="No NI total"):
            ev.validate_geography(self._geography(), annual)

    def test_geography_duplicate_negative_empty_missing(self):
        df = self._geography()
        df.loc[1, "geography_code"] = "A"
        with pytest.raises(ev.VacanciesValidationError, match="Duplicate"):
            ev.validate_geography(df)
        with pytest.raises(ev.VacanciesValidationError, match="negative"):
            ev.validate_geography(self._geography((-1, 5)))
        with pytest.raises(ev.VacanciesValidationError, match="No geography"):
            ev.validate_geography(self._geography().iloc[0:0])
        with pytest.raises(ev.VacanciesValidationError, match="Missing columns"):
            ev.validate_geography(self._geography().drop(columns=["geography"]))


class TestListings:
    """Public key lists; no network."""

    def test_breakdown_and_geography_keys(self):
        assert ev.list_breakdowns() == ["vacancy_type", "soc", "sic", "jbo", "nimdm"]
        assert ev.list_geographies() == ["lgd", "assembly_area", "hsct", "dea"]


class TestCli:
    """The ``bolster dfc vacancies`` command; no network."""

    def test_help_lists_every_dimension(self):
        from click.testing import CliRunner

        from bolster.cli import cli

        result = CliRunner().invoke(cli, ["dfc", "vacancies", "--help"])
        assert result.exit_code == 0
        for dimension in ("quarterly", "monthly", "vacancy-type", "soc", "sic", "jbo", "nimdm"):
            assert dimension in result.output
        for dimension in ("annual", "lgd", "assembly-area", "hsct", "dea"):
            assert dimension in result.output

    def test_release_with_an_annual_dimension_is_a_usage_error(self):
        from click.testing import CliRunner

        from bolster.cli import cli

        result = CliRunner().invoke(cli, ["dfc", "vacancies", "--dimension", "lgd", "--release", "2024-02"])
        assert result.exit_code == 2
        assert "factsheet dimensions only" in result.output


@pytest.mark.integration
class TestClaimantCountJoin:
    """Vacancy areas share their keys with the claimant count, so the two can be joined by code."""

    @pytest.fixture(scope="class")
    def lgd_vacancies(self):
        return ev.get_vacancies_by_geography("lgd")

    @pytest.fixture(scope="class")
    def claimants(self):
        from bolster.data_sources.nisra import claimant_count

        return {
            "lgd": claimant_count.get_latest_claimant_count("lgd"),
            "aa": claimant_count.get_latest_claimant_count("aa"),
        }

    def test_lgd_codes_and_names_match(self, lgd_vacancies, claimants):
        claimant_lgd = claimants["lgd"]
        claimant_lgd = claimant_lgd[claimant_lgd["geography_code"] != "N92000002"]
        vacancy_names = dict(zip(lgd_vacancies["geography_code"], lgd_vacancies["geography"], strict=False))
        claimant_names = dict(zip(claimant_lgd["geography_code"], claimant_lgd["geography"], strict=False))
        assert vacancy_names == claimant_names

    def test_assembly_area_codes_match(self, claimants):
        areas = ev.get_vacancies_by_geography("assembly_area")
        claimant_aa = claimants["aa"]
        assert set(areas["geography_code"]) == set(claimant_aa["geography_code"]) - {"N92000002"}

    def test_a_financial_year_of_claimants_spans_twelve_months(self, claimants):
        """The vacancy year (April to March) maps onto twelve monthly claimant counts."""
        lgd = claimants["lgd"]
        window = lgd[(lgd["date"] >= "2024-04-01") & (lgd["date"] <= "2025-03-01")]
        assert window["date"].nunique() == 12
