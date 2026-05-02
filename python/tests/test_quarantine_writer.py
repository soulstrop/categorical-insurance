"""Tests for the raw_quarantine warehouse writer (P2R.11).

The writer is the bridge between ``catins.schema_evolution.parse_proposal``
(Python) and the dbt ``models/raw/raw_quarantine`` projection. We
test against an in-process DuckDB ``WarehouseSession`` rather than
mocks because the Pandas / DuckDB type-coercion behaviour is part of
what we want under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from catins.schema_evolution import (
    DEFAULT_REGISTRY,
    QuarantineRow,
    parse_proposal,
)
from catins.schema_evolution.quarantine import (
    RAW_QUARANTINE_TABLE,
    init_quarantine_table,
    write_quarantine_rows,
)
from catins.warehouse import WarehouseSession


class _DuckDBSession:
    """Minimal WarehouseSession over an in-process DuckDB connection.

    Only the subset of the Protocol the writer touches: ``sql`` and
    ``write_table``.
    """

    def __init__(self, path: Path) -> None:
        self._conn = duckdb.connect(str(path))

    def sql(self, query: str):  # type: ignore[no-untyped-def]
        return self._conn.execute(query).df()

    def register_udf(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def write_table(self, df, name: str, mode: str = "overwrite") -> None:  # type: ignore[no-untyped-def]
        self._conn.register("__buf", df)
        if mode == "append":
            self._conn.execute(f"INSERT INTO {name} SELECT * FROM __buf")
        else:
            self._conn.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM __buf")

    def read_table(self, name: str):  # type: ignore[no-untyped-def]
        return self._conn.execute(f"SELECT * FROM {name}").df()

    def close(self) -> None:
        self._conn.close()


@pytest.fixture
def session(tmp_path: Path):  # type: ignore[no-untyped-def]
    s = _DuckDBSession(tmp_path / "catins.duckdb")
    yield s
    s.close()


def _check_protocol(session: _DuckDBSession) -> None:
    # Minimal type-check that our test session satisfies the seam.
    assert isinstance(session, WarehouseSession)


def test_init_quarantine_table_creates_table(session: _DuckDBSession) -> None:
    _check_protocol(session)
    init_quarantine_table(session)
    df = session.sql(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{RAW_QUARANTINE_TABLE}'"
    )
    assert set(df["column_name"].tolist()) == {
        "quarantine_id",
        "quarantined_at",
        "schema_version_seen",
        "reason",
        "detail",
        "raw_payload",
    }


def test_init_is_idempotent(session: _DuckDBSession) -> None:
    init_quarantine_table(session)
    init_quarantine_table(session)
    df = session.sql(f"SELECT count(*) AS n FROM {RAW_QUARANTINE_TABLE}")
    assert int(df["n"].iloc[0]) == 0


def test_write_empty_iterable_is_noop(session: _DuckDBSession) -> None:
    n = write_quarantine_rows(session, [])
    assert n == 0
    # No DDL ran either — the table should not exist.
    df = session.sql(
        f"SELECT count(*) AS n FROM information_schema.tables "
        f"WHERE table_name = '{RAW_QUARANTINE_TABLE}'"
    )
    assert int(df["n"].iloc[0]) == 0


def test_write_rows_persists_payload(session: _DuckDBSession) -> None:
    rows = [
        QuarantineRow(
            raw_payload={"holder_name": "Alice", "schema_version": 99},
            reason="unknown schema version",
            schema_version_seen=99,
            detail="known versions: [1]",
        ),
        QuarantineRow(
            raw_payload={"holder_name": "Bob"},
            reason="missing schema_version",
        ),
    ]
    n = write_quarantine_rows(session, rows)
    assert n == 2
    df = session.sql(
        f"SELECT reason, schema_version_seen, raw_payload "
        f"FROM {RAW_QUARANTINE_TABLE} ORDER BY reason"
    )
    assert df["reason"].tolist() == ["missing schema_version", "unknown schema version"]
    # schema_version_seen NULL for the missing-version row, 99 for the unknown-version row.
    # DuckDB / pandas may return either pd.NA, None, or NaN for the null;
    # ``pd.isna`` handles all three uniformly.
    versions_clean = [None if pd.isna(v) else int(v) for v in df["schema_version_seen"].tolist()]
    assert versions_clean == [None, 99]
    payloads = [json.loads(p) for p in df["raw_payload"].tolist()]
    assert payloads[0] == {"holder_name": "Bob"}
    assert payloads[1] == {"holder_name": "Alice", "schema_version": 99}


def test_dispatch_failures_round_trip_through_writer(session: _DuckDBSession) -> None:
    """End-to-end: parse_proposal failures land verbatim in the writer's table."""
    rows = [
        {"holder_name": "Alice"},  # missing schema_version
        {"holder_name": "Bob", "schema_version": 99},  # unknown version
        # Validation-failure: known v1, but missing required fields
        {"schema_version": 1, "holder_name": "Carol"},
    ]
    quarantined = []
    for row in rows:
        result = parse_proposal(row, DEFAULT_REGISTRY)
        if isinstance(result, QuarantineRow):
            quarantined.append(result)
    assert len(quarantined) == 3
    n = write_quarantine_rows(session, quarantined)
    assert n == 3

    df = session.sql(f"SELECT reason FROM {RAW_QUARANTINE_TABLE} ORDER BY reason")
    assert df["reason"].tolist() == [
        "missing schema_version",
        "unknown schema version",
        "validation failed",
    ]
