{# compile_masking(field, policy): tier-aware masking expression.

   Returns a SQL expression that selects ``field`` with the
   appropriate masking applied for the active tier:

   * **enterprise** — emits ``field`` unwrapped; the column is
     governed by a Snowflake ``MASKING POLICY`` attached
     out-of-band (DDL not in dbt). The warehouse evaluates the
     policy on read; the SQL the macro emits looks unprotected
     because protection lives in the column metadata.
   * **standard** — emits a ``CASE`` expression that mirrors the
     prod policy, gated on Snowflake's ``CURRENT_ROLE()`` /
     ``IS_ROLE_IN_SESSION``. Same semantics as the policy, just
     enforced inline.
   * **duckdb** — emits ``field`` unchanged. CI does not assert
     access control, only shape parity.

   ``policy`` is a label looked up in a (currently inline) policy
   table; ``direct_pii`` masks to ``'***'`` for unprivileged roles.
#}
{% macro compile_masking(field, policy) %}
{% set features = feature_set() %}
{% if features.masking == 'policy' %}
    {{ return(field) }}
{% elif features.masking == 'case_expression' %}
    {% if policy == 'direct_pii' %}
        {{ return("CASE WHEN IS_ROLE_IN_SESSION('PRIVACY_OFFICER') THEN " ~ field ~ " ELSE '***' END") }}
    {% elif policy == 'quasi_pii' %}
        {{ return("CASE WHEN IS_ROLE_IN_SESSION('ANALYST') OR IS_ROLE_IN_SESSION('PRIVACY_OFFICER') THEN " ~ field ~ " ELSE NULL END") }}
    {% else %}
        {{ exceptions.raise_compiler_error("compile_masking: unknown policy '" ~ policy ~ "'") }}
    {% endif %}
{% else %}
    {{ return(field) }}
{% endif %}
{% endmacro %}
