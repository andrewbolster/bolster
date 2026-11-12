"""Data integrity tests for the NISRA public expenditure module."""

import io

import pandas as pd
import pytest

from bolster.data_sources.nisra import public_expenditure as pe
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError


def _good_df() -> pd.DataFrame:
    """Minimal frame that passes validation, for mutating in unit tests."""
    return pd.DataFrame(
        {
            "financial_year": ["2023/24", "2024/25", "2024/25"],
            "year_start": [2023, 2024, 2024],
            "department": ["DoH", "DoH", "DoH"],
            "spending_area_code": ["DoH01", "DoH01", "DoH01"],
            "spending_area": ["Hospital services"] * 3,
            "expenditure_category": ["Capital DEL", "Capital DEL", "Non Ringfenced Resource DEL"],
            "spend_gbp_thousands": [100.0, 110.0, 5000.0],
            "provisional": [False, False, False],
        }
    )


class TestFinalOutturnIntegrity:
    @pytest.fixture(scope="class")
    def data(self):
        return pe.get_latest_data()

    def test_required_columns(self, data):
        assert list(data.columns) == pe.COLUMNS

    def test_no_provisional_rows_by_default(self, data):
        assert not data["provisional"].any()

    def test_historical_coverage(self, data):
        years = sorted(data["financial_year"].unique())
        assert years[0] == "2016/17"
        assert len(years) >= 9

    def test_financial_years_are_contiguous(self, data):
        starts = sorted(data["year_start"].unique())
        assert starts == list(range(starts[0], starts[-1] + 1))

    def test_every_year_has_every_department(self, data):
        per_year = data.groupby("financial_year")["department"].nunique()
        assert per_year.min() == per_year.max()

    def test_known_categories_only(self, data):
        assert set(data["expenditure_category"]) <= pe.EXPENDITURE_CATEGORIES

    def test_area_codes_present_and_stable(self, data):
        assert data["spending_area_code"].notna().all()
        codes_per_area = data.groupby(["department", "spending_area"])["spending_area_code"].nunique()
        assert (codes_per_area == 1).all()

    def test_no_duplicate_keys(self, data):
        assert not data.duplicated(["financial_year", "department", "spending_area", "expenditure_category"]).any()

    def test_values_are_plausible(self, data):
        totals = data.groupby("year_start")["spend_gbp_thousands"].sum()
        assert totals.between(1e7, 1e8).all()  # £10bn-£100bn in £ thousands

    def test_validate_passes(self, data):
        assert pe.validate_data(data) is True

    def test_department_totals_match_detail(self, data):
        totals = pe.get_department_totals()
        assert totals["spend_gbp_thousands"].sum() == pytest.approx(data["spend_gbp_thousands"].sum())


class TestProvisionalYear:
    @pytest.fixture(scope="class")
    def with_provisional(self):
        return pe.get_latest_data(include_provisional=True)

    @pytest.fixture(scope="class")
    def final(self):
        return pe.get_latest_data()

    def test_provisional_rows_are_only_the_newest_year(self, with_provisional, final):
        provisional = with_provisional[with_provisional["provisional"]]
        if provisional.empty:
            pytest.skip("PxStat already holds the newest year; no provisional rows remain")
        assert provisional["year_start"].nunique() == 1
        assert provisional["year_start"].iloc[0] > final["year_start"].max()

    def test_final_rows_are_unchanged_by_including_provisional(self, with_provisional, final):
        final_part = with_provisional[~with_provisional["provisional"]].reset_index(drop=True)
        pd.testing.assert_frame_equal(final_part, final)


class TestCrossValidation:
    """PxStat and the dashboard workbook are separate publications of the same figures."""

    @pytest.fixture(scope="class")
    def final(self):
        return pe.get_latest_data()

    @pytest.fixture(scope="class")
    def dashboard(self):
        return pe.get_dashboard_data()

    def test_overlapping_years_agree_row_for_row(self, final, dashboard):
        key = ["financial_year", "department", "spending_area", "expenditure_category"]
        overlap = dashboard[dashboard["financial_year"].isin(final["financial_year"])]
        merged = overlap.merge(final, on=key, how="outer", suffixes=("_dash", "_px"), indicator=True)

        both = merged[merged["_merge"] == "both"]
        assert len(both) == len(final)
        assert (both["spend_gbp_thousands_dash"] - both["spend_gbp_thousands_px"]).abs().max() < 0.5

        # The workbook also lists cells PxStat leaves empty; those must be zero.
        only_dash = merged[merged["_merge"] == "left_only"]
        assert (only_dash["spend_gbp_thousands_dash"] == 0).all()
        assert not (merged["_merge"] == "right_only").any()

    def test_hospital_services_2024_25(self, final, dashboard):
        def total(frame: pd.DataFrame) -> float:
            rows = frame[
                (frame["financial_year"] == "2024/25")
                & (frame["department"] == "DoH")
                & (frame["spending_area"] == "Hospital services")
            ]
            return float(rows["spend_gbp_thousands"].sum())

        assert total(final) == total(dashboard) == 5_271_473.0

    def test_dashboard_marks_exactly_one_provisional_year(self, dashboard):
        assert dashboard.loc[dashboard["provisional"], "year_start"].nunique() == 1


