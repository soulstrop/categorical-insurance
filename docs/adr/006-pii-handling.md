# ADR 006: PII and Sensitive-Data Handling

## Status
Accepted (2026-04-30). Required prerequisite for the dbt
`prod=snowflake` profile to be usable. Closes
`docs/PHASES.md` "What is not yet in any phase" item #4.
Companion to ADR 007 (Right-to-Erasure).

## Context

Insurance proposals carry a stack of regulated identifiers that the
current `CanonicalProposal` does not yet acknowledge. In production
the model would gain SSN, date of birth, address, prior-claim history,
and depending on product line health-underwriting answers and
behavioural / telematics data. Several regulatory regimes can apply
simultaneously — GLBA on financial PII, HIPAA on health-adjacent
products, GINA on genetic information, state insurance privacy laws
(NY DFS 23 NYCRR 500, CIPA in CA, NAIC Model Act), and CCPA / state
consumer-privacy regimes.

The codebase has zero of this surface today. `CanonicalProposal.holder`
is a free-text string, mock data uses placeholder names, and the dbt
`prod` profile connects with no masking-policy reference. The mock
hides the issue; the moment any real data lands, every operational
decision below has been made implicitly by absence.

The Phase 2 audit identified PII handling as a hard prerequisite
shipped past inadvertently. This ADR records the decision so that
implementation against real data cannot resume without an explicit
choice on each axis.

## Sub-decisions

### 1. Field classification

Fields are classified at the Pydantic source-of-truth via a small
marker class:

```python
from typing import Annotated
from catins.privacy import PII

class IndividualHolder(BaseModel):
    name: Annotated[str,        PII("direct",   regimes={"GLBA"})]
    ssn:  Annotated[str,        PII("direct",   regimes={"GLBA"})]
    dob:  Annotated[date,       PII("quasi",    regimes={"GLBA"})]
    zip_code: Annotated[str,    PII("quasi",    regimes={"GLBA"})]
```

A CI check fails when a new field on any privacy-bearing model is
unannotated. The classification feeds the dbt source-contract
generator (ADR-008-adjacent), which emits per-field `MASKING POLICY`
references in production-target YAML and view-based emulation in dev /
mock targets.

The classification is *the* source of truth: a separate YAML
registry would be a fourth column list and re-introduce the drift
problem the existing dbt drift check solves.

### 2. Holder type model

The `holder` field on `Proposal` becomes a discriminated union:

```python
Holder = IndividualHolder | EntityHolder
```

`IndividualHolder` carries PII annotations as above.
`EntityHolder` (insured business: legal name, EIN, address) is *not*
PII under GLBA's individual-consumer definition; it remains a regular
typed model. Treating both as PII would over-protect business records
and obscure the genuinely-sensitive individual case.

### 3. Protection at rest — hybrid tokenisation + DDM

Direct identifiers (SSN, full name when on `IndividualHolder`,
account / payment identifiers) are **tokenised at the staging
boundary** via self-managed HashiCorp **Vault Enterprise**'s Transform
secret engine. The vault holds the canonical `(token → plaintext)`
mapping; the warehouse holds only tokens. Most analytics never decode.

Quasi-identifiers (DOB, ZIP, age, address) are protected at read time
by **Snowflake Dynamic Data Masking**, with partial-reveal policies
where useful (year-only DOB, ZIP prefix only) for non-`PII_FULL`
roles.

Health-adjacent and behavioural fields are DDM with full mask by
default; explicit `PII_FULL_HEALTH` role required.

The hybrid is chosen for high-volume operating economics: tokenisation
pays its cost once at ingest (bounded by upstream throughput); DDM
pays its cost as a planner-time policy lookup (negligible per query).
Column-level encryption everywhere would multiply read cost on every
join and was rejected on those grounds. Tokenisation everywhere would
make legitimate quasi-identifier analytics (age cohorts, ZIP
distributions) require constant detokenisation, defeating the point.

### 4. Vault deployment — self-managed Enterprise

Self-managed Vault Enterprise is chosen over HCP Vault Cloud and
tokenisation-specialist alternatives (Skyflow, Privacera). Operational
familiarity (the team already operates Vault in transactional
contexts), key custody control, and the ability to lock the transform
engine to a specific cluster outweigh the lower TCO of managed
options.

The analytical use case has substantially weaker operational demands
than a transactional Vault deployment:

