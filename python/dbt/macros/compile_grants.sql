{# compile_grants(role): tier-aware GRANT-emission macro.

   Use as a post-hook on a model that should be readable only by a
   particular role. ADR 007 §4 requires the audit log to be visible
   only to privacy officers in prod tiers — this macro is how that
   intent is expressed in the model file.

   Returns a list of SQL statements (suitable for the ``post_hook``
   config). Empty list on tiers without grants (DuckDB), so the
   model file shape is the same across all tiers.

   Usage:
       {{ config(post_hook = compile_grants(role='privacy_officer')) }}
#}
{% macro compile_grants(role) %}
{% set features = feature_set() %}
{% if features.grants %}
    {{ return([
        "GRANT SELECT ON " ~ this ~ " TO ROLE " ~ role | upper
    ]) }}
{% else %}
    {{ return([]) }}
{% endif %}
{% endmacro %}
