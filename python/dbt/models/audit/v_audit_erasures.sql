-- Privacy-officer-facing audit view per ADR 007 §4. Exposes the
-- full audit trail produced by ``catins.privacy.erasure.erase`` —
-- including the pre-erasure snapshot, which contains plaintext PII
-- and is therefore restricted to privacy-officer roles in prod
-- tiers via the ``compile_grants`` post-hook.
--
-- The erasure_filter does NOT apply here: an audit log must surface
-- *every* erasure event, including ones whose target row is now
-- tombstoned. That is the entire point of the table.
{{ config(post_hook=compile_grants(role='privacy_officer')) }}
SELECT
    erasure_id,
    CAST(erased_at AS TIMESTAMP) AS erased_at,
    erased_by,
    table_name,
    where_column,
    where_value,
    reason,
    pii_fields_nulled,
    pre_erasure_snapshot
FROM {{ source('main', '_audit_erasures') }}
ORDER BY erased_at DESC