| Concern | Transactional Vault | Analytical Vault (this project) |
|---|---|---|
| Lease / renewal | App-side state, refresh logic | Stateless encode/decode HTTP calls |
| Caching | App-side cache + revocation | No caching; plaintext never persisted outside Vault |
| Hot path | Vault is on every write | Vault is on ingest only; analytics never call it |
| Failure mode | Outage stalls writes | Outage stalls plaintext decode; tokens still queryable |
| QPS shape | Many small calls | Batched (encode/decode arrays per dbt staging run) |

Vault config-as-code lives at `vault/` in the monorepo: transform
engine roles, transformations, and the role-to-field mapping
generated from the Pydantic classification at build time.

### 5. Access control — RBAC + ABAC hybrid

Role-based access for **capability** (`PII_FULL`, `PII_MASKED`,
`PII_FULL_HEALTH`, `NONE`); attribute-based row access policies for
**scope** (jurisdiction, product line, business unit). The two
compose by intersection.

Pure RBAC at the cardinality of (capability × jurisdiction × product
line × business unit) produces the well-known role explosion at
scale. ABAC keeps each axis small (a half-dozen attributes); RBAC
covers the data-class dimension where there really are only a handful
of choices.

Access policies are declared in dbt model `meta` blocks and compiled
to Snowflake `GRANT` and `ROW ACCESS POLICY` statements by a custom
macro (production) or to view-level filters (dev / mock — see §7).

### 6. Audit — ACCESS_HISTORY + selective SIEM forwarding

`SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY` is enabled in production as
the foundational audit log: every column access by every user is
recorded, with 365-day retention. This satisfies most compliance
attestation requirements at zero engineering cost.

Accesses to vault-tokenised fields and to `PII_FULL` / `PII_FULL_HEALTH`
roles are additionally forwarded to an external SIEM (Splunk or
Datadog Cloud SIEM, decision deferred) for real-time alerting on
anomalies. The bimodal split — Snowflake-native for the high-volume
quasi-identifier tier, SIEM for the low-volume sensitive tier — keeps
SIEM ingestion cost bounded while still satisfying NY DFS / NAIC
real-time-alerting expectations on the highest-risk path.

### 7. Dev tier vs prod tier — classification-driven multi-target generation

Snowflake Standard (the dev tier) lacks Dynamic Data Masking, Row
Access Policies, and `ACCESS_HISTORY`. Snowflake Enterprise (the
prod tier) has all three. Local development additionally targets
DuckDB.

The same Pydantic classification → multiple compilation targets:

| Mechanism | Prod (Snowflake Enterprise) | Dev (Snowflake Standard) | Local mock (DuckDB) |
|---|---|---|---|
| Tokenisation | Vault Transform | Vault Transform (same dev cluster) | In-process Python token map |
| Field masking | `MASKING POLICY` DDL | `pii_masked` view layer with role-conditional `CASE` | Same view-based emulation |
| Row access | `ROW ACCESS POLICY` DDL | View with `WHERE` clause referencing session variable | Same with a context-variable shim |
| Audit log | `ACCESS_HISTORY` | `access_log` table written by a logging UDF on each masked view | Same custom log table |

The dbt project gains a `target.feature_set` macro: `enterprise` in
prod, `standard` in dev, `mock` in local. Three compilation targets,
one source of truth.

The trade is explicit: **dev-tier behaviour is functional, not
enforcement.** A developer in the dev account can `SELECT *` on the
underlying table and bypass the view layer. This is acceptable
because:

* Dev data is synthetic or already-tokenised (real PII never lands in
  dev).
* The contract preserved across tiers is the **interface** (the
  masked views), not the **enforcement** (deny-by-policy).

What is gained: contributors run the full pipeline against Snowflake
Standard, see the same masked outputs they will see in prod, and
write code against the masked surface — and CI verifies the surface
is identical across tiers.

### 8. Secret resolution — fnox

