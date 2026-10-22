"""Offline tests for the ASHE published-tables accessors and their no-substitution contract.

NISRA publishes each ASHE release as separate files, and not every release has every file (the 2026 release
has no figure workbook). These tests build small workbooks and archives in-test, stand in for the NISRA pages
and downloads, and check that:

- files are found from scraped page links, never constructed from the year;
- a year that is not linked raises ``NISRADataNotFoundError`` naming the year and file kind;
- a request for one year never returns, or even downloads, another year's file;
- the year in the returned frames comes from the source file, and is never guessed.
"""

import io
import logging
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from bolster.data_sources.nisra import ashe
from bolster.data_sources.nisra._base import NISRADataError, NISRADataNotFoundError

HEADER = [
    "Description",
    "Code",
    "Number of jobs (thousands) [note 3]",
    "Median",
    "Annual percentage change: Median",
    "Mean",
    "Annual percentage change: Mean",
    "10th percentile",
    "90th percentile",
]
MEASURE_NAMES = {1: "Weekly pay - Gross", 5: "Hourly pay - Gross", 7: "Annual pay - Gross"}


def _sheet(title: str, rows: list[list], cv: bool = False) -> pd.DataFrame:
    """A sheet laid out like NISRA's: title row, seven note rows, 'Description' header row, then data."""
    width = len(HEADER)
    lines = [[title] + [None] * (width - 1)]
    lines += [["Notes about this worksheet"] + [None] * (width - 1) for _ in range(7)]
    lines.append(HEADER)
    lines += rows
    return pd.DataFrame(lines)


def _write_xlsx(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    return path


def _ods_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="odf") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    return buffer.getvalue()


HEADLINE_GROUPS = [
    "All",
    "Male",
    "Female",
    "Full-time",
    "Part-time",
    "Male Full-time",
    "Male Part-time",
    "Female Full-time",
    "Female Part-time",
]


def _headline_rows(base: float) -> list[list]:
    rows = []
    for i, group in enumerate(HEADLINE_GROUPS):
        # The last group's 90th percentile is suppressed, as NISRA does for unreliable cells
        p90 = "[u]" if i == len(HEADLINE_GROUPS) - 1 else base * 2 + i
        rows.append([group, "[z]", 100 + i, base + i, 5.5, base * 1.1 + i, 6.0, base / 3, p90])
    return rows


def _headline_workbook(
    path: Path, year: int, measures: tuple[int, ...] = (1,), title_years: dict[str, int] | None = None
) -> Path:
    """A headline results workbook with an estimates and a CV sheet for each of ``measures``."""
    title_years = title_years or {}
    sheets = {}
    for number in measures:
        a_name, b_name = f"Table 1.{number}a Measure", f"Table 1.{number}b Measure CV"
        a_year = title_years.get(a_name, year)
        b_year = title_years.get(b_name, year)
        sheets[a_name] = _sheet(
            f"Table 1 (NI).{number}a   Pay (£) - For all employee jobs: Northern Ireland, {a_year} [note 1]",
            _headline_rows(500.0),
        )
        sheets[b_name] = _sheet(
            f"Table 1 (NI).{number}b   Coefficients of variation for Pay: Northern Ireland, {b_year}",
            _headline_rows(2.0),
        )
    return _write_xlsx(path, sheets)


LGDS = [
    ("N09000001", "Antrim and Newtownabbey", 600.0),
    ("N09000003", "Belfast", 700.0),
    ("N09000011", "Ards and North Down", 520.0),
]


