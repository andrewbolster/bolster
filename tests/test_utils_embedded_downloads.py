"""Tests for bolster.utils.embedded_downloads using small synthetic datavis pages (no network)."""

import base64
import io

import pandas as pd
import pytest

from bolster.utils.embedded_downloads import (
    EmbeddedFile,
    clean_labels,
    coerce_numeric,
    extract_embedded_files,
    read_tables,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows: list[list]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, header=False, index=False, engine="openpyxl")
    return buffer.getvalue()


def _figure_xlsx(title: str, header: list, data: list[list], footnote: str | None = None) -> bytes:
    rows = [[title] + [None] * (len(header) - 1), [None] * len(header), header, *data]
    if footnote:
        rows += [[None] * len(header), [footnote] + [None] * (len(header) - 1)]
    return _xlsx(rows)


def _anchor(mime: str, content: bytes, download: str | None = None, text: str = "x", quote: str = '"') -> str:
    payload = base64.b64encode(content).decode()
    attr = f" download={quote}{download}{quote}" if download else ""
    return f"<a{attr} href={quote}data:{mime};base64,{payload}{quote}>{text}</a>"


class TestExtractEmbeddedFiles:
    def test_keeps_csv_and_xlsx_in_page_order_and_ignores_other_data_uris(self):
        html = (
            _anchor("image/png", b"png", download="chart.png")
            + _anchor("text/csv", b"a,b\n1,2", download="Figure 1.csv")
            + _anchor(XLSX, _xlsx([[1]]), download="Figure 1.xlsx")
            + _anchor("application/javascript", b"var x=1", download="app.js")
        )
        files = extract_embedded_files(html)
        assert [(f.filename, f.kind) for f in files] == [("Figure 1.csv", "csv"), ("Figure 1.xlsx", "xlsx")]
        assert files[0].content == b"a,b\n1,2"

    def test_name_falls_back_to_link_text_then_placeholder(self):
        html = _anchor("text/csv", b"a\n1", text="Figure 2.CSV (3kB)") + _anchor("text/csv", b"a\n1", text="<b></b>")
        files = extract_embedded_files(html)
        assert [f.filename for f in files] == ["Figure 2.CSV (3kB)", "unnamed-2"]

    def test_tolerates_single_quotes_whitespace_and_missing_padding(self):
        payload = base64.b64encode(b"hello world!!").decode().rstrip("=")
        spaced = payload[:4] + "\n  " + payload[4:]
        html = f"<a download='Table 1.csv' href='data:text/csv;base64,{spaced}'>t</a>"
        (file,) = extract_embedded_files(html)
        assert file.content == b"hello world!!"
        assert file.filename == "Table 1.csv"

    def test_page_without_embedded_files(self):
        assert extract_embedded_files('<a href="https://example.com">x</a><p>no files</p>') == []


class TestLabel:
    @pytest.mark.parametrize(
        ("filename", "label"),
        [
            ("Figure 1-pay-publication-september-2026.xlsx", "Figure 1"),
            ("figure-12-vacancies.csv", "Figure 12"),
            ("fig2.csv", "Figure 2"),
            ("table-13a-average-daily-rates-202021.xlsx", "Table 13a"),
            ("Table 5--sickness.xlsx", "Table 5"),
            ("ecrg-figure-1-september-2026", "Figure 1"),
            ("Figure 1.CSV (3kB)", "Figure 1"),
            ("summary.csv", "summary"),
            ("prefigure-1-thing.csv", "prefigure-1-thing"),
        ],
    )
    def test_label(self, filename, label):
        assert EmbeddedFile(filename, "csv", b"").label == label


