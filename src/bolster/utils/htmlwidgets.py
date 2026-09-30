"""Read chart data out of R ``htmlwidgets`` pages, without executing any JavaScript.

R's ``htmlwidgets`` package (used by ``plotly`` for R, ``leaflet`` and others) writes each widget's
data into the page as JSON::

    <script type="application/json" data-for="htmlwidget-abc123">{"x": {"data": [...], "layout": {...}}, ...}</script>

so the numbers behind a Plotly chart can be read directly. NISRA's "datavis" reports built this way (for
example the Neighbourhood Renewal Area profiles) have no downloadable files, only these blocks.

This is general to any htmlwidgets page, not specific to NISRA. Only Plotly widgets are decoded into
traces; other widget types (a Leaflet map, say) are returned with ``kind="other"`` and no traces.

Library bundles (jQuery, plotly.js) sit in the page as inline or base64 ``data:`` scripts and are never
scanned: only ``<script type="application/json" data-for=...>`` tags are looked at.

Example:
    >>> from bolster.utils.htmlwidgets import extract_widgets, plotly_frame
    >>> html = (
    ...     '<h2>Population</h2>'
    ...     '<script type="application/json" data-for="htmlwidget-1">'
    ...     '{"x": {"data": [{"name": "Area", "type": "scatter", "x": ["2020", "2021"], "y": [10, 12]}],'
    ...     ' "layout": {"title": "Residents", "yaxis": {"title": "Number"}}}}'
    ...     '</script>'
    ... )
    >>> plotly_frame(extract_widgets(html))[["section", "series", "category", "value"]].values.tolist()
    [['Population', 'Area', '2020', 10.0], ['Population', 'Area', '2021', 12.0]]
"""

import html as html_lib
import json
import re
from dataclasses import dataclass, field

import pandas as pd

_OPEN = '<script type="application/json" data-for="'
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TRACE_KEYS = ("name", "type", "orientation", "x", "y", "text")
_decoder = json.JSONDecoder()


@dataclass(frozen=True)
class Widget:
    """One htmlwidget on a page.

    ``section`` is the nearest preceding heading (``<h1>``-``<h4>``). ``ticks`` maps numeric x positions to
    their labels for charts whose x axis is an index with ``ticktext``.
    """

    widget_id: str
    kind: str
    section: str = ""
    title: str = ""
    x_title: str = ""
    y_title: str = ""
    ticks: dict[int, str] = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)


def _text(value: object) -> str:
    """Plotly titles are a string or ``{"text": ...}``; drop tags, decode entities, collapse whitespace."""
    if isinstance(value, dict):
        value = value.get("text", "")
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG_RE.sub(" ", str(value or "")))).strip()


def extract_widgets(html: str) -> list[Widget]:
    """Return every htmlwidget on the page, in page order.

    Args:
        html: The page's HTML.

    Returns:
        One :class:`Widget` per ``data-for`` JSON block; empty if the page has none.

    Raises:
        ValueError: If a widget block is not valid JSON followed by ``</script>``. These blocks are widget
            data by contract, so this is reported and not skipped.
    """
    headings = [(m.start(), _text(m.group(2))) for m in _HEADING_RE.finditer(html)]
    widgets, pos = [], 0
    while (start := html.find(_OPEN, pos)) != -1:
        id_end = html.index('"', start + len(_OPEN))
        widget_id = html[start + len(_OPEN) : id_end]
        body_start = html.index(">", id_end) + 1
        try:
            payload, body_end = _decoder.raw_decode(html, body_start)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Widget {widget_id} is not valid JSON: {exc}") from exc
        if not html.startswith("</script>", body_end):
            raise ValueError(f"Unexpected content after widget {widget_id}")
        pos = body_end
        section = next((text for at, text in reversed(headings) if at < start), "")
        x = payload.get("x") if isinstance(payload, dict) else None
        if not isinstance(x, dict) or "data" not in x:
            widgets.append(Widget(widget_id, "other", section))
            continue
        layout = x.get("layout") or {}
        x_axis, y_axis = layout.get("xaxis") or {}, layout.get("yaxis") or {}
        ticks = {
            round(v): label
            for v, label in zip(x_axis.get("tickvals") or [], x_axis.get("ticktext") or [], strict=False)
        }
        widgets.append(
            Widget(
                widget_id=widget_id,
                kind="plotly",
                section=section,
                title=_text(layout.get("title")),
                x_title=_text(x_axis.get("title")),
                y_title=_text(y_axis.get("title")),
                ticks=ticks,
                traces=[{key: trace.get(key) for key in _TRACE_KEYS} for trace in x["data"]],
            )
        )
    return widgets


def plotly_frame(widgets: list[Widget]) -> pd.DataFrame:
    """Flatten Plotly widgets into one row per plotted value.

    The category axis is ``y`` for horizontal bars and ``x`` otherwise; a numeric x position with tick labels
    is replaced by its label. ``unit`` is the title of the value axis.

    Args:
        widgets: Output of :func:`extract_widgets`; non-Plotly widgets are ignored.

    Returns:
        DataFrame with ``section``, ``figure`` (the chart title), ``unit``, ``series`` (trace name),
        ``category`` (str) and ``value`` (float, ``NaN`` where the plotted value is null).
    """
    rows = []
    for widget in widgets:
        if widget.kind != "plotly":
            continue
        for trace in widget.traces:
            horizontal = trace.get("orientation") == "h"
            categories, values = (trace["y"], trace["x"]) if horizontal else (trace["x"], trace["y"])
            unit = widget.x_title if horizontal else widget.y_title
            for category, value in zip(categories or [], values or [], strict=False):
                if widget.ticks and isinstance(category, int | float):
                    category = widget.ticks.get(round(category), category)
                rows.append(
                    {
                        "section": widget.section,
                        "figure": widget.title,
                        "unit": unit,
                        "series": trace.get("name") or "",
                        "category": str(category),
                        "value": value,
                    }
                )
    frame = pd.DataFrame(rows, columns=["section", "figure", "unit", "series", "category", "value"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype("float64")
    return frame
