"""Tests for the right-to-erasure operation (P2R.8).

Covers ADR 007 §1 (tombstone-with-PII-null), §4 (audit table), and §6
(idempotency). Exercised against a real DuckDBSession with a seeded
``stg_proposals`` table.
"""

import json

import pandas as pd
import pytest

from catins.models import SCHEMA_V1_EFFECTIVE_DATE, CanonicalProposal
from catins.privacy import (
    AUDIT_TABLE,
    ErasureResult,
    erase,
    init_audit_table,
)
from catins.warehouse import DuckDBSession


def _seeded_session() -> DuckDBSession:
    """A DuckDB session with stg_proposals + the audit table set up."""
    s = DuckDBSession()
    schema_v1 = pd.Timestamp(SCHEMA_V1_EFFECTIVE_DATE)
    s.write_table(
        pd.DataFrame(
            [
                {
                    "holder_kind": "individual",
                    "holder_name": "Alice",
                    "premium": 100.0,
                    "zip_code": "10001",
                    "age": 30,
                    "schema_version": 1,
                    "schema_effective_date": schema_v1,
                    "erased": False,
                },
                {
                    "holder_kind": "individual",
                    "holder_name": "Bob",
                    "premium": 250.0,
                    "zip_code": "94102",
                    "age": 45,
                    "schema_version": 1,
                    "schema_effective_date": schema_v1,
                    "erased": False,
                },
            ]
        ),
        "stg_proposals",
    )
    init_audit_table(s)
    return s


def _erase_alice(session: DuckDBSession) -> ErasureResult:
    return erase(
        session,
        table="stg_proposals",
        where_column="holder_name",
        where_value="Alice",
        model_cls=CanonicalProposal,
        erased_by="operator-x",
        reason="customer request",
    )


# --- §1 tombstone-with-PII-null ---


def test_erasure_nulls_pii_columns_only() -> None:
    s = _seeded_session()
    _erase_alice(s)
    rows = s.sql("SELECT * FROM stg_proposals WHERE premium = 100.0")
    assert len(rows) == 1
    row = rows.iloc[0]
    # PII fields nulled:
    assert pd.isna(row["holder_name"])
    assert pd.isna(row["zip_code"])
    assert pd.isna(row["age"])
    # Non-PII preserved:
    assert row["holder_kind"] == "individual"
    assert row["premium"] == 100.0
    assert row["schema_version"] == 1
    # Tombstone marker set:
    assert bool(row["erased"]) is True


def test_erasure_does_not_touch_other_rows() -> None:
    s = _seeded_session()
    _erase_alice(s)
    bob = s.sql("SELECT * FROM stg_proposals WHERE premium = 250.0").iloc[0]
    assert bob["holder_name"] == "Bob"
    assert bob["zip_code"] == "94102"
    assert bob["age"] == 45
    assert bool(bob["erased"]) is False


def test_erasure_returns_pii_fields_nulled() -> None:
    s = _seeded_session()
    result = _erase_alice(s)
    assert not result.already_erased
    # Sorted alphabetically per the implementation.
    assert result.pii_fields_nulled == ["age", "holder_name", "zip_code"]
    assert result.erasure_id  # non-empty UUID


# --- §4 audit table ---


def test_audit_table_records_the_erasure() -> None:
    s = _seeded_session()
    result = _erase_alice(s)
    audit = s.sql(f"SELECT * FROM {AUDIT_TABLE} WHERE erasure_id = '{result.erasure_id}'")
    assert len(audit) == 1
    audit_row = audit.iloc[0]
    assert audit_row["erased_by"] == "operator-x"
    assert audit_row["reason"] == "customer request"
    assert audit_row["table_name"] == "stg_proposals"
    assert audit_row["where_column"] == "holder_name"
    assert audit_row["where_value"] == "Alice"


