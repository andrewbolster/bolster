"""Tests for the DfC gambling licensing and industry data module.

The first half needs no network: parsers run on hand-built tables and workbooks laid out the way
each release lays them out. The second half runs against the live DfC publication pages and
workbooks for every release.
"""

import io

import pandas as pd
import pytest

from bolster.data_sources.dfc import gambling_licensing as g

# ---------------------------------------------------------------------------
# Offline: labels, titles, years and numbers
# ---------------------------------------------------------------------------


class TestPermitTier:
    @pytest.mark.parametrize(
        ("label", "tier"),
        [
            ("Amusement permit £500 [Note 1]", "£500"),
            ("Amusement permit £25 [Note 1]", "£25"),
            ("Amusement permit £8 [Note 1]", "£8"),
            ("Amusement permit £252", "£25"),
            ("Amusement permit £251", "£25"),
            ("Amusement permit £82", "£8"),
            ("Amusement permit £81", "£8"),
        ],
    )
    def test_known_tiers(self, label, tier):
        assert g.parse_permit_tier(label) == tier

    @pytest.mark.parametrize("label", ["Amusement permit £9", "Amusement permit £2512", "Amusement permit"])
    def test_unknown_tier_raises(self, label):
        with pytest.raises(g.GamblingValidationError):
            g.parse_permit_tier(label)


class TestMeasure:
    @pytest.mark.parametrize(
        ("label", "category", "measure"),
        [
            ("Number of bingo club licences operational [Note 1]", "bingo_clubs", "operational"),
            ("Number of bingo club renewals4", "bingo_clubs", "renewed"),
            ("Number of bingo clubs registered3", "bingo_clubs", "registered"),
            ("Number of bingo club registrations cancelled7 ", "bingo_clubs", "cancelled"),
            ("Number of bookmaking office licences transferred [Note 4]", "bookmaking_offices", "transferred"),
            ("Number of society lottery registrations refused", "society_lotteries", "refused"),
            ("Number of existing society lotteries renewed", "society_lotteries", "renewed"),
            ("Number of new society lotteries granted", "society_lotteries", "granted"),
            ("Number of disqualification orders made", "gaming_machine_certificates", "disqualification_orders"),
            (
                "Number of disqualification orders made in consequence of: the revocation of any licence",
                "bookmakers",
                "disqualification_orders_revocation",
            ),
            (
                "Number of disqualification orders made in consequence of: the conviction of a licensed bookmaker "
                "for an offence",
                "bookmakers",
                "disqualification_orders_conviction",
            ),
            ("Number of existing amusement permits3", "amusement_permits", "existing_permits"),
            ("Number of gaming machines of each type [Notes 3 and 8]", "amusement_permits", "gaming_machines"),
            ("Number of new amusement permits granted4", "amusement_permits", "new_permits_granted"),
            ("Number of permits cancelled or revoked5", "amusement_permits", "cancelled_or_revoked"),
            ("Number of permits granted for a pleasure fair6", "amusement_permits", "pleasure_fair_permits_granted"),
        ],
    )
    def test_known_labels(self, label, category, measure):
        assert g.parse_measure(label, category) == measure

    def test_unknown_label_raises_naming_it(self):
        with pytest.raises(g.GamblingValidationError, match="Number of widgets"):
            g.parse_measure("Number of widgets", "bingo_clubs")

    def test_unknown_amusement_label_raises(self):
        with pytest.raises(g.GamblingValidationError, match="Number of widgets"):
            g.parse_measure("Number of widgets", "amusement_permits")


