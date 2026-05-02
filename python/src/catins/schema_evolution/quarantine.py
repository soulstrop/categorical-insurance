"""Quarantine landing per ADR 008 §5.

# math: math.tex §VII.B

Persists ``QuarantineRow`` instances into the warehouse-side
``raw_quarantine`` table. The dbt model ``models/raw/raw_quarantine``
is a thin projection over this table; the Phase 3 ``quarantine_check``
(P3.8) reads through that projection and fails when the latest
partition is non-empty.

The DDL is co-located with the writer for the same reason as
``catins.privacy.erasure.AUDIT_ERASURES_DDL``: the producer owns the
schema, not dbt — dbt sees the table as an external source.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable

import pandas as pd

from catins.schema_evolution.dispatch import QuarantineRow
from catins.warehouse import WarehouseSession

RAW_QUARANTINE_TABLE = "raw_quarantine"

RAW_QUARANTINE_DDL = f"""
CREATE TABLE IF NOT EXISTS {RAW_QUARANTINE_TABLE} (
    quarantine_id        VARCHAR PRIMARY KEY,
    quarantined_at       TIMESTAMP,
    schema_version_seen  INTEGER,
    reason               VARCHAR,
    detail               VARCHAR,
    raw_payload          VARCHAR
);
"""


def init_quarantine_table(session: WarehouseSession) -> None:
    """Create ``raw_quarantine`` if it doesn't exist."""
    session.sql(RAW_QUARANTINE_DDL)


def write_quarantine_rows(
    session: WarehouseSession,
    rows: Iterable[QuarantineRow],
) -> int:
    """Persist a batch of ``QuarantineRow`` instances; return the count.

    No-op (returns 0) when ``rows`` is empty — append-mode writes of
    empty DataFrames are a no-op on the DuckDB backend, but the early
    return keeps the call site explicit.
    """
    payloads = []
    for row in rows:
        payloads.append(
            {
                "quarantine_id": str(uuid.uuid4()),
                "quarantined_at": pd.Timestamp.now(),
                "schema_version_seen": row.schema_version_seen,
                "reason": row.reason,
                "detail": row.detail,
                "raw_payload": json.dumps(row.raw_payload, default=str),
            }
        )
    if not payloads:
        return 0

    init_quarantine_table(session)
    session.write_table(pd.DataFrame(payloads), RAW_QUARANTINE_TABLE, mode="append")
    return len(payloads)
