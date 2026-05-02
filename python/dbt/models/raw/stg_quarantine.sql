-- Quarantine landing per ADR 008 §5. The Python ingest path writes
-- the underlying ``raw_quarantine`` table when ``parse_proposal``
-- rejects a row; this model is the dbt-managed projection over it,
-- with explicit casts so downstream tooling sees a stable column
-- contract. The Phase 3 ``quarantine_check`` (P3.8) reads this
-- model and fails when it is non-empty for the latest partition.
SELECT
    quarantine_id,
    CAST(quarantined_at AS TIMESTAMP) AS quarantined_at,
    CAST(schema_version_seen AS INTEGER) AS schema_version_seen,
    reason,
    detail,
    raw_payload
FROM {{ source('main', 'raw_quarantine') }}
