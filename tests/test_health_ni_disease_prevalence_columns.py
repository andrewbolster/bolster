"""Offline tests: PxStat dimension labels are matched regardless of letter case."""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import disease_prevalence as dp
from bolster.data_sources.health_ni._base import NISRADataNotFoundError


def _raw(fy_label: str = "Financial Year", extra: dict | None = None) -> pd.DataFrame:
    rows = []
    for fy in ("2023/24", "2024/25"):
        for disease, reg, prev in (("Asthma", 1000.0, 50.0), ("Diabetes", 400.0, 20.0)):
            rows.append({"STATISTIC": "Numreg", fy_label: fy, "Disease": disease, "VALUE": reg, **(extra or {})})
            rows.append(
                {"STATISTIC": "Rawprevalence1000", fy_label: fy, "Disease": disease, "VALUE": prev, **(extra or {})}
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("label", ["Financial Year", "Financial year", "FINANCIAL YEAR", "financial year"])
def test_resolve_column_ignores_case(label):
    raw = _raw(fy_label=label)
    assert dp._resolve_column(raw, "Financial Year") == label


def test_resolve_column_missing_names_label_and_columns():
    raw = _raw()
    with pytest.raises(NISRADataNotFoundError) as exc:
        dp._resolve_column(raw, "Fiscal Quarter")
    message = str(exc.value)
    assert "Fiscal Quarter" in message
    assert "Financial Year" in message


@pytest.mark.parametrize("label", ["Financial Year", "Financial year"])
def test_pivot_gives_identical_output_for_either_label_case(label):
    raw = _raw(fy_label=label, extra={"Local Government District": "Belfast"})
    out = dp._pivot_prevalence(raw, group_col="Local Government District", output_col="lgd")
    assert list(out.columns) == [
        "financial_year",
        "year",
        "lgd",
        "disease",
        "registered_patients",
        "prevalence_per_1000",
    ]
    assert sorted(out["year"].unique()) == [2023, 2024]
    assert out["registered_patients"].tolist() == [1000.0, 400.0, 1000.0, 400.0]


def test_pivot_geography_column_is_matched_case_insensitively():
    raw = _raw(extra={"local government district": "Belfast"})
    out = dp._pivot_prevalence(raw, group_col="Local Government District", output_col="lgd")
    assert set(out["lgd"]) == {"Belfast"}
