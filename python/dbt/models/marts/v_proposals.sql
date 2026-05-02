-- Consumer-facing view over staged proposals. Per ADR 007 §2 the
-- WHERE clause filters out tombstoned rows via the erasure_filter
-- macro; the Dagster check_view_filter_compliance (P3.11) and the
-- generic test_view_filters_erased dbt test both enforce this.
SELECT
    holder_kind,
    holder_name,
    premium,
    zip_code,
    age,
    schema_version,
    schema_effective_date,
    erased
FROM {{ ref('stg_proposals') }}
WHERE {{ erasure_filter() }}
