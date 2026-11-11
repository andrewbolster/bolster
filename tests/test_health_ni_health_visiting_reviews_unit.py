"""Offline unit tests for the health visiting reviews module.

The workbooks are built in memory in each of the layouts the Department of Health has used, so these
tests need no network. The live behaviour is covered in
``test_health_ni_health_visiting_reviews_integrity.py``.
"""

import logging
from pathlib import Path

import pandas as pd
import pytest

from bolster.data_sources.health_ni import health_visiting_reviews as hvr
from bolster.data_sources.health_ni._base import NISRADataNotFoundError, NISRAValidationError

TABLE_1_LABELS = [
    "New Baby Review by HV",
    "6 to 8 Week Review by HV",
    "14 to 16 Week Health Review by HV",
    "6 to 9 Month Contact by HV",
    "Health Review at 1 Year by HV",
    "Health Review at 2-21/2 Years by HV",
]
REVIEW_HEADINGS = [
    "New Baby Review",
    "6 - 8 Week Review",
    "14 - 16 Week Health Review",
    "6 - 9 Month Contact",
    "Health Review at 1 Year",
    "Health Review at 2 - 2½ Years",
]
QUARTER_LABELS = [
    "New baby review ",
    "6 – 8 Week Review ",
    "14 – 16 Week Health Review",
    "6 – 9 Month Contact ",
    "Health Review at 1 Year ",
    "Health Review at 2 – 2½ Years",
]
OUTCOME_HEADERS = ["Contact Early", "Contact on Time", "Contact Late", "No Contact", "Children in Cohort"]
PCT_HEADERS = [
    "% Contact Early",
    "% Contact on Time",
    "% Contact Late",
    "% No Contact",
    "% Contact Early, On time or Late",
]


def _trust_counts(review_index: int, trust_index: int) -> list[int]:
    early, late, none = 3 + trust_index, 20 + review_index, 5 + trust_index
    on_time = 400 + 10 * review_index + 25 * trust_index
    return [early, on_time, late, none, early + on_time + late + none]


def _block(review_index: int) -> list[list[int]]:
    rows = [_trust_counts(review_index, t) for t in range(len(hvr.TRUSTS))]
    return [*rows, [sum(column) for column in zip(*rows, strict=True)]]


def _pct(counts: list[int]) -> list[float]:
    cohort = counts[4]
    early, on_time, late, none = (c / cohort for c in counts[:4])
    return [early, on_time, late, none, early + on_time + late]


def _sheets(
    *,
    lead_col: bool,
    ab_titles: bool,
    gap: bool,
    quarters: str,
    ni_override: dict[str, int] | None = None,
) -> dict[str, list[list[object]]]:
    """Build the table sheets of one synthetic release in the requested layout family."""
    pad: list[object] = [None] if lead_col else []

    def title(number: int, suffix: str, text: str) -> list[object]:
        return [*pad, f"Table {number}{suffix}: {text}" if ab_titles else f"Table {number}: {text}"]

    sheets: dict[str, list[list[object]]] = {"Notes": [[*pad, "Notes"]]}

    def table(number: int, corner: str, labels: list[str], counts: list[list[int]]) -> list[list[object]]:
        rows: list[list[object]] = []
        if lead_col:
            rows += [[None], title(number, "a", "Number"), [None]]
        else:
            rows += [title(number, "a", "Number")]
        rows.append([*pad, corner, *OUTCOME_HEADERS])
        rows += [[*pad, label, *row] for label, row in zip(labels, counts, strict=True)]
        if gap:
            rows.append([None])
        rows.append(title(number, "b", "Proportion"))
        rows.append([*pad, corner, *PCT_HEADERS])
        rows += [[*pad, label, *_pct(row)] for label, row in zip(labels, counts, strict=True)]
        return rows

    per_review = [_block(r) for r in range(6)]
    summary = [block[-1] for block in per_review]
    sheets["Table 1"] = table(1, "Northern Ireland", TABLE_1_LABELS, summary)
    geographies = [*hvr.TRUSTS, "Northern Ireland"]
    for r in range(6):
        counts = [list(row) for row in per_review[r]]
        if ni_override and r == 0:
            counts[-1] = [ni_override.get(h, v) for h, v in zip(OUTCOME_HEADERS, counts[-1], strict=True)]
        sheets[f"Table {r + 2}"] = table(r + 2, REVIEW_HEADINGS[r], geographies, counts)

    values = [[0.9 - 0.01 * r - 0.005 * q for q in range(4)] for r in range(6)]
    rows8: list[list[object]] = []
    if quarters == "grouped":  # years head their four columns, Q1-Q4 below
        rows8 += [[None], [*pad, "Table 8: Proportion on time"], [None]]
        rows8.append([*pad, None, "2017/18", None, None, None, "2018/19"])
        rows8.append([*pad, "Northern Ireland", *["Q1", "Q2", "Q3", "Q4"] * 2])
        rows8 += [[*pad, QUARTER_LABELS[r], *values[r], *values[r]] for r in range(6)]
        rows8.append([*pad, 'Source: "Healthy Child, Healthy Future"'])
    elif quarters == "repeated":  # year repeated above every quarter column
        rows8 += [[*pad, "Table 8: Proportion on time"]]
        rows8.append([*pad, None, *["2018/19"] * 4, *["2019/20"] * 4])
        rows8.append([*pad, "Northern Ireland", *["Q1", "Q2", "Q3", "Q4"] * 2])
        rows8 += [[*pad, QUARTER_LABELS[r], *values[r], *values[r]] for r in range(6)]
    else:  # combined "2018/19 Q1" labels
        rows8 += [[*pad, "Table 8: Proportion on time"]]
        labels = [f"{y} Q{q}" for y in ("2018/19", "2019/20") for q in (1, 2, 3, 4)]
        rows8.append([*pad, "Northern Ireland", *labels])
        rows8 += [[*pad, QUARTER_LABELS[r], *values[r], *values[r]] for r in range(6)]
    sheets["Table 8"] = rows8
    return sheets