class TestTitlesYearsAndNumbers:
    @pytest.mark.parametrize(
        ("raw", "key"),
        [
            ("Table 1: Number of amusement permits and gaming machines1", "amusement_permits"),
            ("Table 5 Number of lottery certificates1", "lottery_certificates"),
            ("Table 4: Number of society lotteries [Note 6]", "society_lotteries"),
            ("Table 7: Number of bookmakers' licences", "bookmakers"),
            ("Table 7: Number of bookmakers’ licences", "bookmakers"),
            ("Table 4: Number of bookmaker licences1", "bookmakers"),
            ("Table 6: Number of bookmaking offices", "bookmaking_offices"),
            ("Table 9: Number of people employed in gambling and betting activities1,", "employment"),
            (
                "Table 10: Business turnover for land-based gambling and betting operators [Notes 1, 2 and 3]",
                "turnover",
            ),
            ("Table 11: Betting and gaming duty [Notes 1, 2 and 3]", "duty"),
            ("Table 8: Number of registered gambling businesses", "registered_businesses"),
        ],
    )
    def test_title_identifies_table(self, raw, key):
        assert g._table_key(g._normalise_title(raw)) == key

    def test_unrelated_title_matches_nothing(self):
        assert g._table_key(g._normalise_title("Table 12: Number of widgets")) is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (2025, 2025),
            (2025.0, 2025),
            ("2025", 2025),
            (" 2024 ", 2024),
            ("2025.5", None),
            ("20255", None),
            (None, None),
        ],
    )
    def test_as_year(self, value, expected):
        assert g._as_year(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2013", ("2013", 2013)),
            (2013, ("2013", 2013)),
            ("2000-2001", ("2000-01", 2000)),
            ("1999-2000", ("1999-00", 1999)),
            ("2024-25", ("2024-25", 2024)),
        ],
    )
    def test_parse_period(self, value, expected):
        assert g._parse_period(value, "x") == expected

    @pytest.mark.parametrize("value", ["2024-26", "2024/25", "Total", ""])
    def test_bad_period_raises(self, value):
        with pytest.raises(g.GamblingValidationError):
            g._parse_period(value, "x")

    def test_number_accepts_numbers_and_numeric_text(self):
        assert g._number(3, "x") == 3.0
        assert g._number("1,234", "x") == 1234.0

    @pytest.mark.parametrize("value", ["n/a", "[c]", None, float("nan"), True])
    def test_number_rejects_everything_else(self, value):
        with pytest.raises(g.GamblingValidationError):
            g._number(value, "table")


# ---------------------------------------------------------------------------
# Offline: table parsers on hand-built sheets
# ---------------------------------------------------------------------------


def _sheet(rows):
    width = max(len(row) for row in rows)
    return pd.DataFrame([list(row) + [None] * (width - len(row)) for row in rows], dtype=object)


class TestYearAcrossParser:
    def _bingo(self):
        return _sheet(
            [
                ["Table 5: Number of bingo clubs"],
                ["(back to contents)"],
                ["Bingo Clubs", "2025", "2024"],
                ["Number of bingo club licences operational [Note 1]", 37, 36],
                ["Number of bingo club renewals3", 27, 21],
                ["Source: Northern Ireland Courts and Tribunals Service (NICTS)"],
                ["1. Number of bingo club licences that are currently operational."],
            ]
        )

    def test_rows_per_measure_and_year(self):
        rows = g._parse_year_across(self._bingo(), "Table 5", "bingo_clubs", 2025)
        frame = pd.DataFrame(rows)
        assert len(frame) == 4
        assert set(frame["measure"]) == {"operational", "renewed"}
        assert frame.loc[(frame.measure == "renewed") & (frame.year == 2024), "value"].item() == 21

    def test_stops_at_source_row(self):
        rows = g._parse_year_across(self._bingo(), "Table 5", "bingo_clubs", 2025)
        assert all("Source" not in str(row["measure"]) for row in rows)

    def test_non_numeric_cell_raises_naming_the_cell(self):
        sheet = self._bingo()
        sheet.iat[3, 1] = "[c]"
        with pytest.raises(g.GamblingValidationError, match="Table 5"):
            g._parse_year_across(sheet, "Table 5", "bingo_clubs", 2025)

    def test_blank_year_cell_raises(self):
        sheet = self._bingo()
        sheet.iat[4, 2] = None
        with pytest.raises(g.GamblingValidationError, match="Missing value"):
            g._parse_year_across(sheet, "Table 5", "bingo_clubs", 2025)

    def test_no_year_header_raises(self):
        sheet = _sheet([["Table 5: Number of bingo clubs"], ["(back to contents)"], ["Bingo Clubs", "Total"]])
        with pytest.raises(g.GamblingValidationError, match="No year header"):
            g._parse_year_across(sheet, "Table 5", "bingo_clubs", 2025)