class TestValidation:
    def test_good_frame_passes(self):
        assert pe.validate_data(_good_df()) is True

    def test_empty_frame_fails(self):
        with pytest.raises(NISRAValidationError, match="No public expenditure rows"):
            pe.validate_data(_good_df().iloc[0:0])

    def test_missing_column_fails(self):
        with pytest.raises(NISRAValidationError, match="Missing columns"):
            pe.validate_data(_good_df().drop(columns=["department"]))

    def test_negative_spend_is_allowed(self):
        df = _good_df()
        df.loc[0, "spend_gbp_thousands"] = -2594.0
        assert pe.validate_data(df) is True

    def test_non_finite_spend_fails(self):
        df = _good_df()
        df.loc[0, "spend_gbp_thousands"] = float("nan")
        with pytest.raises(NISRAValidationError, match="non-finite"):
            pe.validate_data(df)

    def test_unknown_category_fails(self):
        df = _good_df()
        df.loc[0, "expenditure_category"] = "Mystery"
        with pytest.raises(NISRAValidationError, match="Unexpected expenditure categories"):
            pe.validate_data(df)

    def test_duplicate_rows_fail(self):
        df = pd.concat([_good_df(), _good_df().iloc[[0]]], ignore_index=True)
        with pytest.raises(NISRAValidationError, match="Duplicate rows"):
            pe.validate_data(df)

    def test_year_start_must_match_label(self):
        df = _good_df()
        df.loc[0, "year_start"] = 2019
        with pytest.raises(NISRAValidationError, match="does not match"):
            pe.validate_data(df)

    def test_provisional_must_be_latest_year(self):
        df = _good_df()
        df.loc[0, "provisional"] = True
        with pytest.raises(NISRAValidationError, match="latest financial year"):
            pe.validate_data(df)

    def test_missing_area_code_only_allowed_when_provisional(self):
        df = _good_df()
        df.loc[2, "spending_area_code"] = None
        with pytest.raises(NISRAValidationError, match="no spending area code"):
            pe.validate_data(df)
        df.loc[2, "provisional"] = True
        assert pe.validate_data(df) is True


class TestParsingHelpers:
    def test_split_area_label(self):
        assert pe._split_area_label("Hospital services (DoH)") == ("Hospital services", "DoH")

    def test_split_area_label_keeps_inner_brackets(self):
        assert pe._split_area_label("Grants (capital) (DfC)") == ("Grants (capital)", "DfC")

    def test_split_area_label_fixes_spelling(self):
        assert pe._split_area_label("NI Civil Service accomodation services (DoF)")[0] == (
            "NI Civil Service accommodation services"
        )

    def test_split_area_label_without_department_fails(self):
        with pytest.raises(NISRAValidationError, match="no '\\(department\\)' suffix"):
            pe._split_area_label("Hospital services")

    @pytest.mark.parametrize("value", ["2025-26", "2025/26"])
    def test_normalise_year(self, value):
        assert pe._normalise_year(value) == ("2025/26", 2025)

    @pytest.mark.parametrize("value", ["2025", "2025-27", "FY25", "2025/2026"])
    def test_normalise_year_rejects(self, value):
        with pytest.raises(NISRAValidationError):
            pe._normalise_year(value)


def _workbook_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    return buffer.getvalue()


def _detail_sheet(extra_header: list[str] | None = None, rows: list[list] | None = None) -> pd.DataFrame:
    header = ["Department", "Spending Area", "Expenditure Category", "Year", "Spend (£millions)", "Spend (£000s)"]
    body = rows if rows is not None else [["DoH", "Hospital services", "Capital DEL", "2025-26", 1.5, 1500]]
    lines: list[list] = [
        ["Table 4: More detailed data", None, None, None, None, None],
        [
            "The 2025-26 data is based on provisional outturn data. All previous years are final.",
            None,
            None,
            None,
            None,
            None,
        ],
        header if extra_header is None else extra_header,
        *body,
    ]
    return pd.DataFrame(lines)