def _write(path: Path, sheets: dict[str, list[list[object]]]) -> pd.ExcelFile:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            width = max(len(row) for row in rows)
            pd.DataFrame([row + [None] * (width - len(row)) for row in rows]).to_excel(
                writer, sheet_name=name, header=False, index=False
            )
    return pd.ExcelFile(path)


LAYOUTS = {
    "legacy": {"lead_col": True, "ab_titles": False, "gap": True, "quarters": "grouped"},
    "titled": {"lead_col": False, "ab_titles": True, "gap": True, "quarters": "repeated"},
    "no_gap": {"lead_col": False, "ab_titles": True, "gap": False, "quarters": "combined"},
}


@pytest.fixture(params=sorted(LAYOUTS))
def workbook(request: pytest.FixtureRequest, tmp_path: Path) -> pd.ExcelFile:
    return _write(tmp_path / f"{request.param}.xlsx", _sheets(**LAYOUTS[request.param]))


class TestReviewKey:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("New Baby Review by HV", "new_baby"),
            ("New baby review ", "new_baby"),
            ("6 to 8 Week Review by HV", "6_8_weeks"),
            ("6 - 8 Week Review", "6_8_weeks"),
            ("6 – 8 Week Review ", "6_8_weeks"),
            ("14 to 16 Week Health Review by HV", "14_16_weeks"),
            ("6 to 9 Month Contact by HV", "6_9_months"),
            ("6 – 9 Month Contact ", "6_9_months"),
            ("Health Review at 1 Year by HV", "1_year"),
            ("Health Review at 2-21/2 Years by HV", "2_2_5_years"),
            ("Health Review at 2 - 2½ Years", "2_2_5_years"),
            ("Health Review at 2 – 2½ Years", "2_2_5_years"),
        ],
    )
    def test_known_labels(self, label: str, expected: str) -> None:
        assert hvr.review_key(label) == expected

    @pytest.mark.parametrize("label", ["Northern Ireland", "Belfast", "", "Source: HCHF"])
    def test_non_reviews_are_none(self, label: str) -> None:
        assert hvr.review_key(label) is None

    def test_every_review_has_a_label_in_each_table_style(self) -> None:
        for labels in (TABLE_1_LABELS, REVIEW_HEADINGS, QUARTER_LABELS):
            assert [hvr.review_key(label) for label in labels] == list(hvr.REVIEWS)