class TestAmusementPermitsParser:
    def _horizontal(self):
        # 2022 to 2024 layout: tiers side by side, the tier label above the first or middle column of its block
        return _sheet(
            [
                ["Table 1: Number of amusement permits and gaming machines1"],
                ["(back to contents)"],
                [None, "2023", "2022", "2023", "2022"],
                [None, None, "Amusement permit £251", None, "Amusement permit £81"],
                ["Number of existing amusement permits2", 108, 111, 23, 16],
                ["Number of gaming machines of each type3", 6457, 5901, 885, 377],
                ["Source: Local Government District Councils"],
                ["1. Two types of amusement permit can be granted."],
            ]
        )

    def _vertical(self):
        # 2025 layout: tiers stacked, each with its own years and a blank row between
        return _sheet(
            [
                ["Table 1: Number of amusement permits and gaming machines"],
                ["(back to contents)"],
                ["This sheet contains three tables vertically separated by a blank row"],
                ["Amusement permit £500 [Note 1]", "2025"],
                ["Number of existing amusement permits [Note 2]", 106],
                ["Number of gaming machines of each type [Notes 3 and 8]", 6493],
                [None],
                ["Amusement permit £25 [Note 1]", "2024", "2023"],
                ["Number of existing amusement permits [Note 2]", 109, 108],
                ["Number of gaming machines of each type [Notes 3 and 4]", 6410, 6457],
                [None],
                ["Amusement permit £8 [Note 1]", "2025", "2024"],
                ["Number of existing amusement permits [Note 2]", 11, 23],
                ["Number of gaming machines of each type [Notes 3 and 4]", 499, 549],
                [None],
                ["Source: Local Councils"],
            ]
        )

    def test_horizontal_layout(self):
        frame = pd.DataFrame(g._parse_amusement_permits(self._horizontal(), "Table 1", 2023))
        assert set(frame["permit_tier"]) == {"£25", "£8"}
        assert len(frame) == 8
        cell = frame[(frame.permit_tier == "£8") & (frame.year == 2022) & (frame.measure == "gaming_machines")]
        assert cell["value"].item() == 377

    def test_vertical_layout(self):
        frame = pd.DataFrame(g._parse_amusement_permits(self._vertical(), "Table 1", 2025))
        assert set(frame["permit_tier"]) == {"£500", "£25", "£8"}
        assert sorted(frame[frame.permit_tier == "£500"]["year"].unique()) == [2025]
        assert sorted(frame[frame.permit_tier == "£25"]["year"].unique()) == [2023, 2024]
        assert frame[(frame.permit_tier == "£500") & (frame.measure == "gaming_machines")]["value"].item() == 6493

    def test_tier_and_block_counts_must_match(self):
        sheet = self._horizontal()
        sheet.iat[3, 4] = None
        sheet.iat[3, 3] = None
        with pytest.raises(g.GamblingValidationError, match="permit tier labels"):
            g._parse_amusement_permits(sheet, "Table 1", 2023)

    def test_unknown_tier_raises(self):
        sheet = self._vertical()
        sheet.iat[3, 0] = "Amusement permit £9 [Note 1]"
        with pytest.raises(g.GamblingValidationError, match="tier"):
            g._parse_amusement_permits(sheet, "Table 1", 2025)


class TestIndustryParser:
    def _employment(self):
        return _sheet(
            [
                ["Table 9: Number of people employed in gambling and betting activities [Note 1]"],
                ["(back to contents)"],
                ["Year", "Full-time", "Part-time", "Total"],
                ["2022", 1255, 986, 2241],
                ["2024", 1188, 859, 2047],
                ["Source: Business Register and Employment Survey (BRES), NISRA"],
            ]
        )

    def test_employment_has_three_series(self):
        frame = pd.DataFrame(g._parse_industry(self._employment(), "Table 9", "employment", 2025))
        assert set(frame["series"]) == {"employment_full_time", "employment_part_time", "employment_total"}
        assert set(frame["unit"]) == {"people"}
        assert len(frame) == 6

    def test_duty_periods_are_normalised(self):
        sheet = _sheet(
            [
                ["Table 11: Betting and gaming duty [Notes 1, 2 and 3]"],
                ["(back to contents)"],
                ["Financial Year", "Turnover (£m)"],
                ["1999-2000", 36],
                ["2000-01", 37],
                ["Source: ONS"],
            ]
        )
        frame = pd.DataFrame(g._parse_industry(sheet, "Table 11", "duty", 2025))
        assert list(frame["period"]) == ["1999-00", "2000-01"]
        assert list(frame["year"]) == [1999, 2000]
        assert set(frame["series"]) == {"betting_and_gaming_duty"}

    def test_missing_employment_column_raises(self):
        sheet = self._employment()
        sheet.iat[2, 3] = "Everyone"
        with pytest.raises(g.GamblingValidationError, match="full-time, part-time and total"):
            g._parse_industry(sheet, "Table 9", "employment", 2025)

    def test_missing_header_raises(self):
        sheet = _sheet([["Table 10: Business turnover"], ["(back to contents)"], ["Turnover", "£m"]])
        with pytest.raises(g.GamblingValidationError, match="No 'Year' header"):
            g._parse_industry(sheet, "Table 10", "turnover", 2025)


