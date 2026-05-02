-- Consumer-facing view over the contracts table produced by the
-- validation pipeline. Per ADR 007 §2 the WHERE clause filters out
-- tombstoned rows via the erasure_filter macro.
SELECT
    holder_kind,
    holder_name,
    premium,
    zip_code,
    age,
    schema_version,
    schema_effective_date,
    erased,
    payload_json
FROM {{ source('main', 'contracts') }}
WHERE {{ erasure_filter() }}