class TestOutcomesParsing:
    def test_every_layout_gives_the_same_frame(self, workbook: pd.ExcelFile) -> None:
        df = hvr._parse_outcomes(workbook, 2025)
        assert df.shape == (36, 10)
        assert list(df.columns) == [
            "year",
            "financial_year",
            "review",
            "trust",
            *hvr.OUTCOME_COLUMNS,
            "cohort",
            "on_time_pct",
        ]
        assert set(df["financial_year"]) == {"2025/26"}
        assert hvr.validate_outcomes(df)

    def test_values_survive_each_layout(self, workbook: pd.ExcelFile) -> None:
        df = hvr._parse_outcomes(workbook, 2025)
        row = df[(df["review"] == "6_8_weeks") & (df["trust"] == "Southern")].iloc[0]
        assert [int(row[c]) for c in (*hvr.OUTCOME_COLUMNS, "cohort")] == _trust_counts(1, 3)
        assert row["on_time_pct"] == pytest.approx(_trust_counts(1, 3)[1] / _trust_counts(1, 3)[4] * 100)

    def test_proportion_block_is_not_read_as_counts_when_there_is_no_gap(self, tmp_path: Path) -> None:
        df = hvr._parse_outcomes(_write(tmp_path / "w.xlsx", _sheets(**LAYOUTS["no_gap"])), 2025)
        assert (df["cohort"] > 1).all()
        assert pd.api.types.is_integer_dtype(df["cohort"])

    def test_rows_are_in_review_then_geography_order(self, workbook: pd.ExcelFile) -> None:
        df = hvr._parse_outcomes(workbook, 2025)
        assert df["review"].drop_duplicates().tolist() == list(hvr.REVIEWS)
        assert df.head(6)["trust"].tolist() == ["Northern Ireland", *hvr.TRUSTS]

    def test_suppressed_counts_are_missing(self, tmp_path: Path) -> None:
        sheets = _sheets(**LAYOUTS["legacy"])
        # Suppress Southern's contact early and no contact in Table 2 (row of Southern in the counts block).
        for row in sheets["Table 2"]:
            if len(row) > 2 and row[1] == "Southern" and isinstance(row[2], int):
                row[2], row[5] = "-", "-"
                break
        df = hvr._parse_outcomes(_write(tmp_path / "w.xlsx", sheets), 2018)
        southern = df[(df["review"] == "new_baby") & (df["trust"] == "Southern")].iloc[0]
        assert pd.isna(southern["contact_early"]) and pd.isna(southern["no_contact"])
        assert hvr.validate_outcomes(df)

    def test_disagreeing_northern_ireland_row_uses_summary_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        sheets = _sheets(**LAYOUTS["titled"], ni_override={"Contact Early": 79, "Contact on Time": 19600})
        with caplog.at_level(logging.WARNING, logger=hvr.logger.name):
            df = hvr._parse_outcomes(_write(tmp_path / "w.xlsx", sheets), 2022)
        ni = df[(df["review"] == "new_baby") & (df["trust"] == "Northern Ireland")].iloc[0]
        assert int(ni["contact_early"]) == _block(0)[-1][0]
        assert "2022/23 new_baby contact_early is 79 in its own table" in caplog.text
        assert hvr.validate_outcomes(df)

    def test_unrecognised_geography_raises(self, tmp_path: Path) -> None:
        sheets = _sheets(**LAYOUTS["titled"])
        for row in sheets["Table 2"]:
            if row[0] == "Belfast":
                row[0] = "Belfast City"
                break
        with pytest.raises(NISRAValidationError, match="unrecognised geography"):
            hvr._parse_outcomes(_write(tmp_path / "w.xlsx", sheets), 2025)

    def test_missing_outcome_column_raises(self, tmp_path: Path) -> None:
        sheets = _sheets(**LAYOUTS["titled"])
        for row in sheets["Table 3"]:
            if "Contact Late" in row:
                row[row.index("Contact Late")] = "Contact Whenever"
                break
        with pytest.raises(NISRAValidationError, match="missing columns"):
            hvr._parse_outcomes(_write(tmp_path / "w.xlsx", sheets), 2025)

    def test_workbook_without_count_tables_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NISRAValidationError, match="no health review count tables"):
            hvr._parse_outcomes(_write(tmp_path / "w.xlsx", {"Table 1": [["nothing", "here"]]}), 2025)


