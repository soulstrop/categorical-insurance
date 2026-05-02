{# Generic test: a consumer-facing view never returns rows where
   erased = true. ADR 007 §2 + the erasure_filter macro guarantee
   this; the test catches regressions where a model is added without
   the macro applied.

   A row returned indicates a failure (dbt's "rows returned = bad"
   convention).
#}
{% test view_filters_erased(model) %}
SELECT *
FROM {{ model }}
WHERE erased = true
{% endtest %}
