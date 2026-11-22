"""Offline unit tests for the shared BSO Family Practitioner Services readers.

These build small workbooks shaped like the published ones (a cover sheet, a
single-table sheet whose title row ends in a "Scroll left" hint, a sheet of
stacked sub-tables, a notes sheet) so they need no network.
"""

import datetime

import pandas as pd
import pytest

from bolster.data_sources.health_ni import _base, _fps, gms
from bolster.data_sources.health_ni._base import NISRADataNotFoundError, NISRAValidationError

SCROLL = "<<Scroll left for previous years data"


def _write_workbook(path, sheets: dict[str, list[list[str]]]):
    """Write ``{sheet name: rows}`` to an xlsx, padding rows to the sheet's full width like the real files."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            width = max(len(r) for r in rows)
            padded = [list(r) + [""] * (width - len(r)) for r in rows]
            pd.DataFrame(padded).to_excel(writer, sheet_name=name, header=False, index=False)


def _trust_sheet(
    title: str = "Table 2.2: Sight Tests by Local Commissioning Group (Health Trust) and Financial Quarter [note 1]",
):
    return [
        [title, "", "", SCROLL],
        ["This worksheet contains one table with references to notes which can be found in the notes worksheet."],
        ["Sources: FPS Ophthalmic Payment System"],
        ["Local Commissioning Group (Health Trust)", "Quarter 1 2025/26", "Quarter 2 2025/26", "Quarter 4 2025/26"],
        ["Belfast", "100", "110", "120"],
        ["Northern", "200", "210", "220"],
        ["Unknown", "10", "20", "[d]"],
        ["Northern Ireland", "310", "340", "340"],
        [],
        ["To Table of Contents"],
    ]


def _age_sex_sheet():
    header = ["Age Group", "Quarter 1 2025/26", "Quarter 2 2025/26"]
    return [
        ["Table 2.1: Number of Sight Tests by Gender, Age Group and Financial Quarter [note 1]", "", SCROLL],
        ["This worksheet contains four tables arranged vertically with one blank row between each table."],
        ["Table 2.1a: Male Sight Tests by Age Group and Financial Quarter [note 1]"],
        header,
        ["0-5", "1", "2"],
        ["Total", "1", "2"],
        [],
        ["Table 2.1b: Female Sight Tests by Age Group and Financial Quarter [note 1]"],
        header,
        ["0-5", "3", "4"],
        ["Total", "3", "4"],
        [],
        ["Table 2.1c: Unknown/Missing Gender Sight Tests by Age Group and Financial Quarter"],
        header,
        ["0-5", "0", "1"],
        ["Total", "0", "1"],
        [],
        ["Table 2.1d: All Persons Sight Tests by Age Group and Financial Quarter"],
        header,
        ["0-5", "4", "7"],
        ["Total", "4", "7"],
    ]


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "fps.xlsx"
    _write_workbook(
        path,
        {
            "Cover sheet": [
                ["General Ophthalmic Services for Northern Ireland"],
                ["Quarterly Series to Q2 2025/26 - Provisional"],
            ],
            "Table of contents": [["Table of contents"], ["Table number", "Table title"], ["2.1", "Sight Tests"]],
            "2.1": _age_sex_sheet(),
            "2.2": _trust_sheet(),
            "Notes": [["Notes table"], ["Note number", "Note text"], ["1", "A note"]],
            "User Guidance": [["User Guidance", "Links"], ["Some guidance", "https://example.org"]],
        },
    )
    return pd.ExcelFile(path, engine="openpyxl")


@pytest.fixture
def frame(workbook):
    return _fps.parse_quarterly_workbook(workbook)


class TestQuarterLabels:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Quarter 1 2025/26", ("2025/26", 1, datetime.date(2025, 6, 30))),
            ("Quarter 2 2025/26", ("2025/26", 2, datetime.date(2025, 9, 30))),
            ("Quarter 3 2025/26", ("2025/26", 3, datetime.date(2025, 12, 31))),
            ("Quarter 4 2025/26", ("2025/26", 4, datetime.date(2026, 3, 31))),
            ("Quarter 4 2099/00", ("2099/00", 4, datetime.date(2100, 3, 31))),
            ("Quarter 1 2017/18 [note 3]", ("2017/18", 1, datetime.date(2017, 6, 30))),
        ],
    )
    def test_parses_quarters(self, label, expected):
        assert _fps.parse_quarter_label(label) == expected

    @pytest.mark.parametrize("label", ["Age Group", "Quarter 5 2025/26", "2025/26 Q1", "Quarter 1 2025", ""])
    def test_rejects_other_headings(self, label):
        assert _fps.parse_quarter_label(label) is None


class TestTitles:
    def test_core_title_drops_prefix_and_notes(self):
        title = (
            "Table 2.2: Sight Tests by Local Commissioning Group (Health Trust) and Financial Quarter [note 1] [note 6]"
        )
        assert _fps.core_title(title) == "Sight Tests by Local Commissioning Group (Health Trust) and Financial Quarter"

    @pytest.mark.parametrize(
        ("title", "level"),
        [
            ("Number of Sight Tests by Gender, Age Group and Financial Quarter", "age_sex"),
            ("Sight Tests by Local Commissioning Group (Health Trust) and Financial Quarter", "trust"),
            ("Fillings by Local Commissioning Group and Financial Quarter", "trust"),
            ("Sight Tests by Local Government District and Financial Quarter", "lgd"),
            ("Patient Registrations by Assembly Area and Financial Quarter", "assembly_area"),
            ("Number Of Ophthalmic Medical Practitioners & Optometrists by Financial Quarter", None),
            ("Monthly Breakdown of Claims by Payment Month", None),
        ],
    )
    def test_table_level(self, title, level):
        assert _fps.table_level(title) == level

    @pytest.mark.parametrize(
        ("title", "sex"),
        [
            ("Male Sight Tests by Age Group and Financial Quarter", "Male"),
            ("Female Sight Tests by Age Group and Financial Quarter", "Female"),
            ("Unknown/Missing Gender Sight Tests by Age Group and Financial Quarter", "Unknown"),
            ("All Persons Sight Tests by Age Group and Financial Quarter", "All"),
            ("Fillings for Males by Age Group and Financial Quarter", "Male"),
            ("Fillings for Females by Age Group and Financial Quarter", "Female"),
            ("Fillings for Unknown/Missing Gender by Age Group and Financial Quarter", "Unknown"),
            ("Fillings for All Persons by Age Group and Financial Quarter", "All"),
        ],
    )
    def test_sex_from_title(self, title, sex):
        assert _fps._sex_from_table_title(title) == sex

    def test_new_category_is_not_relabelled(self):
        assert (
            _fps._sex_from_table_title("Non-binary Sight Tests by Age Group") == "Non-binary Sight Tests by Age Group"
        )


class TestSheetRows:
    def test_scroll_hint_is_stripped_only_on_request(self, workbook):
        kept = _base.excel_sheet_rows(workbook, "2.2")
        stripped = _base.excel_sheet_rows(workbook, "2.2", strip_scroll_hint=True)
        assert any(cell.startswith("<<") for cell in kept[0])
        assert len(stripped[0]) == 1
        assert stripped[0][0].startswith("Table 2.2:")

    def test_single_table_sheet_is_invisible_without_the_strip(self, workbook):
        """The defect the strip fixes: a one-table sheet yielded no tables at all."""
        with pytest.raises(NISRADataNotFoundError):
            _base.parse_stacked_tables(_base.excel_sheet_rows(workbook, "2.2"))
        assert not _base.parse_stacked_tables(_base.excel_sheet_rows(workbook, "2.2", strip_scroll_hint=True)).empty


class TestParseQuarterlyWorkbook:
    def test_reads_single_and_stacked_sheets(self, frame):
        assert set(frame.sheet) == {"2.1", "2.2"}
        assert len(frame[frame.sheet == "2.2"]) == 4 * 3
        assert frame[frame.sheet == "2.1"].table_id.nunique() == 4

    def test_quarter_columns_become_periods(self, frame):
        trust = frame[frame.sheet == "2.2"]
        assert sorted(trust.period.dropna().unique()) == [
            pd.Timestamp("2025-06-30"),
            pd.Timestamp("2025-09-30"),
            pd.Timestamp("2026-03-31"),
        ]
        assert set(trust.financial_year) == {"2025/26"}
        assert sorted(trust.quarter.unique()) == [1, 2, 4]

    def test_suppressed_cell_is_missing_not_zero(self, frame):
        unknown = frame[(frame.sheet == "2.2") & (frame.row_label == "Unknown")].set_index("quarter").value
        assert pd.isna(unknown[4])
        assert unknown[1] == 10

    def test_cover_marks_series_provisional(self, workbook, frame):
        assert _fps.is_provisional(workbook) is True
        assert frame.provisional.all()

    def test_unmarked_cover_is_not_provisional(self, tmp_path):
        path = tmp_path / "final.xlsx"
        _write_workbook(
            path,
            {
                "Cover sheet": [["General Ophthalmic Services"], ["Quarterly Series to Q2 2025/26"]],
                "2.2": _trust_sheet(),
            },
        )
        assert _fps.is_provisional(pd.ExcelFile(path, engine="openpyxl")) is False

    def test_workbook_without_tables_raises(self, tmp_path):
        path = tmp_path / "empty.xlsx"
        _write_workbook(path, {"Cover sheet": [["Cover"]], "Notes": [["Notes table"], ["1", "A note"]]})
        with pytest.raises(NISRADataNotFoundError, match="No data tables"):
            _fps.parse_quarterly_workbook(pd.ExcelFile(path, engine="openpyxl"))


class TestQuarterlySeries:
    def test_trust_series_is_tidy(self, frame):
        out = _fps.quarterly_series(frame, title_pattern=r"(?:Number of )?Sight Tests\b", level="trust")
        assert list(out.columns) == ["period", "financial_year", "quarter", "trust", "value", "is_total", "provisional"]
        assert out.is_total.sum() == 3
        assert set(out[out.is_total].trust) == {"Northern Ireland"}
        assert out.period.is_monotonic_increasing

    def test_found_by_title_not_number(self, tmp_path):
        """Table numbers drift between editions: renumbering a sheet must not lose the table."""
        path = tmp_path / "renumbered.xlsx"
        _write_workbook(
            path,
            {
                "Cover sheet": [["Cover"]],
                "13.7": _trust_sheet(
                    "Table 13.7: Sight Tests by Local Commissioning Group (Health Trust) and Financial Quarter"
                ),
            },
        )
        df = _fps.parse_quarterly_workbook(pd.ExcelFile(path, engine="openpyxl"))
        out = _fps.quarterly_series(df, title_pattern=r"Sight Tests\b", level="trust")
        assert len(out) == 12

    def test_no_match_names_pattern_and_level(self, frame):
        with pytest.raises(NISRADataNotFoundError, match=r"Vouchers.*'trust'"):
            _fps.quarterly_series(frame, title_pattern=r"Vouchers\b", level="trust")

    def test_wrong_level_is_not_substituted(self, frame):
        with pytest.raises(NISRADataNotFoundError):
            _fps.quarterly_series(frame, title_pattern=r"(?:Number of )?Sight Tests\b", level="lgd")

    def test_age_sex_series_has_sex_and_age_group(self, frame):
        out = _fps.quarterly_series(frame, title_pattern=r"(?:Number of )?Sight Tests\b", level="age_sex")
        assert {"sex", "age_group"} <= set(out.columns)
        assert set(out.sex) == {"Male", "Female", "Unknown", "All"}
        everyone = out[(out.sex == "All") & (out.age_group == "Total")].sort_values("period")
        assert everyone.value.tolist() == [4, 7]
        assert everyone.is_total.all()

    def test_areas_plus_unknown_equal_total(self, frame):
        out = _fps.quarterly_series(frame, title_pattern=r"(?:Number of )?Sight Tests\b", level="trust")
        first = out[out.quarter == 1]
        assert first[first.is_total].value.sum() == first[~first.is_total].value.sum()


class TestUnallocated:
    def _annual(self):
        return pd.DataFrame(
            {
                "financial_year": ["2025/26"] * 4,
                "measure": ["Sight Tests"] * 4,
                "trust": ["Belfast", "Northern", "Southern", "Northern Ireland"],
                "value": [100.0, 200.0, 50.0, 360.0],
                "is_total": [False, False, False, True],
            }
        )

    def test_gap_between_total_and_areas(self):
        out = _fps.unallocated(self._annual(), level="trust", by=["financial_year", "measure"])
        assert out.loc[0, "total"] == 360
        assert out.loc[0, "area_sum"] == 350
        assert out.loc[0, "unallocated"] == 10

    def test_requires_a_total_row(self):
        with pytest.raises(NISRAValidationError, match="No Northern Ireland total"):
            _fps.unallocated(self._annual().query("not is_total"), level="trust", by=["measure"])


class TestValidateSeries:
    def test_accepts_good_frame(self):
        assert (
            _fps.validate_series(pd.DataFrame({"period": [pd.Timestamp("2026-03-31")], "value": [1.0]}), label="X")
            is True
        )

    def test_empty_raises(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            _fps.validate_series(pd.DataFrame(columns=["period", "value"]), label="X")

    def test_missing_column_raises(self):
        with pytest.raises(NISRAValidationError, match="missing columns"):
            _fps.validate_series(pd.DataFrame({"value": [1.0]}), label="X")

    def test_negative_raises(self):
        with pytest.raises(NISRAValidationError, match="negative"):
            _fps.validate_series(pd.DataFrame({"period": [pd.Timestamp("2026-03-31")], "value": [-1.0]}), label="X")


class TestAnnualCube:
    def test_unknown_level_raises_before_any_request(self, monkeypatch):
        monkeypatch.setattr(_fps, "read_dataset", lambda code: pytest.fail("must not fetch"))
        with pytest.raises(ValueError, match="Unknown geography level"):
            _fps.read_annual_cube("FPSGOSOT", "region")

    def test_unexpected_columns_raise(self, monkeypatch):
        monkeypatch.setattr(_fps, "read_dataset", lambda code: pd.DataFrame({"VALUE": [1]}))
        with pytest.raises(NISRAValidationError, match="expected columns"):
            _fps.read_annual_cube("FPSGOSOT", "trust")

    def test_tidies_a_cube(self, monkeypatch):
        raw = pd.DataFrame(
            {
                "STATISTIC": ["S", "S"],
                "Statistic Label": ["Sight Tests", "Sight Tests"],
                "TLIST(A1)": ["2025/26", "2025/26"],
                "Financial Year": ["2025/26", "2025/26"],
                "HSCT": ["BHSCT", "N92000002"],
                "Health and Social Care Trust": ["Belfast", "Northern Ireland"],
                "UNIT": ["Number", "Number"],
                "VALUE": [10, 25],
            }
        )
        seen = {}
        monkeypatch.setattr(_fps, "read_dataset", lambda code: seen.setdefault("code", code) and raw)
        out = _fps.read_annual_cube("FPSGOSOT", "trust")
        assert seen["code"] == "FPSGOSOTHSCT"
        assert out.period.tolist() == [pd.Timestamp("2026-03-31")] * 2
        assert out.is_total.tolist() == [False, True]
        assert out.trust.tolist() == ["Belfast", "Northern Ireland"]
        assert out.value.tolist() == [10, 25]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestDiscovery:
    def test_no_matching_publication_names_the_series(self, monkeypatch):
        monkeypatch.setattr(_base.session, "get", lambda *a, **k: _Response({"results": [{"link": "/other/thing"}]}))
        with pytest.raises(NISRADataNotFoundError, match="No Widget publications found matching prefix"):
            _base.find_latest_govuk_publication("widgets", "/government/statistics/widgets", label="Widget")

    def test_newest_matching_publication_is_fetched(self, monkeypatch):
        fetched = []

        def fake_get(url, **kwargs):
            fetched.append(url)
            if url == _base.GOVUK_SEARCH_API_URL:
                return _Response(
                    {
                        "results": [
                            {"link": "/government/statistics/x-1", "public_timestamp": "2026-01-01T00:00:00Z"},
                            {"link": "/government/statistics/x-2", "public_timestamp": "2026-06-01T00:00:00Z"},
                            {"link": "/unrelated", "public_timestamp": "2027-01-01T00:00:00Z"},
                        ]
                    }
                )
            return _Response({"details": {"attachments": []}})

        monkeypatch.setattr(_base.session, "get", fake_get)
        _base.find_latest_govuk_publication("x", "/government/statistics/x", label="X")
        assert fetched[-1].endswith("/government/statistics/x-2")

    def test_attachment_is_chosen_by_title_keywords(self):
        content = {
            "details": {
                "attachments": [
                    {"title": "Report page", "url": "https://datavis.example/report.html"},
                    {
                        "title": "General Ophthalmic Services Tables, Quarter 2",
                        "url": "https://assets.example/media/x/tables.xlsx",
                    },
                ]
            }
        }
        assert _base.find_govuk_xlsx_attachment(content, ("tables",)) == "https://assets.example/media/x/tables.xlsx"

    def test_missing_attachment_raises(self):
        with pytest.raises(NISRADataNotFoundError, match="No .xlsx attachment matching"):
            _base.find_govuk_xlsx_attachment({"details": {"attachments": []}}, ("Tables",))

    def test_gms_keeps_its_own_error_message(self, monkeypatch):
        monkeypatch.setattr(_base.session, "get", lambda *a, **k: _Response({"results": []}))
        with pytest.raises(NISRADataNotFoundError, match="No GMS publications"):
            gms._find_latest_publication("general medical services", "/government/statistics/does-not-exist")