class TestQuarterlyParsing:
    def test_every_layout_gives_eight_quarters_per_review(self, workbook: pd.ExcelFile) -> None:
        df = hvr._parse_quarterly(workbook, 2019)
        assert df.shape == (48, 6)
        assert df["financial_year"].nunique() == 2
        assert hvr.validate_quarterly(df)

    def test_quarter_starts_follow_the_financial_year(self, workbook: pd.ExcelFile) -> None:
        df = hvr._parse_quarterly(workbook, 2019)
        first_year = int(df["year"].min())
        quarters = df[(df["year"] == first_year) & (df["review"] == "new_baby")].sort_values("quarter")
        assert quarters["quarter_start"].tolist() == [
            pd.Timestamp(year=first_year, month=4, day=1),
            pd.Timestamp(year=first_year, month=7, day=1),
            pd.Timestamp(year=first_year, month=10, day=1),
            pd.Timestamp(year=first_year + 1, month=1, day=1),
        ]

    def test_values_are_percentages(self, workbook: pd.ExcelFile) -> None:
        df = hvr._parse_quarterly(workbook, 2019)
        first = df[(df["review"] == "new_baby")].sort_values("quarter_start").iloc[0]
        assert first["on_time_pct"] == pytest.approx(90.0)

    def test_source_footer_is_not_a_review(self, tmp_path: Path) -> None:
        df = hvr._parse_quarterly(_write(tmp_path / "w.xlsx", _sheets(**LAYOUTS["legacy"])), 2018)
        assert set(df["review"]) == set(hvr.REVIEWS)

    def test_workbook_without_a_quarterly_table_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NISRAValidationError, match="no quarterly table"):
            hvr._parse_quarterly(_write(tmp_path / "w.xlsx", {"Table 1": [["nothing", "here"]]}), 2025)

    def test_quarter_without_a_year_raises(self, tmp_path: Path) -> None:
        sheets = {
            "Table 8": [
                ["Table 8"],
                ["Northern Ireland", "Q1", "Q2", "Q3", "Q4"],
                ["New baby review", 0.9, 0.9, 0.9, 0.9],
            ]
        }
        with pytest.raises(NISRAValidationError, match="no financial year"):
            hvr._parse_quarterly(_write(tmp_path / "w.xlsx", sheets), 2025)