# ---------------------------------------------------------------------------
# Offline: reading a whole workbook (fake workbooks, no network)
# ---------------------------------------------------------------------------


def _year_table(title, labels, years=(2022, 2021)):
    rows = [[title], ["(back to contents)"], [None, *map(str, years)]]
    rows += [[label, *([5] * len(years))] for label in labels]
    rows += [["Source: test"]]
    return rows


def _fake_tables(release):
    tables = {
        "Table 1": [
            ["Table 1: Number of amusement permits and gaming machines"],
            ["(back to contents)"],
            [None, "2022", "2021", "2022", "2021"],
            [None, "Amusement permit £252", None, "Amusement permit £82", None],
            ["Number of existing amusement permits3", 1, 2, 3, 4],
            ["Source: test"],
        ],
        "Table 2": _year_table("Table 2: Number of bingo clubs", ["Number of bingo club licences operational2"]),
        "Table 3": _year_table(
            "Table 3: Number of bookmaking offices", ["Number of bookmaking office licences operational2"]
        ),
        "Table 4": _year_table("Table 4: Number of bookmaker licences1", ["Number of bookmaker licences operational2"]),
        "Table 5": _year_table(
            "Table 5 Number of lottery certificates1", ["Number of lottery certificates operational"]
        ),
        "Table 6": [
            ["Table 6: Number of registered gambling businesses"],
            ["(back to contents)"],
            ["Year", "No.2"],
            ["2013", 95],
            ["2014", 90],
        ],
        "Table 7": [
            ["Table 7: Number of people employed in gambling and betting activities"],
            ["(back to contents)"],
            ["Year", "Full-time", "Part-time", "Total"],
            ["2009", 10, 5, 15],
        ],
        "Table 8": [
            ["Table 8: Business turnover for land-based gambling and betting operators"],
            ["(back to contents)"],
            ["Year", "Turnover (£m)"],
            ["2015", 743.2],
        ],
        "Table 9": [
            ["Table 9: Betting and gaming duty 1, 2"],
            ["(back to contents)"],
            ["Year", "Betting and gaming duty (£m)"],
            ["1999-2000", 36],
        ],
    }
    if release >= 2023:
        tables["Table 10"] = _year_table(
            "Table 10: Number of gaming machine certificates", ["Number of gaming machine certificates operational1"]
        )
        tables["Table 11"] = _year_table(
            "Table 11: Number of society lotteries", ["Number of existing society lotteries renewed1"], years=(2023,)
        )
    return tables


def _workbook(tables):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([["Contents"]]).to_excel(writer, sheet_name="Contents", header=False, index=False)
        for name, rows in tables.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, header=False, index=False)
    buffer.seek(0)
    return pd.ExcelFile(buffer)


@pytest.fixture
def fake_release(monkeypatch):
    """Serve fake workbooks from ``load_workbook`` and a fixed address from ``_workbook_url``."""

    def install(tables):
        monkeypatch.setattr(g, "_workbook_url", lambda release, force_refresh=False: "https://example.test/tables.xlsx")
        monkeypatch.setattr(g, "load_workbook", lambda url, download_file, **kwargs: _workbook(tables))

    return install


