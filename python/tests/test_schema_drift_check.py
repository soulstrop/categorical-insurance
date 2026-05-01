"""Planted-regression tests for the schema-drift asset check (P3.4).

The check (``orchestration.checks._evaluate_schema_drift``) is the
runtime analogue of the CI ``//python:dbt:check-drift`` task: both
read ``catins.dbt.expected_columns(CanonicalProposal)`` as the single
source of truth. These tests verify the check fires correctly on
three classes of drift:

* a column that appeared on the model side but not in the data;
* a column that appeared in the data but not on the model side;
* a column whose dtype no longer maps to the expected SQL type.
"""

import pandas as pd

from catins.orchestration.checks import _evaluate_schema_drift


def _canonical_df() -> pd.DataFrame:
    schema_v1_date = pd.Timestamp("2026-04-30")
    base = {
        "holder_kind": "individual",
        "schema_version": 1,
        "schema_effective_date": schema_v1_date,
        "erased": False,
    }
    return pd.DataFrame(
        [
            {"holder_name": "Alice", "premium": 100.0, "zip_code": "10001", "age": 30, **base},
            {"holder_name": "Bob", "premium": 250.0, "zip_code": "94102", "age": 45, **base},
        ]
    )


def test_passes_on_canonical_dataframe() -> None:
    result = _evaluate_schema_drift(_canonical_df())
    assert result.passed
    assert result.description == "Schema matches CanonicalProposal."


def test_fails_on_missing_column() -> None:
    df = _canonical_df().drop(columns=["age"])
    result = _evaluate_schema_drift(df)
    assert not result.passed
    assert result.description is not None
    assert "missing" in result.description
    assert "age" in result.description


def test_fails_on_extra_column() -> None:
    df = _canonical_df().assign(extraneous=["x", "y"])
    result = _evaluate_schema_drift(df)
    assert not result.passed
    assert result.description is not None
    assert "extra" in result.description
    assert "extraneous" in result.description


def test_fails_on_type_mismatch() -> None:
    """An age column inferred as float (DOUBLE) drifts from INTEGER."""
    df = _canonical_df().assign(age=lambda d: d["age"].astype("float64"))
    result = _evaluate_schema_drift(df)
    assert not result.passed
    assert result.description is not None
    assert "type mismatches" in result.description
    assert "age" in result.description
    assert "DOUBLE" in result.description
    assert "INTEGER" in result.description


def test_distinguishes_drift_kinds_in_description() -> None:
    """A simultaneous missing + extra + type-mismatch surfaces all three."""
    df = (
        _canonical_df()
        .drop(columns=["age"])
        .assign(extraneous=["x", "y"])
        .assign(premium=lambda d: d["premium"].astype("int64"))
    )
    result = _evaluate_schema_drift(df)
    assert not result.passed
    assert result.description is not None
    assert "missing" in result.description
    assert "extra" in result.description
    assert "type mismatches" in result.description
