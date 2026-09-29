"""Tests for bolster.utils.htmlwidgets using small synthetic htmlwidgets pages (no network)."""

import base64
import json

import pandas as pd
import pytest

from bolster.utils.htmlwidgets import extract_widgets, plotly_frame


def _widget(widget_id: str, x: dict | None, raw: str | None = None) -> str:
    body = raw if raw is not None else json.dumps({"x": x, "evals": [], "jsHooks": []})
    return f'<script type="application/json" data-for="{widget_id}">{body}</script>'


def _plotly(traces: list[dict], **layout) -> dict:
    return {"data": traces, "layout": layout}


class TestExtractWidgets:
    def test_reads_plotly_widgets_in_page_order_with_sections(self):
        html = (
            "<h2>Population</h2>"
            + _widget("w1", _plotly([{"name": "Area", "type": "scatter", "x": ["2020"], "y": [1]}], title="Residents"))
            + "<h3>Health &amp; care</h3>"
            + _widget(
                "w2",
                _plotly([{"name": "NI", "type": "bar", "x": ["a"], "y": [2]}], title={"text": "Rates<br>per 1,000"}),
            )
        )
        first, second = extract_widgets(html)
        assert (first.widget_id, first.kind, first.section, first.title) == ("w1", "plotly", "Population", "Residents")
        assert (second.widget_id, second.section, second.title) == ("w2", "Health & care", "Rates per 1,000")

    def test_axis_titles_and_ticks(self):
        layout = {
            "xaxis": {"title": {"text": "Year"}, "tickvals": [1, 2], "ticktext": ["2020", "2021"]},
            "yaxis": {"title": "Percentage"},
        }
        (widget,) = extract_widgets(_widget("w", _plotly([{"name": "s", "x": [1], "y": [1]}], **layout)))
        assert (widget.x_title, widget.y_title) == ("Year", "Percentage")
        assert widget.ticks == {1: "2020", 2: "2021"}

    def test_non_plotly_widget_is_kept_without_traces(self):
        (widget,) = extract_widgets("<h2>Map</h2>" + _widget("map", {"options": {}, "calls": []}))
        assert (widget.kind, widget.traces, widget.section) == ("other", [], "Map")

    def test_ignores_library_bundles_and_pages_without_widgets(self):
        payload = base64.b64encode(b'data-for="not-a-widget" var x = 1').decode()
        html = f'<script src="data:application/javascript;base64,{payload}"></script><p>no charts</p>'
        assert extract_widgets(html) == []

    def test_invalid_json_is_reported_not_skipped(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            extract_widgets(_widget("w", None, raw="{not json"))

    def test_unexpected_content_after_the_json_is_reported(self):
        with pytest.raises(ValueError, match="Unexpected content"):
            extract_widgets('<script type="application/json" data-for="w">{"x": {}} trailing</script>')

    def test_widget_before_any_heading_has_empty_section(self):
        (widget,) = extract_widgets(_widget("w", _plotly([])))
        assert widget.section == ""


class TestPlotlyFrame:
    def test_vertical_series_and_units(self):
        html = _widget(
            "w",
            _plotly(
                [
                    {"name": "Area", "x": ["2020", "2021"], "y": [10, 12]},
                    {"name": "NI", "x": ["2020", "2021"], "y": [5, None]},
                ],
                title="Residents",
                yaxis={"title": "Number"},
            ),
        )
        df = plotly_frame(extract_widgets("<h2>Population</h2>" + html))
        assert list(df.columns) == ["section", "figure", "unit", "series", "category", "value"]
        assert df["series"].tolist() == ["Area", "Area", "NI", "NI"]
        assert df["unit"].unique().tolist() == ["Number"]
        assert df["value"].tolist()[:3] == [10.0, 12.0, 5.0]
        assert pd.isna(df["value"].iloc[3]), "a null plotted value becomes NaN"

    def test_horizontal_bars_use_y_as_the_category(self):
        html = _widget(
            "w",
            _plotly(
                [{"name": "2021", "type": "bar", "orientation": "h", "x": [30, 70], "y": ["Male", "Female"]}],
                xaxis={"title": "Percentage"},
            ),
        )
        df = plotly_frame(extract_widgets(html))
        assert df["category"].tolist() == ["Male", "Female"]
        assert df["value"].tolist() == [30.0, 70.0]
        assert df["unit"].unique().tolist() == ["Percentage"]

    def test_index_x_axis_is_resolved_through_ticktext(self):
        html = _widget(
            "w",
            _plotly(
                [{"name": "s", "x": [1, 2], "y": [5, 6]}], xaxis={"tickvals": [1, 2], "ticktext": ["0-15", "16-39"]}
            ),
        )
        assert plotly_frame(extract_widgets(html))["category"].tolist() == ["0-15", "16-39"]

    def test_non_plotly_and_empty_input(self):
        assert plotly_frame(extract_widgets(_widget("map", {"calls": []}))).empty
        empty = plotly_frame([])
        assert list(empty.columns) == ["section", "figure", "unit", "series", "category", "value"]
        assert str(empty["value"].dtype) == "float64"

    def test_unnamed_trace_gets_an_empty_series(self):
        html = _widget("w", _plotly([{"x": ["a"], "y": [1]}]))
        assert plotly_frame(extract_widgets(html))["series"].tolist() == [""]
