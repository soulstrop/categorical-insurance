"""Tests for the WarehouseSession protocol and DuckDBSession mock."""

import pandas as pd
import pyarrow as pa

from catins.warehouse import DuckDBSession, WarehouseSession


def test_duckdb_session_implements_protocol() -> None:
    session = DuckDBSession()
    assert isinstance(session, WarehouseSession)


def test_round_trip_dataframe() -> None:
    session = DuckDBSession()
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    session.write_table(df, "fixture")
    out = session.read_table("fixture")
    assert sorted(out["a"].tolist()) == [1, 2, 3]
    assert sorted(out["b"].tolist()) == ["x", "y", "z"]


def test_append_mode() -> None:
    session = DuckDBSession()
    session.write_table(pd.DataFrame({"a": [1]}), "t", mode="overwrite")
    session.write_table(pd.DataFrame({"a": [2]}), "t", mode="append")
    out = session.read_table("t")
    assert sorted(out["a"].tolist()) == [1, 2]


def test_register_pandas_udf() -> None:
    session = DuckDBSession()

    def double(col: pa.ChunkedArray) -> pa.ChunkedArray:
        return pa.compute.multiply(col, 2)

    session.register_udf(
        "double_it",
        double,
        param_types=["BIGINT"],
        return_type="BIGINT",
    )
    session.write_table(pd.DataFrame({"x": [1, 2, 3]}), "src")
    result = session.sql("SELECT double_it(x) AS y FROM src ORDER BY x")
    assert result["y"].tolist() == [2, 4, 6]