class TestReadTables:
    def test_xlsx_title_header_and_footnote(self):
        content = _figure_xlsx(
            "Figure 3: Median Pay (£) by Grade 2016-2026",
            ["Analogous Grade", 2016.0, 2017.0],
            [["AA", 17620.0, 17796.0], ["SpAd", None, 69336.0]],
            footnote="* Please note figures may not sum due to rounding",
        )
        (table,) = read_tables(_anchor(XLSX, content, download="Figure 3.xlsx")).values()
        assert table.label == "Figure 3"
        assert table.title == "Figure 3: Median Pay (£) by Grade 2016-2026"
        assert list(table.data.columns) == ["analogous_grade", "2016", "2017"]
        assert table.data["analogous_grade"].tolist() == ["AA", "SpAd"]
        assert table.data.shape == (2, 3)

    def test_blank_spacer_rows_between_data_rows_are_skipped(self):
        """Regression: a sheet alternating data and blank rows once parsed to zero rows."""
        content = _figure_xlsx("T", ["A", "B"], [[None, None], ["x", 1], [None, None], ["y", 2], [None, None]])
        (table,) = read_tables(_anchor(XLSX, content, download="Figure 1.xlsx")).values()
        assert table.data["a"].tolist() == ["x", "y"]
        assert table.data["b"].tolist() == [1, 2]

    def test_label_only_rows_are_dropped(self):
        content = _figure_xlsx(
            "T", ["Type", "2020", "2021"], [["Controlled", 1, 2], ["Covid-19", None, None], ["Other", 3, 4]]
        )
        (table,) = read_tables(_anchor(XLSX, content, download="Figure 1.xlsx")).values()
        assert table.data["type"].tolist() == ["Controlled", "Other"]

    def test_footnote_markers_are_removed_from_headers(self):
        content = _figure_xlsx("T", ["Management Type", "2015/16 [4]", "2016/17", "2017/18 [5]"], [["x", 1, 2, 3]])
        (table,) = read_tables(_anchor(XLSX, content, download="Table 7.xlsx")).values()
        assert list(table.data.columns) == ["management_type", "2015_16", "2016_17", "2017_18"]

    def test_duplicate_headers_are_made_unique(self):
        content = _figure_xlsx("T", ["Pay (£)", "Pay (€)", "Other"], [[1, 2, 3]])
        (table,) = read_tables(_anchor(XLSX, content, download="Figure 1.xlsx")).values()
        assert list(table.data.columns) == ["pay", "pay_2", "other"]

    def test_percent_headers_do_not_collide_with_plain_headers(self):
        content = _figure_xlsx("T", ["Grade", "Filled 2020", "% filled 2020"], [["x", 12, 48]])
        (table,) = read_tables(_anchor(XLSX, content, download="Table 2.xlsx")).values()
        assert list(table.data.columns) == ["grade", "filled_2020", "pct_filled_2020"]

    def test_xlsx_without_header_row_raises(self):
        content = _xlsx([["Figure 1: title only"], [None]])
        with pytest.raises(ValueError, match="No header row"):
            read_tables(_anchor(XLSX, content, download="Figure 1.xlsx"))

    @pytest.mark.parametrize(
        "encode",
        [
            pytest.param(lambda s: s.encode("utf-8"), id="utf8"),
            pytest.param(lambda s: s.encode("utf-8-sig"), id="utf8-bom"),
            pytest.param(lambda s: s.encode("utf-16-le"), id="utf16le-no-bom"),
            pytest.param(lambda s: s.encode("utf-16"), id="utf16-bom"),
        ],
    )
    def test_csv_encodings(self, encode):
        csv_text = '"Date","Pay (£)"\r\n"2019-01-01",41\r\n"2019-02-01",38\r\n'
        (table,) = read_tables(_anchor("text/csv", encode(csv_text), download="Figure 1.csv")).values()
        assert table.title == ""
        assert list(table.data.columns) == ["date", "pay"]
        assert table.data["date"].tolist() == ["2019-01-01", "2019-02-01"]
        assert table.data["pay"].tolist() == ["41", "38"]

    def test_prefers_xlsx_over_csv_whichever_comes_first(self):
        xlsx = _anchor(XLSX, _figure_xlsx("Figure 1: from xlsx", ["A", "B"], [["x", 1]]), download="Figure 1.xlsx")
        csv = _anchor("text/csv", b"A,B\nfrom-csv,1\n", download="Figure 1.csv")
        for html in (xlsx + csv, csv + xlsx):
            (table,) = read_tables(html).values()
            assert table.title == "Figure 1: from xlsx"

    def test_figures_and_tables_keep_page_order(self):
        html = "".join(
            _anchor("text/csv", b"A,B\n1,2\n", download=name)
            for name in ["Figure 1.csv", "Table 10.csv", "Table 2.csv", "Table 13a.csv"]
        )
        assert list(read_tables(html)) == ["Figure 1", "Table 10", "Table 2", "Table 13a"]

    def test_no_embedded_files(self):
        assert read_tables("<html></html>") == {}


class TestCleanLabels:
    def test_drops_footnote_markers_and_collapses_whitespace(self):
        labels = pd.Series(["Controlled [3]", "NICS\nOverall", "  Perm   Sec ", "Ind 1 [note 2]", "AA"])
        assert clean_labels(labels).tolist() == ["Controlled", "NICS Overall", "Perm Sec", "Ind 1", "AA"]


class TestCoerceNumeric:
    def test_strips_display_formatting(self):
        result = coerce_numeric(pd.Series(["3.4%", "£1,234", " 7 ", "-2.1%", 5, 2.5]))
        assert result.tolist() == [3.4, 1234.0, 7.0, -2.1, 5.0, 2.5]

    def test_unparseable_and_missing_become_nan(self):
        result = coerce_numeric(pd.Series(["[c]", "-", None, float("nan"), "n/a"]))
        assert result.isna().all()
        assert str(result.dtype) == "float64"