def _lgd_ods(year: int, table_number: int = 7) -> bytes:
    sheets = {}
    for group in ("All", "Male_Full-Time"):
        rows = [["All employees", "[z]", 1000, 625.0, 5.8, 700.0, 5.9, 200.0, 1200.0]]
        rows += [
            [name, code, 50 + i, median + i, 3.0, median + 80, 4.0, 180.0, 1100.0]
            for i, (code, name, median) in enumerate(LGDS)
        ]
        sheets[f"Table{table_number}_1a_{group}"] = _sheet(
            f"Table {table_number} (NI).1a   Weekly pay - Gross (£): Northern Ireland, {year}", rows
        )
        cv_rows = [["All employees", "[z]", 1.0, 1.0, "[x]", 1.0, "[x]", 3.0, 3.0]] + [
            [name, code, 2.0, 2.5, "[x]", 2.2, "[x]", 4.0, 4.0] for code, name, _ in LGDS
        ]
        sheets[f"Table{table_number}_1b_{group}_CV"] = _sheet(
            f"Table {table_number} (NI).1b   CVs: Northern Ireland, {year}", cv_rows
        )
    return _ods_bytes(sheets)


def _sector_ods(year: int) -> bytes:
    names = [
        "All employees",
        "Public sector",
        "Private sector",
        "Non-profit body or mutual association",
        "Not classified",
    ]
    rows = [
        [n, "[z]", 100 + i, 600.0 + 10 * i, 5.0, 700.0 + 10 * i, 5.0, 200.0, 1200.0] for i, n in enumerate(names[:-1])
    ]
    rows.append([names[-1], "[z]", "[z]", "[x]", "[x]", "[x]", "[x]", "[x]", "[x]"])
    cv_rows = [[r[0], "[z]", 2.0, 2.0, "[x]", 2.0, "[x]", 3.0, 3.0] for r in rows]
    return _ods_bytes(
        {
            "Table13_1a_All": _sheet(f"Table 13 (NI).1a   Weekly pay - Gross: Northern Ireland, {year}", rows),
            "Table13_1b_All_CV": _sheet(f"Table 13 (NI).1b   CVs: Northern Ireland, {year}", cv_rows),
        }
    )


