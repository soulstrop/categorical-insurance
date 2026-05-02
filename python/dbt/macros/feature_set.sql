{# feature_set: which governance capabilities the active target supports.

   The catins dbt project compiles against three tiers (per the Phase-
   2-revisit plan):

   * **enterprise** — Snowflake Enterprise: real Dynamic Data Masking
     (DDM), Row Access Policies (RAP), grants. Macros emit policy
     references the warehouse enforces.
   * **standard** — Snowflake Standard (no DDM/RAP): masking is
     emulated as ``CASE`` expressions per consumer view; access
     control is via separate masked / unmasked views and grants.
   * **duckdb** — local CI tier: no governance enforcement; the
     macros are no-ops so consumer-view shape parity holds.

   The active tier is the dbt target's ``type`` for ``duckdb``, and
   the dbt var ``catins_tier`` (``standard`` | ``enterprise``;
   defaults to ``standard``) for Snowflake targets. Tests stub the
   tier via ``--vars '{"catins_tier": "enterprise"}'``.
#}
{% macro catins_tier() %}
{# An explicit ``catins_tier`` var always wins — that lets tests
   exercise the enterprise / standard branches against the DuckDB
   adapter (CI doesn't have the snowflake adapter installed). When
   the var is unset, the target's adapter type drives the choice. #}
{% set explicit = var('catins_tier', '') %}
{% if explicit %}{{ return(explicit) }}
{% elif target.type == 'duckdb' %}{{ return('duckdb') }}
{% else %}{{ return('standard') }}
{% endif %}
{% endmacro %}

{% macro feature_set() %}
{# Returns a Jinja dict of capability flags for the active tier.
   Models and macros should branch on these flags rather than on
   target.type directly — keeps the tier table the single source
   of truth for what a tier can do. #}
{% set tier = catins_tier() %}
{% if tier == 'enterprise' %}
    {{ return({
        'tier': 'enterprise',
        'masking': 'policy',
        'row_access': 'policy',
        'grants': true,
    }) }}
{% elif tier == 'standard' %}
    {{ return({
        'tier': 'standard',
        'masking': 'case_expression',
        'row_access': 'separate_view',
        'grants': true,
    }) }}
{% else %}
    {{ return({
        'tier': 'duckdb',
        'masking': 'none',
        'row_access': 'none',
        'grants': false,
    }) }}
{% endif %}
{% endmacro %}
