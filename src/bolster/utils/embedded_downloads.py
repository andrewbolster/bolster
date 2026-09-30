"""Read data files embedded in a page as base64 ``data:`` download links.

Some report pages have no server-side download endpoint: each chart's download button is instead an
``<a download="...">`` link whose ``href`` is a base64 ``data:`` URI holding a real ``.csv`` and/or
``.xlsx`` of that chart's data, so the file can be recovered without touching any chart JavaScript. This
module reads those links; for pages built with R htmlwidgets instead (data in a JSON script block, no
downloadable files), see :mod:`bolster.utils.htmlwidgets`.

The label and layout rules below are defaults tuned for NISRA's "datavis" tool (``datavis.nisra.gov.uk``,
also used by DE, DfE and DfC), the only source currently read this way. A page can carry both "Figure N"
and "Table N" downloads (tables may be lettered, ``Table 13a``); each is identified by a label such as
``"Figure 1"`` or ``"Table 13a"``, and a file whose name has neither falls back to its filename, so
nothing on the page is silently skipped.

Two layouts occur:

* ``.xlsx``: one sheet with a title row, a blank row, a header row, then data
  rows. Blank spacer rows may sit between data rows, and footnotes may follow;
  both are dropped, as are label-only rows (section headings with no values).
* ``.csv``: header row then data rows, encoded as UTF-8 or as UTF-16-LE without
  a byte-order mark. No title.

Pages that embed both are read from the ``.xlsx`` (it carries the title and needs
no encoding detection); an item that only has a ``.csv`` is read from that.

Pages that embed no files (their data lives only in Plotly figure JSON) are out
of scope; :func:`read_tables` returns an empty mapping for them.

Example:
    >>> from bolster.utils.embedded_downloads import read_tables
    >>> html = "<html></html>"
    >>> read_tables(html)
    {}
"""

import base64
import io
import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from bolster.utils.text import clean_column_name