class TestReadRelease:
    def test_reads_every_table_of_a_2022_style_workbook(self, fake_release):
        fake_release(_fake_tables(2022))
        licences, industry = g._read_release(2022)
        assert g.validate_licences(licences)
        assert g.validate_industry(industry)
        assert set(licences["category"]) == {
            "amusement_permits",
            "bingo_clubs",
            "bookmaking_offices",
            "bookmakers",
            "lottery_certificates",
        }
        assert set(industry["series"]) >= {"registered_businesses", "employment_total", "betting_and_gaming_duty"}

    def test_society_lotteries_and_certificates_are_required_from_2023(self, fake_release):
        tables = _fake_tables(2023)
        fake_release(tables)
        licences, _ = g._read_release(2023)
        assert {"society_lotteries", "gaming_machine_certificates"} <= set(licences["category"])

        del tables["Table 11"]
        with pytest.raises(g.GamblingDataNotFoundError, match="society_lotteries"):
            g._read_release(2023)

    def test_missing_required_table_raises_naming_it(self, fake_release):
        tables = _fake_tables(2022)
        del tables["Table 9"]
        fake_release(tables)
        with pytest.raises(g.GamblingDataNotFoundError, match="duty"):
            g._read_release(2022)

    def test_unrecognised_table_raises_instead_of_being_skipped(self, fake_release):
        tables = _fake_tables(2022)
        tables["Table 12"] = [["Table 12: Number of widgets"], ["(back to contents)"], ["Year", "No."], ["2020", 1]]
        fake_release(tables)
        with pytest.raises(g.GamblingValidationError, match="Unrecognised table 'Table 12'"):
            g._read_release(2022)

    def test_two_tables_for_one_series_raise(self, fake_release):
        tables = _fake_tables(2022)
        tables["Table 12"] = _year_table(
            "Table 12: Number of bingo clubs", ["Number of bingo club licences operational"]
        )
        fake_release(tables)
        with pytest.raises(g.GamblingValidationError, match="two tables"):
            g._read_release(2022)


# ---------------------------------------------------------------------------
# Offline: validators
# ---------------------------------------------------------------------------


