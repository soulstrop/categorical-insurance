-- Staging view over raw proposals. The Phase 2 pipeline reads this
-- view and lifts each row through the validation UDF.
SELECT
    holder,
    CAST(premium AS DOUBLE) AS premium,
    zip_code,
    CAST(age AS INTEGER) AS age
FROM {{ source('raw', 'proposals') }}