def _zip_with(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


@pytest.fixture
def nisra(monkeypatch, tmp_path):
    """Stand-ins for NISRA's pages and downloads. Records every URL downloaded.

    Usage: ``pages[page_url] = [url, ...]`` to link files, ``files[url] = path`` to serve them.
    """

    class Site:
        def __init__(self):
            self.pages: dict[str, list[str]] = {}
            self.files: dict[str, Path] = {}
            self.downloaded: list[str] = []
            self.latest_year = 2026

    site = Site()

    def fake_scrape(page_url, file_extension=".xlsx", base_url=None, force_refresh=False):
        if page_url not in site.pages:
            raise RuntimeError(f"404 for {page_url}")
        return [{"url": u, "text": u.rsplit("/", 1)[-1]} for u in site.pages[page_url] if file_extension in u.lower()]

    def fake_download(url, cache_ttl_hours=24, force_refresh=False):
        site.downloaded.append(url)
        return site.files[url]

    monkeypatch.setattr(ashe, "scrape_file_links", fake_scrape)
    monkeypatch.setattr(ashe, "download_file", fake_download)
    monkeypatch.setattr(ashe, "get_latest_ashe_publication_url", lambda: ("https://example/latest", site.latest_year))
    site.tmp_path = tmp_path
    return site


class TestDiscovery:
    def test_file_url_comes_from_the_scraped_page(self, nisra):
        page = ashe.ASHE_PUBLICATION_PAGE.format(year=2025)
        nisra.pages[page] = [
            "https://example/odd/place/ASHE-2025-linked.xlsx",
            "https://example/ASHE-1997-2025-headline-timeseries.xlsx",
        ]
        assert ashe.get_ashe_file_url(2025, "linked") == "https://example/odd/place/ASHE-2025-linked.xlsx"
        assert ashe.get_ashe_file_url(2025, "timeseries") == "https://example/ASHE-1997-2025-headline-timeseries.xlsx"

    def test_unlinked_figure_workbook_names_year_and_kind_and_advises_year(self, nisra):
        nisra.pages[ashe.ASHE_PUBLICATION_PAGE.format(year=2026)] = [
            "https://example/ASHE-1997-2026-headline-timeseries.xlsx"
        ]
        with pytest.raises(NISRADataNotFoundError) as excinfo:
            ashe.get_ashe_file_url(2026, "linked")
        message = str(excinfo.value)
        assert "2026" in message
        assert "figure ('linked') workbook" in message
        assert "year=2025" in message
        assert "no other year is substituted" in message

    def test_missing_publication_page_is_a_not_found_error(self, nisra):
        with pytest.raises(NISRADataNotFoundError, match="Could not read"):
            ashe.get_ashe_file_url(2031, "linked")

    def test_unknown_file_type(self, nisra):
        with pytest.raises(ValueError, match="Unknown file_type"):
            ashe.get_ashe_file_url(2025, "nope")


class TestNoSubstitution:
    """A request for one year must never return, or download, another year's file."""

    def test_default_figure_workbook_accessor_raises_for_unpublished_latest_year(self, nisra):
        nisra.pages[ashe.ASHE_PUBLICATION_PAGE.format(year=2026)] = []
        nisra.pages[ashe.ASHE_PUBLICATION_PAGE.format(year=2025)] = ["https://example/ASHE-2025-linked.xlsx"]
        nisra.files["https://example/ASHE-2025-linked.xlsx"] = nisra.tmp_path / "unused.xlsx"

        for accessor in (
            ashe.get_gender_pay_gap,
            ashe.get_real_earnings,
            ashe.get_latest_ashe_geography,
            ashe.get_latest_ashe_sector,
        ):
            with pytest.raises(NISRADataNotFoundError, match="2026"):
                accessor()
        assert nisra.downloaded == []

    def test_headline_for_unlinked_year_never_downloads_other_year(self, nisra):
        page = ashe.ASHE_HEADLINE_PAGE
        nisra.pages[page] = [
            "https://example/ASHE-2025-headline-results.xlsx",
            "https://example/ASHE-2024-headline-results.xlsx",
        ]
        nisra.files["https://example/ASHE-2025-headline-results.xlsx"] = _headline_workbook(
            nisra.tmp_path / "h25.xlsx", 2025
        )

        with pytest.raises(NISRADataNotFoundError, match=r"2026.*headline results workbook"):
            ashe.get_ashe_headline_results(year=2026)
        with pytest.raises(NISRADataNotFoundError, match=r"years linked there: 2025, 2024"):
            ashe.get_ashe_headline_results()  # latest release year is 2026 and is not linked
        assert nisra.downloaded == []

    @pytest.mark.parametrize("accessor", [ashe.get_ashe_lgd_earnings, ashe.get_ashe_sector_earnings])
    def test_ods_for_unlinked_year_never_downloads_other_year(self, nisra, accessor):
        nisra.pages[ashe.ASHE_ODS_PAGE] = ["https://example/ODS-format-ASHE-tables-2025.zip"]
        with pytest.raises(NISRADataNotFoundError, match=r"2026.*ODS tables archive"):
            accessor(year=2026)
        with pytest.raises(NISRADataNotFoundError):
            accessor()
        assert nisra.downloaded == []

    def test_explicit_year_gets_exactly_that_year(self, nisra):
        nisra.pages[ashe.ASHE_ODS_PAGE] = [
            "https://example/ODS-format-ASHE-tables-2026.zip",
            "https://example/ODS-format-ASHE-tables-2025.zip",
        ]
        nisra.files["https://example/ODS-format-ASHE-tables-2025.zip"] = _zip_with(
            nisra.tmp_path / "t25.zip",
            {"NI Table 7 Work LGD14/Work LGD14 Table 7 (NI).1   Weekly pay - Gross 2025.ods": _lgd_ods(2025)},
        )
        nisra.files["https://example/ODS-format-ASHE-tables-2026.zip"] = _zip_with(
            nisra.tmp_path / "t26.zip",
            {"NI Table 7 Work LGD14/Work LGD14 Table 7 (NI).1   Weekly pay - Gross 2026.ods": _lgd_ods(2026)},
        )
        assert set(ashe.get_ashe_lgd_earnings(year=2025)["year"]) == {2025}
        assert set(ashe.get_ashe_lgd_earnings(year=2026)["year"]) == {2026}
        assert set(ashe.get_ashe_lgd_earnings()["year"]) == {2026}  # latest release year
        assert nisra.downloaded == [
            "https://example/ODS-format-ASHE-tables-2025.zip",
            "https://example/ODS-format-ASHE-tables-2026.zip",
            "https://example/ODS-format-ASHE-tables-2026.zip",
        ]

    def test_archive_whose_files_are_titled_another_year_is_rejected(self, nisra):
        nisra.pages[ashe.ASHE_ODS_PAGE] = ["https://example/ODS-format-ASHE-tables-2026.zip"]
        nisra.files["https://example/ODS-format-ASHE-tables-2026.zip"] = _zip_with(
            nisra.tmp_path / "mislabelled.zip",
            {"Work LGD14 Table 7 (NI).1   Weekly pay - Gross 2026.ods": _lgd_ods(2025)},
        )
        with pytest.raises(NISRADataError, match="Expected ASHE 2026"):
            ashe.get_ashe_lgd_earnings(year=2026)


class TestHeadlineParsing:
    def test_tidy_frame_with_source_year_and_cv(self, nisra):
        path = _headline_workbook(nisra.tmp_path / "h.xlsx", 2026)
        df = ashe.parse_ashe_headline_results(path, measure="weekly_pay_gross")

        assert set(df["year"]) == {2026}
        assert len(df) == 9
        assert set(df["sex"]) == {"All", "Male", "Female"}
        assert set(df["work_pattern"]) == {"All", "Full-time", "Part-time"}
        row = df[(df["sex"] == "Female") & (df["work_pattern"] == "Part-time")].iloc[0]
        assert row["median"] == 508.0 and row["jobs_thousands"] == 108
        assert row["median_cv"] == 10.0 and row["mean_cv"] == pytest.approx(2.2 + 8)
        assert pd.isna(row["p90"])  # '[u]' suppression is NaN, not a number

    def test_year_is_read_from_the_titles_not_the_file_name(self, nisra):
        df = ashe.parse_ashe_headline_results(
            _headline_workbook(nisra.tmp_path / "ASHE-2099-headline-results.xlsx", 2024), measure="weekly_pay_gross"
        )
        assert set(df["year"]) == {2024}

    def test_expected_year_mismatch_raises(self, nisra):
        path = _headline_workbook(nisra.tmp_path / "h.xlsx", 2025)
        with pytest.raises(NISRADataError, match="Expected ASHE 2026"):
            ashe.parse_ashe_headline_results(path, year=2026, measure="weekly_pay_gross")

    def test_stray_title_year_is_logged_not_trusted(self, nisra, caplog):
        # NISRA's 2023 workbook titles Table 1.7a (and 1.8a) "2021"
        path = _headline_workbook(
            nisra.tmp_path / "h.xlsx", 2023, measures=(1, 7), title_years={"Table 1.7a Measure": 2021}
        )
        with caplog.at_level(logging.WARNING):
            df = ashe.parse_ashe_headline_results(path, year=2023, measure="annual_pay_gross")
        assert set(df["year"]) == {2023}
        assert "Table 1.7" in caplog.text

    def test_table_not_carrying_the_expected_year_raises(self, nisra):
        path = _headline_workbook(
            nisra.tmp_path / "h.xlsx", 2023, title_years={"Table 1.1a Measure": 2021, "Table 1.1b Measure CV": 2021}
        )
        with pytest.raises(NISRADataError, match="Expected ASHE 2023"):
            ashe.parse_ashe_headline_results(path, year=2023, measure="weekly_pay_gross")

    def test_all_eleven_measures(self, nisra):
        path = _headline_workbook(nisra.tmp_path / "h.xlsx", 2026, measures=tuple(range(1, 12)))
        df = ashe.parse_ashe_headline_results(path)
        assert set(df["measure"]) == set(ashe.ASHE_MEASURES)
        assert len(df) == 99

    def test_missing_measure_table_raises(self, nisra):
        path = _headline_workbook(nisra.tmp_path / "h.xlsx", 2026)
        with pytest.raises(NISRADataNotFoundError, match=r"Table 1\.5"):
            ashe.parse_ashe_headline_results(path, measure="hourly_pay_gross")

    def test_unknown_measure(self, nisra):
        with pytest.raises(ValueError, match="Unknown measure"):
            ashe.parse_ashe_headline_results(nisra.tmp_path / "x.xlsx", measure="nope")

    def test_accessor_reads_the_scraped_workbook(self, nisra):
        nisra.pages[ashe.ASHE_HEADLINE_PAGE] = ["https://example/files/ASHE-2026-headline-results.xlsx"]
        nisra.files["https://example/files/ASHE-2026-headline-results.xlsx"] = _headline_workbook(
            nisra.tmp_path / "h.xlsx", 2026
        )
        df = ashe.get_ashe_headline_results(measure="weekly_pay_gross")
        assert set(df["year"]) == {2026}
        assert nisra.downloaded == ["https://example/files/ASHE-2026-headline-results.xlsx"]

    def test_year_before_supported_layouts(self, nisra):
        with pytest.raises(ValueError, match="only supported from 2021"):
            ashe.get_ashe_headline_results(year=2020)

    def test_unrecognised_group_raises(self):
        with pytest.raises(NISRADataError, match="Unrecognised"):
            ashe._split_group("Everyone else")

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Male_Full-Time", ("Male", "Full-time")),
            ("Female Part-time", ("Female", "Part-time")),
            ("Full-Time", ("All", "Full-time")),
            ("Male", ("Male", "All")),
        ],
    )
    def test_split_group(self, text, expected):
        assert ashe._split_group(text) == expected


