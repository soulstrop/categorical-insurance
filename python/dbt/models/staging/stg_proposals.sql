-- Staging view over raw proposals. The Phase 2 pipeline reads this
-- view and lifts each row through the validation UDF.
SELECT
    holder_kind,
    holder_name,
    CAST(premium AS DOUBLE) AS premium,
    zip_code,
    CAST(age AS INTEGER) AS age,
    CAST(schema_version AS INTEGER) AS schema_version,
    CAST(schema_effective_date AS DATE) AS schema_effective_date,
    CAST(erased AS BOOLEAN) AS erased
FROM {{ source('raw', 'proposals') }}