_MIME_KINDS: dict[str, Literal["csv", "xlsx"]] = {
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

_ANCHOR_RE = re.compile(r"(<a\b[^>]*>)(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r"""href=(["'])data:([^;,"']+)[^"']*?;base64,([^"']+)\1""", re.IGNORECASE)
_DOWNLOAD_RE = re.compile(r"""download=(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
_LABEL_RE = re.compile(r"(?<![a-z])(fig(?:ure)?|table)[\s_-]*(\d+[a-z]?)(?![a-z0-9])", re.IGNORECASE)
_NON_NUMERIC_RE = re.compile(r"[%£€,\s]")
_NOTE_RE = re.compile(r"\s*\[[^\]]*\]")


@dataclass(frozen=True)
class EmbeddedFile:
    """A data file embedded in a page as a base64 ``data:`` URI."""

    filename: str
    kind: Literal["csv", "xlsx"]
    content: bytes

    @property
    def label(self) -> str:
        """``"Figure N"`` / ``"Table N"`` found in the filename, else the filename without its extension.

        Example:
            >>> EmbeddedFile("Figure 3-pay-2026.xlsx", "xlsx", b"").label
            'Figure 3'
            >>> EmbeddedFile("table-13a-daily-rates-202425.xlsx", "xlsx", b"").label
            'Table 13a'
            >>> EmbeddedFile("ecrg-figure-1-september-2026", "csv", b"").label
            'Figure 1'
            >>> EmbeddedFile("summary.csv", "csv", b"").label
            'summary'
        """
        match = _LABEL_RE.search(self.filename)
        if match:
            kind = "Table" if match.group(1).lower() == "table" else "Figure"
            return f"{kind} {match.group(2).lower()}"
        return self.filename.rsplit(".", 1)[0]


@dataclass(frozen=True)
class EmbeddedTable:
    """One embedded figure or table: its label, title (empty for CSV-only items) and data.

    ``data`` has snake_case column names (bracketed footnote markers such as ``[4]`` removed and ``%``
    spelled ``pct``) and untouched cell values; use :func:`coerce_numeric` for columns that should be numbers
    and :func:`clean_labels` for label columns.
    """

    label: str
    title: str
    data: pd.DataFrame


def extract_embedded_files(html: str) -> list[EmbeddedFile]:
    r"""Return every ``.csv``/``.xlsx`` file embedded as a base64 ``data:`` link, in page order.

    A file's name comes from the ``download`` attribute, else the link text (some pages label
    links ``Figure 1.CSV (3kB)`` and set no ``download``), else ``unnamed-N``. Links of other
    types (images, scripts, fonts) are ignored.

    Args:
        html: The page's HTML.

    Returns:
        The embedded files; empty if the page embeds none.

    Example:
        >>> import base64
        >>> payload = base64.b64encode(b"a,b\n1,2").decode()
        >>> html = f'<a download="Figure 1.csv" href="data:text/csv;base64,{payload}">x</a>'
        >>> [(f.filename, f.kind) for f in extract_embedded_files(html)]
        [('Figure 1.csv', 'csv')]
        >>> html = f'<a href="data:text/csv;base64,{payload}">Figure 2.CSV (3kB)</a>'
        >>> [(f.filename, f.label) for f in extract_embedded_files(html)]
        [('Figure 2.CSV (3kB)', 'Figure 2')]
    """
    files: list[EmbeddedFile] = []
    for anchor in _ANCHOR_RE.finditer(html):
        tag = anchor.group(1)
        href = _HREF_RE.search(tag)
        if not href:
            continue
        kind = _MIME_KINDS.get(href.group(2).lower())
        if kind is None:
            continue
        download = _DOWNLOAD_RE.search(tag)
        filename = download.group(2).strip() if download else ""
        filename = filename or _TAG_RE.sub("", anchor.group(2)).strip() or f"unnamed-{len(files) + 1}"
        payload = re.sub(r"\s", "", href.group(3))
        payload += "=" * (-len(payload) % 4)
        files.append(EmbeddedFile(filename=filename, kind=kind, content=base64.b64decode(payload)))
    return files


def read_tables(html: str) -> dict[str, EmbeddedTable]:
    """Parse every figure and table embedded in the page as a base64 `data:` download link.

    An item with both an ``.xlsx`` and a ``.csv`` is read from the ``.xlsx``.

    Args:
        html: The page's HTML.

    Returns:
        Mapping of label (``"Figure 1"``, ``"Table 13a"``, ...) to :class:`EmbeddedTable`, in page order.
    """
    chosen: dict[str, EmbeddedFile] = {}
    for file in extract_embedded_files(html):
        label = file.label
        if label not in chosen or (file.kind == "xlsx" and chosen[label].kind == "csv"):
            chosen[label] = file
    return {label: _parse_table(label, file) for label, file in chosen.items()}


def coerce_numeric(series: pd.Series) -> pd.Series:
    """Convert a column of display strings to numbers, mapping anything non-numeric to ``NaN``.

    Strips ``%``, ``£``, ``€``, thousands commas and whitespace first, so ``"3.4%"`` becomes
    ``3.4`` and ``"£1,234"`` becomes ``1234.0``. Percentages are *not* divided by 100.

    Example:
        >>> coerce_numeric(pd.Series(["3.4%", "£1,234", "[x]", None, 7])).tolist()
        [3.4, 1234.0, nan, nan, 7.0]
    """
    cleaned = series.astype("string").str.replace(_NON_NUMERIC_RE, "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").astype("float64")


def clean_labels(series: pd.Series) -> pd.Series:
    r"""Tidy a column of row labels: drop bracketed footnote markers and collapse whitespace.

    Example:
        >>> clean_labels(pd.Series(["Controlled [3]", "NICS\nOverall", "  Perm   Sec "])).tolist()
        ['Controlled', 'NICS Overall', 'Perm Sec']
    """
    return series.astype(str).str.replace(_NOTE_RE, "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()


def _parse_table(label: str, file: EmbeddedFile) -> EmbeddedTable:
    if file.kind == "xlsx":
        raw = pd.read_excel(io.BytesIO(file.content), header=None)
        title, header_row = _title_and_header_row(raw)
        return EmbeddedTable(label, title, _table_below(raw, header_row))
    raw = pd.read_csv(io.StringIO(_decode_csv(file.content)), header=None, dtype=object)
    return EmbeddedTable(label, "", _table_below(raw, 0))


def _decode_csv(content: bytes) -> str:
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return content.decode("utf-16")
    if b"\x00" in content[:64]:
        return content.decode("utf-16-le")
    return content.decode("utf-8-sig")


def _title_and_header_row(raw: pd.DataFrame) -> tuple[str, int]:
    """Locate an xlsx table's title (row 0) and header (first later row with 2+ filled cells)."""
    title = next((str(v).strip() for v in raw.iloc[0] if pd.notna(v)), "") if len(raw) else ""
    filled = raw.notna().sum(axis=1)
    header_row = next((i for i in range(1, len(raw)) if filled.iloc[i] >= 2), None)
    if header_row is None:
        raise ValueError("No header row found in embedded table")
    return title, header_row


def _table_below(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Build the table from the rows below the header.

    Blank spacer rows are skipped, and so are rows with only their first cell filled (footnotes,
    section headings) when the table has more than one column.
    """
    columns = _unique([clean_column_name(_header_text(v)) for v in raw.iloc[header_row]])
    body = raw.iloc[header_row + 1 :].dropna(how="all")
    if body.shape[1] > 1:
        body = body[body.notna().sum(axis=1) > 1]
    body.columns = columns
    return body.reset_index(drop=True)


def _header_text(value: object) -> str:
    """Render a header cell for cleaning.

    Integer-valued floats (``2016.0``) become ``"2016"``, ``[4]`` markers are dropped, and ``%`` becomes
    ``pct`` so ``"% filled 2020"`` does not collide with ``"Filled 2020"``.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _NOTE_RE.sub("", str(value)).replace("%", " pct ")


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        out.append(name if count == 0 else f"{name}_{count + 1}")
    return out