All secrets — Snowflake credentials, Vault token, SIEM API keys —
flow through [`fnox`](https://github.com/jdx/fnox), the env-var
injection model from the same author as `mise`. Code reads
`os.environ`; fnox makes sure values are present, sourced from
age-encrypted git in dev, from Vault or AWS Secrets Manager in CI and
prod.

This abstracts secret storage from the execution environment: the
same `mise run //python:test` works locally with shell integration
auto-loading on `cd`, in CI with `fnox exec --` wrapping mise, and in
production with the same wrapper. No code path branches on
environment.

The Vault token itself is fnox-managed: contributors get a dev-tier
Vault token via fnox-encrypted secrets in the repo; CI pulls a
service token from cloud-managed secrets via fnox; production reads
the token from the same provider. The Vault client in
`catins.privacy.vault` is unaware of any of this and just reads
`VAULT_ADDR` / `VAULT_TOKEN` from the environment.

## Out of scope

* **Right-to-erasure mechanics** (CCPA, state-law deletion rights):
  ADR 007.
* **Schema and contract evolution** (versioning of the `Proposal`
  shape over time, including how erased / tombstoned records remain
  interpretable): ADR 008.
* **Subprocessor and vendor management** (BAAs, DPAs): a compliance
  / legal artefact, not an engineering decision.
* **Pen-testing and red-team posture**: operational, not architectural.

## Consequences

* **Positive.** A single classification at the Pydantic layer drives
  protection, access, masking, and audit consistently across runtime,
  warehouse, and the local mock. CI will refuse a new sensitive field
  that lacks classification.
* **Positive.** The hot read path is DDM-only — no decryption, no
  vault round-trip, no per-query overhead. Compliance scope on the
  warehouse shrinks to the quasi-identifier tier; direct identifiers
  live in Vault and rarely leave it.
* **Positive.** Operational secrets carry no environment-specific
  branching at the code level. fnox is the seam.
* **Negative.** The mock surface is non-trivial: a tokenisation
  emulator, view-based masking, a session-variable shim for ABAC, and
  an `access_log`-emitting UDF. Mock fidelity must be unit-tested
  with the same rigor as the production code path. The "this masks
  the same way prod will" assertion is the test obligation that
  replaces the policy-engine guarantee.
* **Negative.** Vault becomes a critical dependency at ingest. A Vault
  outage stalls new ingestion (acceptable — analytics keep running)
  but adds an operational target requiring its own SLO, runbook,
  backup, and unseal procedures. The on-call runbook (P3.6) gains a
  Vault section.
* **Negative.** The dev tier's view-based emulation is a functional
  facsimile, not an enforcement boundary. Repository onboarding must
  warn new contributors that "I queried it directly in dev and saw
  unmasked values" is not evidence that prod is broken.
* **Negative.** Self-managed Vault Enterprise carries operating cost
  (license, on-call, upgrades) that managed alternatives would
  avoid. The team's existing Vault operational experience is the
  basis for accepting that cost.

## Open questions

1. **SIEM choice** (Splunk Cloud, Datadog Cloud SIEM, Snowflake's own
   Snowsight log forwarder). Defer to a separate small decision once
   throughput estimates are concrete.
2. **Vault transform engine role-to-field mapping format.** Concrete
   schema decision — to be made when the implementation lands.

## What changes in the codebase if accepted

* New module `catins.privacy` with the `PII` marker, classification
  helpers, and a Vault-backed tokenisation client (`hvac`).
* `CanonicalProposal` revised: `holder: IndividualHolder | EntityHolder`
  with PII annotations on `IndividualHolder`.
* `catins.dbt` extended to emit per-target SQL artefacts: `MASKING
  POLICY` and `ROW ACCESS POLICY` (Enterprise), view emulations
  (Standard / DuckDB).
* New `python/dbt/macros/` directory: `compile_grants.sql`,
  `compile_masking.sql`, `feature_set.sql`.
* New `vault/` config tree at the monorepo root: transform-engine
  roles and transformations as config-as-code.
* `fnox.toml` at the python/ tree root configuring secret resolution
  for `SNOWFLAKE_*` and `VAULT_*` env vars.
* `python/dbt/profiles.yml` `prod` block adds `query_tag` and
  session-attribute mapping for ABAC.
* `tests/test_privacy_*.py` covering the mock at parity with the
  production path: tokenisation round-trip, masking-view equivalence,
  access-log emission.
* `docs/RUNBOOK.md` (P3.6) gains a Vault section and a PII-incident
  section.
* `docs/PHASES.md` updated: PII work folded into Phase 2-revisit,
  with concrete done conditions.

## References

* `docs/PHASES.md` "What is not yet in any phase" item #4 (the
  prerequisite this ADR discharges).
* ADR 007 — right-to-erasure.
* ADR 008 — schema and contract evolution (forthcoming).
* HashiCorp Vault Transform secret engine documentation.
* Snowflake Dynamic Data Masking, Row Access Policies, and
  ACCOUNT_USAGE.ACCESS_HISTORY documentation.
* `fnox` — https://github.com/jdx/fnox
