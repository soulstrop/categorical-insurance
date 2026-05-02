{# _governance_debug: tiny logging macro used by tests to introspect
   the active tier's governance behaviour. Not consumed by any
   model — it exists only to give the Python test layer a way to
   call ``feature_set`` / ``compile_grants`` / ``compile_masking``
   via ``dbt run-operation`` and assert on the captured stdout.

   Underscore prefix marks it as test-debug; the leading log line
   ``GOVERNANCE_DEBUG_BEGIN`` is the anchor the test parses.
#}
{% macro _governance_debug() %}
    {% set fs = feature_set() %}
    {{ log('GOVERNANCE_DEBUG_BEGIN', info=true) }}
    {{ log('tier=' ~ fs.tier, info=true) }}
    {{ log('masking=' ~ fs.masking, info=true) }}
    {{ log('row_access=' ~ fs.row_access, info=true) }}
    {{ log('grants=' ~ fs.grants, info=true) }}
    {{ log('mask_direct=' ~ compile_masking(field='holder_name', policy='direct_pii'), info=true) }}
    {{ log('mask_quasi=' ~ compile_masking(field='zip_code', policy='quasi_pii'), info=true) }}
    {{ log('grants_list=' ~ compile_grants(role='privacy_officer') | tojson, info=true) }}
    {{ log('GOVERNANCE_DEBUG_END', info=true) }}
{% endmacro %}
