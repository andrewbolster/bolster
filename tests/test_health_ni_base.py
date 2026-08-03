"""Unit tests for the shared health_ni CSV parsing helpers.

These run entirely in-process: the DoH accessible-CSV layout is reproduced
from fixtures so the quirks it encodes (stacked sub-tables, suppression
markers, footnote refs, cross-tab label columns) are pinned without network.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni._base import (
    NISRADataNotFoundError,
    parse_csv_tables,
    parse_period_column,
    parse_value,
    strip_note_refs,
)

SINGLE_LABEL_CSV = """Some preamble that should be ignored
"Table 1: HSC Workforce (WTE), 31 March 2025 to 31 March 2026"
Staff Group,2025,2026,% Change 2025 to 2026
Administration & Clerical [note 1],"12,373.8","12,500.0",1.0%
Medical & Dental,4815.9,[c],-2.5%

Table 2A - HSC Workforce by Organisation
Organisation,2025,2026
Belfast HSC Trust,"19,063.1","19,200.0"
,,
"""

TWO_LABEL_CSV = """Table 6: HSC Vacancies by Profession & Pay Band
Staff Group,Profession,Band 5,Total
Nursing & Midwifery,Registered Nurses [note 3],120,300
Nursing & Midwifery,Midwives,10,25
Total,,130,325
"""


@pytest.fixture
def single_label_csv(tmp_path):
    path = tmp_path / "single.csv"
    path.write_text(SINGLE_LABEL_CSV, encoding="utf-8")
    return path


@pytest.fixture
def two_label_csv(tmp_path):
    path = tmp_path / "two.csv"
    path.write_text(TWO_LABEL_CSV, encoding="utf-8")
    return path


class TestStripNoteRefs:
    def test_removes_footnote_marker(self):
        assert strip_note_refs("Registered Nurses [note 3]") == "Registered Nurses"

    def test_case_insensitive_marker(self):
        assert strip_note_refs("Midwives [Note 12]") == "Midwives"

    def test_collapses_whitespace(self):
        assert strip_note_refs("Pay bands 8   & above") == "Pay bands 8 & above"

    def test_strips_non_breaking_space(self):
        assert strip_note_refs("Total\xa0WTE") == "Total WTE"

    def test_collapses_embedded_newline(self):
        assert strip_note_refs("Pay bands 8\n& above") == "Pay bands 8 & above"

    def test_plain_label_unchanged(self):
        assert strip_note_refs("Medical & Dental") == "Medical & Dental"


class TestParseValue:
    def test_comma_grouped_thousands(self):
        assert parse_value("63,247.8") == 63247.8

    def test_percentage_becomes_proportion(self):
        assert parse_value("4.3%") == pytest.approx(0.043)

    def test_negative_percentage(self):
        assert parse_value("-11.8%") == pytest.approx(-0.118)

    def test_plain_integer(self):
        assert parse_value("566") == 566.0

    @pytest.mark.parametrize("marker", ["[z]", "[c]", "[x]", "[w]", "[u]"])
    def test_suppression_markers_are_none(self, marker):
        assert parse_value(marker) is None

    @pytest.mark.parametrize("blank", ["", "   ", "-", "..", "*"])
    def test_blanks_are_none(self, blank):
        assert parse_value(blank) is None

    def test_non_numeric_text_is_none(self):
        assert parse_value("Belfast HSC Trust") is None


class TestParsePeriodColumn:
    def test_bare_year_is_march_census_point(self):
        assert parse_period_column("2026") == pd.Timestamp("2026-03-31")

    def test_full_quarter_end_date(self):
        assert parse_period_column("30 Jun 2017") == pd.Timestamp("2017-06-30")

    def test_financial_year_is_not_a_date(self):
        assert parse_period_column("2020/21") is None

    def test_derived_column_is_not_a_date(self):
        assert parse_period_column("% Change 2021 to 2026") is None

    def test_ignores_footnote_ref(self):
        assert parse_period_column("2026 [note 1]") == pd.Timestamp("2026-03-31")


class TestParseCsvTables:
    def test_splits_stacked_sub_tables(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        assert set(df.table_id) == {"1", "2A"}

    def test_captures_table_title(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        assert df[df.table_id == "2A"].table_title.iloc[0] == "HSC Workforce by Organisation"

    def test_strips_note_refs_from_row_labels(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        assert "Administration & Clerical" in set(df.row_label)

    def test_parses_comma_grouped_values(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        row = df[(df.row_label == "Belfast HSC Trust") & (df.column == "2025")]
        assert row.value.iloc[0] == 19063.1

    def test_suppressed_cell_becomes_null(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        row = df[(df.row_label == "Medical & Dental") & (df.column == "2026")]
        assert pd.isna(row.value.iloc[0])

    def test_skips_blank_filler_rows(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        assert (df.row_label.str.strip() != "").all()

    def test_single_label_table_has_no_row_group(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        assert df.row_group.isna().all()

    def test_preamble_before_first_marker_ignored(self, single_label_csv):
        df = parse_csv_tables(single_label_csv)
        assert not df.row_label.str.contains("preamble", case=False).any()

    def test_detects_two_label_columns(self, two_label_csv):
        df = parse_csv_tables(two_label_csv)
        nurses = df[df.row_label == "Registered Nurses"]
        assert nurses.row_group.iloc[0] == "Nursing & Midwifery"

    def test_total_row_keeps_outer_label(self, two_label_csv):
        df = parse_csv_tables(two_label_csv)
        assert "Total" in set(df.row_label)

    def test_two_label_values_parsed(self, two_label_csv):
        df = parse_csv_tables(two_label_csv)
        row = df[(df.row_label == "Midwives") & (df.column == "Total")]
        assert row.value.iloc[0] == 25.0

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(NISRADataNotFoundError, match="Failed to read"):
            parse_csv_tables(tmp_path / "nope.csv")

    def test_file_without_tables_raises(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("just,some,rows\nwith,no,markers\n", encoding="utf-8")
        with pytest.raises(NISRADataNotFoundError, match="No data tables"):
            parse_csv_tables(path)