class TestWorkbookParsing:
    """The dashboard reader, fed hand-built workbooks (no network)."""

    @pytest.fixture
    def serve(self, monkeypatch):
        """Make the dashboard fetch return a page embedding the given workbook bytes."""
        import base64

        class _Response:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        def install(content: bytes | None):
            if content is None:
                html = "<html></html>"
            else:
                mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                payload = base64.b64encode(content).decode()
                html = f'<a download="Download data (.xlsx, 1KB)" href="data:{mime};base64,{payload}">x</a>'
            monkeypatch.setattr(pe.session, "get", lambda *a, **k: _Response(html))

        return install

    def test_reads_detail_sheet_and_flags_provisional(self, serve):
        serve(_workbook_bytes({"Cover": pd.DataFrame([["x"]]), "Table_4": _detail_sheet()}))
        df = pe.get_dashboard_data()
        assert df["financial_year"].tolist() == ["2025/26"]
        assert df["spend_gbp_thousands"].tolist() == [1500.0]
        assert df["provisional"].tolist() == [True]

    def test_finds_the_detail_sheet_by_title_not_position(self, serve):
        other = pd.DataFrame([["Table 3: Data used in dashboard"], ["Department"], ["DoH"]])
        serve(_workbook_bytes({"A": _detail_sheet(), "B": other}))
        assert len(pe.get_dashboard_data()) == 1

    def test_no_embedded_workbook_raises(self, serve):
        serve(None)
        with pytest.raises(NISRADataNotFoundError, match="No embedded workbook"):
            pe.get_dashboard_data()

    def test_missing_detail_table_raises(self, serve):
        serve(_workbook_bytes({"Cover": pd.DataFrame([["Cover sheet"]])}))
        with pytest.raises(NISRADataNotFoundError, match="more detailed data"):
            pe.get_dashboard_data()

    def test_missing_column_raises(self, serve):
        header = ["Department", "Spending Area", "Expenditure Category", "Year", "Spend (£millions)"]
        sheet = _detail_sheet(
            extra_header=header + [None], rows=[["DoH", "Hospital services", "Capital DEL", "2025-26", 1.5, None]]
        )
        serve(_workbook_bytes({"Table_4": sheet}))
        with pytest.raises(NISRADataNotFoundError, match="lacks columns"):
            pe.get_dashboard_data()

    def test_non_numeric_spend_raises(self, serve):
        sheet = _detail_sheet(rows=[["DoH", "Hospital services", "Capital DEL", "2025-26", 1.5, "n/a"]])
        serve(_workbook_bytes({"Table_4": sheet}))
        with pytest.raises(NISRAValidationError, match="not numeric"):
            pe.get_dashboard_data()

    def test_provisional_rows_need_a_year_pxstat_lacks(self, monkeypatch, serve):
        """When PxStat already holds the dashboard's provisional year, nothing is appended."""
        serve(_workbook_bytes({"Table_4": _detail_sheet()}))
        final = _good_df()
        final.loc[:, "financial_year"] = "2025/26"
        final.loc[:, "year_start"] = 2025
        final = final.drop_duplicates(["expenditure_category"])
        monkeypatch.setattr(pe, "_read_pxstat", lambda: final)
        result = pe.get_latest_data(include_provisional=True)
        assert not result["provisional"].any()

    def test_provisional_rows_are_appended_and_coded_where_known(self, monkeypatch, serve):
        rows = [
            ["DoH", "Hospital services", "Capital DEL", "2025-26", 1.5, 1500],
            ["DoH", "Brand new area", "Capital DEL", "2025-26", 2.0, 2000],
        ]
        serve(_workbook_bytes({"Table_4": _detail_sheet(rows=rows)}))
        monkeypatch.setattr(pe, "_read_pxstat", lambda: _good_df())
        result = pe.get_latest_data(include_provisional=True)
        provisional = result[result["provisional"]].set_index("spending_area")
        assert provisional.loc["Hospital services", "spending_area_code"] == "DoH01"
        assert pd.isna(provisional.loc["Brand new area", "spending_area_code"])
        assert provisional["financial_year"].unique().tolist() == ["2025/26"]