class TestOdsTableParsing:
    def test_lgd_one_row_per_district_group_and_total_dropped(self):
        book = pd.ExcelFile(io.BytesIO(_lgd_ods(2026)), engine="odf")
        df = ashe.parse_ashe_lgd_table(book, "workplace", "weekly_pay_gross", year=2026)

        assert set(df["year"]) == {2026}
        assert len(df) == 6  # 3 LGDs x 2 groups, no 'All employees' row
        assert set(df["basis"]) == {"workplace"}
        assert set(df["lgd"]) == {name for _, name, _ in LGDS}
        assert (df["lgd_code"].str.startswith("N09")).all()
        belfast = df[(df["lgd"] == "Belfast") & (df["sex"] == "Male") & (df["work_pattern"] == "Full-time")].iloc[0]
        assert belfast["median"] == 701.0 and belfast["mean"] == 780.0 and belfast["median_cv"] == 2.5

    def test_residence_table_number(self):
        book = pd.ExcelFile(io.BytesIO(_lgd_ods(2026, table_number=8)), engine="odf")
        df = ashe.parse_ashe_lgd_table(book, "residence", "weekly_pay_gross", year=2026)
        assert set(df["basis"]) == {"residence"} and len(df) == 6

    def test_sector_labels_and_placeholder_dropped(self):
        book = pd.ExcelFile(io.BytesIO(_sector_ods(2026)), engine="odf")
        df = ashe.parse_ashe_sector_table(book, "weekly_pay_gross", year=2026)
        assert set(df["sector"]) == {"All", "Public", "Private", "Non-profit"}
        assert "Not classified" not in set(df["sector"])
        assert set(df["year"]) == {2026}
        assert df.loc[df["sector"] == "Public", "median"].iloc[0] == 610.0

    def test_unrecognised_sector_raises(self):
        rows = [["Mystery sector", "[z]", 1, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]]
        book = pd.ExcelFile(
            io.BytesIO(
                _ods_bytes(
                    {
                        "Table13_1a_All": _sheet("Table 13 (NI).1a   Pay: Northern Ireland, 2026", rows),
                        "Table13_1b_All_CV": _sheet("Table 13 (NI).1b   CVs: Northern Ireland, 2026", rows),
                    }
                )
            ),
            engine="odf",
        )
        with pytest.raises(NISRADataError, match="Unrecognised ASHE sector"):
            ashe.parse_ashe_sector_table(book, "weekly_pay_gross")

    def test_estimates_sheet_without_cv_sheet_raises(self):
        book = pd.ExcelFile(
            io.BytesIO(_ods_bytes({"Table7_1a_All": _sheet("Table 7 (NI).1a   Pay: Northern Ireland, 2026", [])})),
            engine="odf",
        )
        with pytest.raises(NISRADataNotFoundError, match="no CV sheet"):
            ashe.parse_ashe_ods_table(book, 7)

    def test_workbook_without_the_table_raises(self):
        book = pd.ExcelFile(io.BytesIO(_sector_ods(2026)), engine="odf")
        with pytest.raises(NISRADataNotFoundError, match="no Table7"):
            ashe.parse_ashe_ods_table(book, 7)

    def test_archive_without_member_raises(self, nisra):
        nisra.pages[ashe.ASHE_ODS_PAGE] = ["https://example/ODS-format-ASHE-tables-2026.zip"]
        nisra.files["https://example/ODS-format-ASHE-tables-2026.zip"] = _zip_with(
            nisra.tmp_path / "t.zip", {"readme.txt": b"x"}
        )
        with pytest.raises(NISRADataNotFoundError, match="has no Table 7"):
            ashe.get_ashe_lgd_earnings(year=2026)

    def test_bad_arguments(self, nisra):
        with pytest.raises(ValueError, match="Unknown basis"):
            ashe.get_ashe_lgd_earnings(year=2026, basis="elsewhere")
        with pytest.raises(ValueError, match="Unknown measure"):
            ashe.get_ashe_sector_earnings(year=2026, measure="nope")
        with pytest.raises(ValueError, match="only supported from 2022"):
            ashe.get_ashe_sector_earnings(year=2021)

    def test_title_without_a_year_raises(self):
        with pytest.raises(NISRADataError, match="No year found"):
            ashe._title_year("Table 7 (NI).1a   Weekly pay")

    def test_ambiguous_year_without_expectation_raises(self):
        with pytest.raises(NISRADataError, match="cannot tell"):
            ashe._workbook_year({"Table 1.1": [2021, 2023]}, None, "workbook")