class TestValidation:
    @pytest.fixture
    def outcomes(self, tmp_path: Path) -> pd.DataFrame:
        return hvr._parse_outcomes(_write(tmp_path / "w.xlsx", _sheets(**LAYOUTS["titled"])), 2025)

    @pytest.fixture
    def quarterly(self, tmp_path: Path) -> pd.DataFrame:
        return hvr._parse_quarterly(_write(tmp_path / "w.xlsx", _sheets(**LAYOUTS["titled"])), 2019)

    def test_valid_outcomes(self, outcomes: pd.DataFrame) -> None:
        assert hvr.validate_outcomes(outcomes) is True

    def test_empty_outcomes(self, outcomes: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            hvr.validate_outcomes(outcomes.iloc[0:0])

    def test_missing_column(self, outcomes: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="missing columns"):
            hvr.validate_outcomes(outcomes.drop(columns=["cohort"]))

    def test_negative_count(self, outcomes: pd.DataFrame) -> None:
        outcomes.loc[0, "contact_late"] = -1
        with pytest.raises(NISRAValidationError, match="negative"):
            hvr.validate_outcomes(outcomes)

    def test_non_positive_cohort(self, outcomes: pd.DataFrame) -> None:
        outcomes.loc[0, "cohort"] = 0
        with pytest.raises(NISRAValidationError, match="non-positive"):
            hvr.validate_outcomes(outcomes)

    def test_incomplete_year(self, outcomes: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="expected every review"):
            hvr.validate_outcomes(outcomes[outcomes["review"] != "1_year"])

    def test_trusts_must_sum_to_northern_ireland(self, outcomes: pd.DataFrame) -> None:
        mask = (outcomes["review"] == "new_baby") & (outcomes["trust"] == "Belfast")
        outcomes.loc[mask, ["contact_on_time", "cohort"]] += 1
        with pytest.raises(NISRAValidationError, match="Trust counts sum to"):
            hvr.validate_outcomes(outcomes)

    def test_outcomes_must_sum_to_cohort(self, outcomes: pd.DataFrame) -> None:
        mask = (outcomes["review"] == "new_baby") & (outcomes["trust"] == "Belfast")
        outcomes.loc[mask, "contact_late"] += 1
        outcomes.loc[
            (outcomes["review"] == "new_baby") & (outcomes["trust"] == "Northern Ireland"), "contact_late"
        ] += 1
        with pytest.raises(NISRAValidationError, match="do not sum to the cohort"):
            hvr.validate_outcomes(outcomes)

    def test_valid_quarterly(self, quarterly: pd.DataFrame) -> None:
        assert hvr.validate_quarterly(quarterly) is True

    def test_empty_quarterly(self, quarterly: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            hvr.validate_quarterly(quarterly.iloc[0:0])

    def test_quarterly_missing_column(self, quarterly: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="missing columns"):
            hvr.validate_quarterly(quarterly.drop(columns=["quarter_start"]))

    def test_quarterly_out_of_range(self, quarterly: pd.DataFrame) -> None:
        quarterly.loc[0, "on_time_pct"] = 101.0
        with pytest.raises(NISRAValidationError, match="outside 0-100"):
            hvr.validate_quarterly(quarterly)

    def test_quarterly_missing_review(self, quarterly: pd.DataFrame) -> None:
        with pytest.raises(NISRAValidationError, match="expected"):
            hvr.validate_quarterly(quarterly[quarterly["review"] != "1_year"])

    def test_quarterly_gap(self, quarterly: pd.DataFrame) -> None:
        gap = quarterly[
            ~((quarterly["review"] == "1_year") & (quarterly["quarter_start"] == quarterly["quarter_start"].iloc[8]))
        ]
        with pytest.raises(NISRAValidationError, match="not contiguous"):
            hvr.validate_quarterly(gap)


class TestReleaseResolution:
    """Which release is read: a request for a year never returns a different year."""

    @pytest.fixture
    def site(self, monkeypatch: pytest.MonkeyPatch) -> dict[int, tuple[int, str | None]]:
        """Fake publication pages: year -> (HTTP status, workbook link)."""
        pages: dict[int, tuple[int, str | None]] = {}
        monkeypatch.setattr(hvr, "_page_status", lambda year, force_refresh: pages.get(year, (404, None))[0])
        monkeypatch.setattr(hvr, "_find_workbook_url", lambda url, force_refresh: _link_for(pages, url))
        return pages

    def test_latest_skips_unpublished_years(self, site: dict[int, tuple[int, str | None]]) -> None:
        site[2024] = (200, "https://example.org/24.xlsx")
        site[2023] = (200, "https://example.org/23.xlsx")
        assert hvr._resolve_release(None, False) == (2024, "https://example.org/24.xlsx")

    def test_latest_does_not_fall_back_when_the_newest_page_has_no_workbook(
        self, site: dict[int, tuple[int, str | None]]
    ) -> None:
        site[2025] = (200, None)
        site[2024] = (200, "https://example.org/24.xlsx")
        with pytest.raises(NISRADataNotFoundError, match="2025/26.*links no tables workbook"):
            hvr._resolve_release(None, False)

    def test_explicit_year(self, site: dict[int, tuple[int, str | None]]) -> None:
        site[2022] = (200, "https://example.org/22.xlsx")
        site[2024] = (200, "https://example.org/24.xlsx")
        assert hvr._resolve_release(2022, False) == (2022, "https://example.org/22.xlsx")

    def test_missing_year_raises_and_names_the_year(self, site: dict[int, tuple[int, str | None]]) -> None:
        site[2024] = (200, "https://example.org/24.xlsx")
        with pytest.raises(NISRADataNotFoundError, match="No 2023/24 release found"):
            hvr._resolve_release(2023, False)

    def test_year_before_the_first_supported_release_raises(self, site: dict[int, tuple[int, str | None]]) -> None:
        with pytest.raises(NISRADataNotFoundError, match="first supported release is 2018/19"):
            hvr._resolve_release(2017, False)

    def test_unexpected_status_raises(self, site: dict[int, tuple[int, str | None]]) -> None:
        site[2025] = (403, None)
        with pytest.raises(NISRADataNotFoundError, match="HTTP 403"):
            hvr._resolve_release(None, False)

    def test_no_releases_at_all(self, site: dict[int, tuple[int, str | None]]) -> None:
        with pytest.raises(NISRADataNotFoundError, match="No Healthy Child"):
            hvr._resolve_release(None, False)

    def test_list_publications_is_newest_first(self, site: dict[int, tuple[int, str | None]]) -> None:
        site[2023] = (200, "https://example.org/23.xlsx")
        site[2025] = (200, "https://example.org/25.xlsx")
        site[2024] = (200, None)  # a page with no workbook is left out, not substituted
        df = hvr.list_publications()
        assert df["year"].tolist() == [2025, 2023]
        assert df["financial_year"].tolist() == ["2025/26", "2023/24"]

    def test_list_publications_unexpected_status_raises(self, site: dict[int, tuple[int, str | None]]) -> None:
        site[2025] = (500, None)
        with pytest.raises(NISRADataNotFoundError, match="HTTP 500"):
            hvr.list_publications()


def _link_for(pages: dict[int, tuple[int, str | None]], url: str) -> str | None:
    for year, (_, link) in pages.items():
        if url == hvr._publication_page_url(year):
            return link
    return None


class TestAccessors:
    """The public getters, with the workbook download replaced by a synthetic one."""

    @pytest.fixture
    def fake_release(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[int | None, bool]]:
        calls: list[tuple[int | None, bool]] = []
        workbook = _write(tmp_path / "release.xlsx", _sheets(**LAYOUTS["titled"]))

        def resolve(year: int | None, force_refresh: bool) -> tuple[int, str]:
            calls.append((year, force_refresh))
            return (year if year is not None else 2025), "https://example.org/hchf.xlsx"

        monkeypatch.setattr(hvr, "_resolve_release", resolve)
        monkeypatch.setattr(hvr, "load_workbook", lambda url, download_file, **kwargs: workbook)
        return calls

    def test_outcomes_for_a_year(self, fake_release: list[tuple[int | None, bool]]) -> None:
        df = hvr.get_health_review_outcomes(year=2021)
        assert set(df["year"]) == {2021}
        assert fake_release == [(2021, False)]

    def test_outcomes_default_to_the_newest_release(self, fake_release: list[tuple[int | None, bool]]) -> None:
        assert set(hvr.get_health_review_outcomes(force_refresh=True)["financial_year"]) == {"2025/26"}
        assert fake_release == [(None, True)]

    def test_quarterly_for_a_year(self, fake_release: list[tuple[int | None, bool]]) -> None:
        df = hvr.get_quarterly_on_time(year=2019)
        assert hvr.validate_quarterly(df)

    def test_series_stitches_releases_and_skips_unreadable_ones(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def one_year(year: int, force_refresh: bool = False) -> pd.DataFrame:
            if year == 2023:
                raise NISRAValidationError("layout not recognised")
            return pd.DataFrame(
                {
                    "year": [year] * 2,
                    "review": ["new_baby"] * 2,
                    "trust": ["Belfast", "Northern Ireland"],
                    "cohort": [1, 2],
                }
            )

        monkeypatch.setattr(hvr, "get_health_review_outcomes", one_year)
        monkeypatch.setattr(
            hvr,
            "list_publications",
            lambda force_refresh=False: pd.DataFrame({"year": [2024, 2023, 2022]}),
        )
        with caplog.at_level(logging.WARNING):
            series = hvr.get_health_review_outcomes_series()
        assert sorted(set(series["year"])) == [2022, 2024]
        assert "layout not recognised" in caplog.text

    def test_quarterly_series_keeps_the_newest_release_where_windows_overlap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def one_year(year: int, force_refresh: bool = False) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "year": [2019, 2019],
                    "quarter_start": [pd.Timestamp("2019-04-01")] * 2,
                    "review": ["new_baby", "1_year"],
                    "on_time_pct": [float(year), float(year)],
                }
            )

        monkeypatch.setattr(hvr, "get_quarterly_on_time", one_year)
        monkeypatch.setattr(hvr, "list_publications", lambda force_refresh=False: pd.DataFrame({"year": [2021, 2020]}))
        series = hvr.get_quarterly_on_time_series()
        assert series["on_time_pct"].tolist() == [2021.0, 2021.0]
        assert len(series) == 2

    def test_financial_year_label(self) -> None:
        assert hvr.financial_year_label(2025) == "2025/26"
        assert hvr.financial_year_label(1999) == "1999/00"
