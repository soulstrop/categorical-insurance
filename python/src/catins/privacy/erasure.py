"""Right-to-erasure operation per ADR 007 §1, §4, §6.

# math: math.tex §VI (Visibility worked instance)

A request to erase ``(table, where_column = where_value)`` performs:

1. **Idempotency check** (§6) — consult ``_audit_erasures`` for a prior
   request with the same ``(table, where_column, where_value)``
   tuple; if found, return ``already_erased=True`` without touching
   the row again. The audit table is the source of truth for "has
   this erasure happened" — robust to PII nulling, which destroys the
   in-row evidence.
2. **Pre-erasure snapshot** — read the current row state into an
   immutable record before any change.
3. **Tombstone-with-PII-null** (§1) — issue
   ``UPDATE table SET <pii_field> = NULL, ..., erased = TRUE WHERE …``
   to null every PII-annotated column on ``model_cls`` and set the
   ``erased`` tombstone marker.
4. **Audit log** (§4) — INSERT into ``_audit_erasures`` with the
   snapshot, the operator identity, the reason, and the list of fields
   nulled.

This module contains no Vault interaction; tokenisation + erasure
compose orthogonally (a tokenised row's tombstone nulls the token,
the audit captures the token; the plaintext is recoverable via Vault
detokenisation against the audit row's snapshot if needed).

SQL injection: ``table`` and ``where_column`` are validated as bare
identifiers (alphanumerics + underscore); ``where_value`` is single-
quote-escaped. Production callers should use parameter binding
instead — this is the test-tier approach.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

import pandas as pd
from pydantic import BaseModel

from catins.privacy.pii import pii_fields
from catins.warehouse import WarehouseSession

AUDIT_TABLE = "_audit_erasures"

AUDIT_ERASURES_DDL = f"""
CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
    erasure_id            VARCHAR PRIMARY KEY,
    erased_at             TIMESTAMP,
    erased_by             VARCHAR,
    table_name            VARCHAR,
    where_column          VARCHAR,
    where_value           VARCHAR,
    reason                VARCHAR,
    pii_fields_nulled     VARCHAR,
    pre_erasure_snapshot  VARCHAR
);
"""


def init_audit_table(session: WarehouseSession) -> None:
    """Create ``_audit_erasures`` if it doesn't exist."""
    session.sql(AUDIT_ERASURES_DDL)


@dataclass(frozen=True)
class ErasureResult:
    """Outcome of an erasure call."""

    erasure_id: str
    table_name: str
    where_column: str
    where_value: str
    already_erased: bool
    pii_fields_nulled: list[str]


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(label: str, value: str) -> None:
    if not _IDENTIFIER_PATTERN.match(value):
        msg = f"{label} is not a valid SQL identifier: {value!r}"
        raise ValueError(msg)


def _sql_string_literal(value: str) -> str:
    """Single-quoted SQL string literal with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def _existing_erasure_id(
    session: WarehouseSession,
    *,
    table_name: str,
    where_column: str,
    where_value: str,
) -> str | None:
    """The audit row's id if this erasure has happened before, else None."""
    df = session.sql(
        f"SELECT erasure_id FROM {AUDIT_TABLE} "
        f"WHERE table_name = {_sql_string_literal(table_name)} "
        f"AND where_column = {_sql_string_literal(where_column)} "
        f"AND where_value = {_sql_string_literal(where_value)} "
        f"ORDER BY erased_at LIMIT 1"
    )
    if df.empty:
        return None
    return str(df["erasure_id"].iloc[0])


def erase(
    session: WarehouseSession,
    *,
    table: str,
    where_column: str,
    where_value: str,
    model_cls: type[BaseModel],
    erased_by: str,
    reason: str,
) -> ErasureResult:
    """Erase the row matching ``where_column = where_value`` in ``table``.

    Idempotent: a second call with the same ``(table, where_column,
    where_value)`` tuple returns ``ErasureResult(already_erased=True,
    pii_fields_nulled=[])`` without modifying the row or appending to
    the audit table.

    Raises ``LookupError`` if no row matches and no prior audit entry
    exists. Raises ``ValueError`` if ``table`` or ``where_column`` is
    not a valid identifier.
    """
    _validate_identifier("table", table)
    _validate_identifier("where_column", where_column)

    # Idempotency: prior erasure of the same subject is the no-op path.
    prior_id = _existing_erasure_id(
        session, table_name=table, where_column=where_column, where_value=where_value
    )
    if prior_id is not None:
        return ErasureResult(
            erasure_id=prior_id,
            table_name=table,
            where_column=where_column,
            where_value=where_value,
            already_erased=True,
            pii_fields_nulled=[],
        )

    # Read the row to snapshot its pre-erasure state.
    row_df = session.sql(
        f"SELECT * FROM {table} WHERE {where_column} = {_sql_string_literal(where_value)}"
    )
    if row_df.empty:
        msg = f"row not found: {table}.{where_column} = {where_value!r}"
        raise LookupError(msg)
    snapshot = json.dumps(row_df.iloc[0].to_dict(), default=str)

    # Identify PII columns from the model's annotations.
    pii = sorted(pii_fields(model_cls).keys())
    set_clauses = [f"{name} = NULL" for name in pii]
    set_clauses.append("erased = TRUE")

    session.sql(
        f"UPDATE {table} SET {', '.join(set_clauses)} "
        f"WHERE {where_column} = {_sql_string_literal(where_value)}"
    )

    erasure_id = str(uuid.uuid4())
    audit_df = pd.DataFrame(
        [
            {
                "erasure_id": erasure_id,
                "erased_at": pd.Timestamp.now(),
                "erased_by": erased_by,
                "table_name": table,
                "where_column": where_column,
                "where_value": where_value,
                "reason": reason,
                "pii_fields_nulled": json.dumps(pii),
                "pre_erasure_snapshot": snapshot,
            }
        ]
    )
    session.write_table(audit_df, AUDIT_TABLE, mode="append")

    return ErasureResult(
        erasure_id=erasure_id,
        table_name=table,
        where_column=where_column,
        where_value=where_value,
        already_erased=False,
        pii_fields_nulled=pii,
    )