def _licence_frame(**overrides):
    row = {
        "release": 2025,
        "year": 2025,
        "category": "bingo_clubs",
        "permit_tier": pd.NA,
        "measure": "operational",
        "value": 37,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _industry_frame(rows):
    return pd.DataFrame(
        [
            {
                "release": 2025,
                "period": period,
                "year": int(period[:4]),
                "series": series,
                "unit": "people",
                "value": value,
            }
            for period, series, value in rows
        ]
    )


class TestValidators:
    def test_valid_licences_pass(self):
        assert g.validate_licences(_licence_frame())

    def test_empty_licences_raise(self):
        with pytest.raises(g.GamblingValidationError, match="empty"):
            g.validate_licences(_licence_frame().iloc[0:0])

    def test_missing_licence_column_raises(self):
        with pytest.raises(g.GamblingValidationError, match="missing columns"):
            g.validate_licences(_licence_frame().drop(columns="measure"))

    @pytest.mark.parametrize("value", [-1, 1.5])
    def test_bad_counts_raise(self, value):
        with pytest.raises(g.GamblingValidationError, match="whole numbers"):
            g.validate_licences(_licence_frame(value=value))

    def test_unknown_category_raises(self):
        with pytest.raises(g.GamblingValidationError, match="Unknown categories"):
            g.validate_licences(_licence_frame(category="casinos"))

    def test_tier_only_on_amusement_permits(self):
        with pytest.raises(g.GamblingValidationError, match="permit tier"):
            g.validate_licences(_licence_frame(permit_tier="£8"))
        with pytest.raises(g.GamblingValidationError, match="permit tier"):
            g.validate_licences(_licence_frame(category="amusement_permits", measure="existing_permits"))

    def test_duplicate_rows_raise(self):
        with pytest.raises(g.GamblingValidationError, match="repeated"):
            g.validate_licences(pd.concat([_licence_frame(), _licence_frame()], ignore_index=True))

    def test_valid_industry_passes(self):
        rows = [
            ("2024", "employment_full_time", 10.0),
            ("2024", "employment_part_time", 5.0),
            ("2024", "employment_total", 15.0),
        ]
        assert g.validate_industry(_industry_frame(rows))

    def test_employment_total_must_add_up(self):
        rows = [
            ("2024", "employment_full_time", 10.0),
            ("2024", "employment_part_time", 5.0),
            ("2024", "employment_total", 99.0),
        ]
        with pytest.raises(g.GamblingValidationError, match="full-time plus part-time"):
            g.validate_industry(_industry_frame(rows))

    def test_negative_industry_value_raises(self):
        with pytest.raises(g.GamblingValidationError, match="non-negative"):
            g.validate_industry(_industry_frame([("2024", "registered_businesses", -5.0)]))

    def test_unknown_series_raises(self):
        with pytest.raises(g.GamblingValidationError, match="Unknown series"):
            g.validate_industry(_industry_frame([("2024", "casino_revenue", 5.0)]))

    def test_repeated_series_period_raises(self):
        rows = [("2024", "registered_businesses", 80.0), ("2024", "registered_businesses", 85.0)]
        with pytest.raises(g.GamblingValidationError, match="Repeated"):
            g.validate_industry(_industry_frame(rows))

    def test_empty_and_missing_industry_raise(self):
        with pytest.raises(g.GamblingValidationError, match="empty"):
            g.validate_industry(_industry_frame([("2024", "registered_businesses", 80.0)]).iloc[0:0])
        with pytest.raises(g.GamblingValidationError, match="missing columns"):
            g.validate_industry(_industry_frame([("2024", "registered_businesses", 80.0)]).drop(columns="unit"))


# ---------------------------------------------------------------------------
# Live: every release from the DfC publication pages
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def all_releases():
    return g.list_releases()


@pytest.fixture(scope="class")
def stacked():
    data = g.get_all_releases()
    licences = data["licences"].assign(permit_tier=data["licences"]["permit_tier"].astype("object").fillna("-"))
    return licences, data["industry"]


class TestReleases:
    def test_releases_run_without_gaps_from_the_first(self, all_releases):
        assert all_releases[0] == g.FIRST_RELEASE
        assert all_releases == list(range(g.FIRST_RELEASE, all_releases[-1] + 1))
        assert all_releases[-1] >= 2025

    def test_a_release_without_a_page_raises_naming_the_year(self):
        with pytest.raises(g.GamblingDataNotFoundError, match="2021"):
            g.get_licences(2021)
        with pytest.raises(g.GamblingDataNotFoundError, match="2099"):
            g.get_industry(2099)

    def test_latest_data_returns_both_frames_for_the_newest_release(self, all_releases):
        data = g.get_latest_data()
        assert set(data) == {"licences", "industry"}
        assert set(data["licences"]["release"]) == {all_releases[-1]}
        assert set(data["industry"]["release"]) == {all_releases[-1]}

    def test_every_release_parses_and_validates(self, all_releases):
        for release in all_releases:
            assert g.validate_licences(g.get_licences(release))
            assert g.validate_industry(g.get_industry(release))


class TestLatestLicences:
    @pytest.fixture(scope="class")
    def licences(self):
        return g.get_licences()

    def test_columns_and_dtypes(self, licences):
        assert list(licences.columns) == ["release", "year", "category", "permit_tier", "measure", "value"]
        assert str(licences["value"].dtype) == "Int64"

    def test_every_category_present(self, licences):
        assert set(licences["category"]) == set(g.list_categories())

    def test_five_years_except_society_lotteries(self, licences):
        years = licences.groupby("category")["year"].agg(lambda s: sorted(set(s)))
        latest = int(licences["release"].max())
        for category, seen in years.items():
            expected = (
                [latest - 2, latest - 1, latest]
                if category == "society_lotteries"
                else list(range(latest - 4, latest + 1))
            )
            assert seen == expected, category

    def test_permit_tiers_change_in_2025(self, licences):
        tiers = (
            licences[licences.category == "amusement_permits"]
            .groupby("permit_tier")["year"]
            .agg(lambda s: sorted(set(s)))
        )
        assert tiers["£500"] == [2025]
        assert tiers["£25"] == [2021, 2022, 2023, 2024]
        assert tiers["£8"] == [2021, 2022, 2023, 2024, 2025]

    def test_published_values_for_2025(self, licences):
        def cell(category, measure, year, tier=None):
            frame = licences[(licences.category == category) & (licences.measure == measure) & (licences.year == year)]
            if tier is not None:
                frame = frame[frame.permit_tier == tier]
            return int(frame["value"].item())

        assert cell("amusement_permits", "existing_permits", 2025, "£500") == 106
        assert cell("amusement_permits", "gaming_machines", 2025, "£500") == 6493
        assert cell("amusement_permits", "gaming_machines", 2024, "£25") == 6410
        assert cell("bookmaking_offices", "operational", 2025) == 276
        assert cell("bookmaking_offices", "operational", 2022) == 279
        assert cell("bookmakers", "operational", 2025) == 103
        assert cell("bingo_clubs", "operational", 2025) == 37
        assert cell("society_lotteries", "granted", 2025) == 53

    def test_renewals_do_not_exceed_operational_licences(self, licences):
        wide = licences.pivot_table(index=["category", "year"], columns="measure", values="value", aggfunc="first")
        for category in ("bookmaking_offices", "bookmakers", "gaming_machine_certificates", "lottery_certificates"):
            sub = wide.xs(category, level="category")
            assert (sub["renewed"] <= sub["operational"]).all(), category

    def test_grants_do_not_exceed_operational_licences(self, licences):
        wide = licences.pivot_table(index=["category", "year"], columns="measure", values="value", aggfunc="first")
        for category in (
            "bookmaking_offices",
            "bookmakers",
            "gaming_machine_certificates",
            "lottery_certificates",
            "bingo_clubs",
        ):
            sub = wide.xs(category, level="category")
            assert (sub["granted"] <= sub["operational"]).all(), category


class TestLatestIndustry:
    @pytest.fixture(scope="class")
    def industry(self):
        return g.get_industry()

    def test_every_series_present(self, industry):
        assert set(industry["series"]) == set(g.list_series())

    def test_series_start_years(self, industry):
        first = industry.groupby("series")["year"].min()
        assert first["betting_and_gaming_duty"] == 1999
        assert first["employment_total"] == 2009
        assert first["registered_businesses"] == 2013
        assert first["land_based_turnover"] == 2015

    def test_duty_is_a_run_of_consecutive_financial_years(self, industry):
        duty = industry[industry.series == "betting_and_gaming_duty"].sort_values("year")
        assert duty["period"].iloc[0] == "1999-00"
        assert duty["year"].diff().dropna().eq(1).all()
        assert duty["period"].str.fullmatch(r"\d{4}-\d{2}").all()

    def test_employment_total_is_full_time_plus_part_time(self, industry):
        wide = industry[industry.series.str.startswith("employment_")].pivot_table(
            index="year", columns="series", values="value"
        )
        assert (wide["employment_full_time"] + wide["employment_part_time"] - wide["employment_total"]).abs().max() <= 1

    def test_registered_businesses_are_rounded_to_five(self, industry):
        businesses = industry[industry.series == "registered_businesses"]["value"]
        assert (businesses % 5 == 0).all()

    def test_turnover_has_the_covid_fall(self, industry):
        turnover = industry[industry.series == "land_based_turnover"].set_index("year")["value"]
        assert turnover[2017] > 700
        assert turnover[2023] < 0.3 * turnover[2017]


class TestAcrossReleases:
    def test_licence_counts_are_never_revised(self, stacked):
        licences, _ = stacked
        wide = licences.pivot_table(
            index=["category", "permit_tier", "measure", "year"], columns="release", values="value", aggfunc="first"
        )
        overlapping = wide.dropna(thresh=2)
        assert len(overlapping) > 100
        assert (overlapping.nunique(axis=1) == 1).all()

    def test_industry_revisions_are_confined_to_known_series(self, stacked):
        _, industry = stacked
        wide = industry.pivot_table(index=["series", "period"], columns="release", values="value", aggfunc="first")
        overlapping = wide.dropna(thresh=2)
        revised = overlapping[overlapping.nunique(axis=1) > 1]
        assert set(revised.index.get_level_values("series")) <= {
            "betting_and_gaming_duty",
            "employment_total",
            "land_based_turnover",
            "registered_businesses",
        }

    def test_total_employment_revisions_are_within_one(self, stacked):
        _, industry = stacked
        wide = industry[industry.series == "employment_total"].pivot_table(
            index="period", columns="release", values="value", aggfunc="first"
        )
        assert (wide.max(axis=1) - wide.min(axis=1)).max() <= 1

    def test_the_2022_turnover_revision_is_visible(self, stacked):
        _, industry = stacked
        turnover = industry[(industry.series == "land_based_turnover") & (industry.year == 2022)].set_index("release")[
            "value"
        ]
        assert turnover[2024] == pytest.approx(228.1)
        assert turnover[2025] == pytest.approx(185.8)

    def test_no_period_is_dropped_between_releases(self, stacked):
        _, industry = stacked
        periods = {
            (release, series): set(frame["period"])
            for (release, series), frame in industry.groupby(["release", "series"])
        }
        for (release, series), seen in periods.items():
            later = periods.get((release + 1, series))
            if later is not None:
                assert seen <= later, (release, series, sorted(seen - later))

    def test_all_releases_frames_validate(self, stacked):
        licences, industry = stacked
        assert g.validate_licences(licences.assign(permit_tier=licences["permit_tier"].replace("-", pd.NA)))
        assert g.validate_industry(industry)