class TestLinkedGeographyYear:
    """parse_ashe_geography never guesses a year from the clock."""

    @staticmethod
    def _map_workbook(path: Path, subtitle: str) -> Path:
        frame = pd.DataFrame(
            [
                ["Map A: headline"],
                [subtitle],
                ["Local Government District", "Median"],
                ["Belfast", 766.6],
                ["Mid Ulster", 672.8],
            ]
        )
        return _write_xlsx(path, {"MapA": frame})

    def test_year_comes_from_the_sheet_title(self, tmp_path):
        path = self._map_workbook(
            tmp_path / "anything.xlsx", "Median gross weekly earnings for full-time employees, April 2025"
        )
        df = ashe.parse_ashe_geography(path)
        assert set(df["year"]) == {2025}
        assert set(df["work_pattern"]) == {"Full-time"}
        assert list(df["lgd"]) == ["Belfast", "Mid Ulster"]

    def test_title_without_a_year_raises_instead_of_using_the_current_year(self, tmp_path):
        path = self._map_workbook(
            tmp_path / "ASHE-2025-linked.xlsx", "Median gross weekly earnings for full-time employees"
        )
        with pytest.raises(NISRADataError, match="No year found"):
            ashe.parse_ashe_geography(path)

    def test_expected_year_mismatch_raises(self, tmp_path):
        path = self._map_workbook(tmp_path / "x.xlsx", "Median gross weekly earnings, April 2025")
        with pytest.raises(NISRADataError, match="titled 2025"):
            ashe.parse_ashe_geography(path, year=2026)