def test_audit_table_captures_pre_erasure_snapshot() -> None:
    s = _seeded_session()
    result = _erase_alice(s)
    audit = s.sql(
        f"SELECT pre_erasure_snapshot FROM {AUDIT_TABLE} WHERE erasure_id = '{result.erasure_id}'"
    )
    snapshot = json.loads(audit.iloc[0]["pre_erasure_snapshot"])
    # Snapshot taken BEFORE the UPDATE — so it has the plaintext PII.
    assert snapshot["holder_name"] == "Alice"
    assert snapshot["zip_code"] == "10001"
    assert snapshot["age"] == 30
    assert snapshot["erased"] is False


def test_audit_table_records_pii_fields_nulled() -> None:
    s = _seeded_session()
    result = _erase_alice(s)
    audit = s.sql(
        f"SELECT pii_fields_nulled FROM {AUDIT_TABLE} WHERE erasure_id = '{result.erasure_id}'"
    )
    nulled = json.loads(audit.iloc[0]["pii_fields_nulled"])
    assert nulled == ["age", "holder_name", "zip_code"]


# --- §6 idempotency ---


def test_second_erasure_is_idempotent() -> None:
    s = _seeded_session()
    first = _erase_alice(s)
    second = _erase_alice(s)
    assert second.already_erased
    # The same audit row id is returned on the idempotent call.
    assert second.erasure_id == first.erasure_id
    assert second.pii_fields_nulled == []


def test_idempotent_second_call_does_not_append_audit_row() -> None:
    s = _seeded_session()
    _erase_alice(s)
    _erase_alice(s)
    n = s.sql(f"SELECT COUNT(*) AS n FROM {AUDIT_TABLE}").iloc[0]["n"]
    assert n == 1


# --- error paths ---


def test_erasure_of_missing_row_raises() -> None:
    s = _seeded_session()
    with pytest.raises(LookupError, match="row not found"):
        erase(
            s,
            table="stg_proposals",
            where_column="holder_name",
            where_value="Eve",
            model_cls=CanonicalProposal,
            erased_by="x",
            reason="y",
        )


def test_invalid_table_identifier_rejected() -> None:
    s = _seeded_session()
    with pytest.raises(ValueError, match="not a valid SQL identifier"):
        erase(
            s,
            table="stg_proposals; DROP TABLE x",
            where_column="holder_name",
            where_value="Alice",
            model_cls=CanonicalProposal,
            erased_by="x",
            reason="y",
        )


def test_invalid_where_column_rejected() -> None:
    s = _seeded_session()
    with pytest.raises(ValueError, match="not a valid SQL identifier"):
        erase(
            s,
            table="stg_proposals",
            where_column="holder_name; DROP TABLE x",
            where_value="Alice",
            model_cls=CanonicalProposal,
            erased_by="x",
            reason="y",
        )


def test_where_value_with_quote_is_escaped_not_executed() -> None:
    """SQL injection attempt via where_value is escaped; the row simply
    doesn't match (no row with that literal name) and we get LookupError."""
    s = _seeded_session()
    with pytest.raises(LookupError):
        erase(
            s,
            table="stg_proposals",
            where_column="holder_name",
            where_value="'; DROP TABLE stg_proposals; --",
            model_cls=CanonicalProposal,
            erased_by="x",
            reason="y",
        )
    # Table still exists with both rows.
    rows = s.sql("SELECT COUNT(*) AS n FROM stg_proposals").iloc[0]["n"]
    assert rows == 2


# --- init_audit_table ---


def test_init_audit_table_is_idempotent() -> None:
    """Running init twice doesn't error."""
    s = _seeded_session()
    init_audit_table(s)  # second time
    # Table still queryable.
    s.sql(f"SELECT * FROM {AUDIT_TABLE}")


def test_audit_table_starts_empty_in_fresh_session() -> None:
    s = _seeded_session()
    n = s.sql(f"SELECT COUNT(*) AS n FROM {AUDIT_TABLE}").iloc[0]["n"]
    assert n == 0
