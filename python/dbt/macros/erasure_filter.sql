{# Erasure filter macro per ADR 007 §2.

   Every consumer-facing view in `models/marts/` is required to compose
   this predicate into its WHERE clause. The literal expansion is
   `erased = false` — both the dbt generic test
   (`test_view_filters_erased`) and the Dagster
   `check_view_filter_compliance` (P3.11) match against this exact
   form, so deviation is rejected.

   Usage:

       SELECT ... FROM {{ ref('stg_proposals') }} WHERE {{ erasure_filter() }}
#}
{% macro erasure_filter() %}
erased = false
{% endmacro %}
