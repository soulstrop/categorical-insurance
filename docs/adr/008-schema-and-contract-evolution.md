# ADR 008: Schema and Contract Evolution

## Status
Accepted (2026-04-30). Companion to ADR 006 (PII Handling) and ADR
007 (Right-to-Erasure). Closes `docs/PHASES.md` "What is not yet in
any phase" item #8 (schema evolution) and item #14 (data contracts
with upstream producers).

## Context

The `CanonicalProposal` shape is locked today by the dbt source-
contract drift check (P2.3). That check enforces a snapshot — *the
shape now matches its committed YAML* — but says nothing about how
the shape changes over time.

Three forces will alter the shape, all inevitable:

1. **Product evolution.** New product lines add fields (telematics
   inputs for motor; medical-underwriting answers for life). Existing
   fields get refined (free-text `address` becomes a structured
   record). Some fields become unused as products are sunset.
2. **Regulatory change.** New rating-factor disclosures, new
   reporting requirements, new mandatory consent capture.
3. **Upstream producer changes.** The claims system, the
   underwriting workbench, and any external feeds all evolve under
   their own pressures. Their schemas drift; ours has to absorb the
   change without breakage.

For a system that issues contracts intended to be enforceable for
years and replayable for the regulator's full audit horizon (often
seven years; in some lines of business, longer), the question is not
*whether* old contracts must remain interpretable but *how*.

`governance_version` (Phase 4) solves this for *policy* — every
contract carries a foreign key into the bundle that admitted it. The
analogous mechanism for *proposal and contract schema* is what this
ADR establishes.

The decision splits into eight sub-questions. Several have been
implicitly settled by ADRs 006 and 007 (the classification scheme;
erasure tombstone semantics) and this ADR makes those choices
explicit at the schema layer.

## Sub-decisions

### 1. Versioning scheme — integer + date dual identifier

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Implicit (no version)** | Latest schema is canonical; old data is migrated forward on read. | Simplest. | Forecloses replay; old contracts get rewritten and lose fidelity. |
| **B. Single integer** *(chosen — operational id)* | `schema_version: int`, monotonically increasing. | Trivial to query, sort, compare. Cheap to store. | Carries no semantic information about *what* changed. |
| **C. SemVer (major.minor.patch)** | Distinguishes additive (minor) from breaking (major). | More expressive; signals compatibility. | Most teams under-use the distinction; cosmetic-vs-additive disagreements proliferate. |
| **D. Date** *(chosen — informational metadata)* | `2026-01-01`. | Intuitive; aligns with regulatory effective-date semantics. | Date arithmetic for "what version were we on" is fiddly. |
| **E. Content hash** | Hash of the schema definition. | Cryptographically unambiguous; supply-chain friendly. | Human-unfriendly; not orderable. |

Chosen: **B + D**. The integer is the operational identifier
(`schema_version: 3`); the date is informational metadata
(`schema_effective_date: 2026-01-01`). One source of truth lives in
code; the date documents intent. SemVer's expressiveness is
re-introduced at the major-version boundary (sub-decision 2) but
without the minor/patch ceremony that goes unused in practice.

### 2. Compatibility policy — additive within a major; explicit version across majors

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Strict-additive (backwards-compatible only)** | Only adding optional fields is allowed; everything else triggers a new schema version. | Simplest reader story; no migration code. | Cannot rename, retype, or remove anything. Reality intrudes within a year. |
| **B. Forward-only migration** | Old data is rewritten to the latest schema on read. | Reader sees one shape. | Loses historical fidelity; an audit query "what did the proposal look like in 2025?" cannot be answered. |
| **C. Multi-version coexistence** | Each row carries its `schema_version`; readers route to the appropriate parser. | Full historical fidelity; no migration cost. | Every reader must handle multiple versions; complexity grows with version count. |
| **D. Hybrid** *(chosen)* | Strict-additive within a major version; multi-version coexistence across majors. | Common case (additive change) is cheap; rare case (breaking change) is explicit and bounded. | Two regimes to maintain; the line between "additive" and "breaking" needs a written rule. |

Chosen: **D**. Within a major version, only additive changes are
allowed: new optional fields with sensible defaults. The integer
version increments on every additive change so the "what was the
shape on date X" lookup remains exact. Across major versions,
multi-version coexistence applies: the codebase carries `ProposalV1`
*and* `ProposalV2` as discriminated-union members, and a
`parse_proposal(row)` dispatch reads the `schema_version` and routes.

The written rule for "additive vs breaking":

* **Additive** (no major bump): adding an optional field with a
  default; widening a numeric type (int → float); adding a literal
  value to an enum; adding a nested optional model.
* **Breaking** (major bump required): renaming a field; removing a
  field; narrowing a type; changing a default that downstream
  consumers depend on; restructuring a nested record; changing the
  semantics of an existing field while preserving its name.

### 3. Schema-version field placement — on every row

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. On every row** *(chosen)* | Each `Proposal` and `Contract` row carries `schema_version: int`. | Mixed-version reads are trivial SQL; replay arithmetic ("count v1 contracts") is one GROUP BY. | One extra column per table. |
| **B. Per-table version pin** | A metadata table records "table T follows schema vN." | One row of metadata, not one column per row. | Cannot mix versions within a table; every schema bump becomes a full table rewrite. |
| **C. Implicit by write timestamp** | The version in effect at write time is canonical. | No new column. | Changes the question "what version is this?" into a date-arithmetic problem against a separate "version effective dates" table; brittle. |

Chosen: **A**. Storage cost is trivial; query convenience is
substantial; mixed-version coexistence (sub-decision 2) demands it.

### 4. Migration mechanism — version-specific Pydantic models for code, view-layer projection for analytics

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Version-specific Pydantic models** *(chosen for app code)* | `ProposalV1`, `ProposalV2`; `parse_proposal(row)` dispatches by version. | Explicit; auditable; type-checked per version. | Class count grows with major-version count. |
| **B. One Pydantic model, version-conditional defaulting** | Single `Proposal`; logic like `if version == 1: x = default_for_v1`. | One class. | Defaults business logic into the model; the "single model" is a fiction with conditional branches. |
| **C. Migration scripts at write time** | Rewrite all old data when a new schema lands. | Reader sees one shape. | Loses historical fidelity (same problem as compatibility option B). |
| **D. View-layer migration** *(chosen for analytics)* | SQL views project all versions into the latest shape. | Analytical queries see uniformity. | Encodes business logic in SQL. |

Chosen: **A for application code; D for analytical queries.**

The application reads with full historical fidelity via the version-
discriminated parser. Analytics — which usually wants "give me a
single comparable view across all versions" — gets a `v_proposals`
SQL view that projects v1, v2, v3 into the latest schema with
NULL-fill semantics for fields that didn't exist in earlier versions.
The view is **not** the source of truth; the underlying versioned
rows are.

### 5. Upstream data contracts — ingest-side validation with quarantine, plus dbt contracts as the architectural target

This addresses PHASES.md item #14.

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. None** *(status quo)* | Trust the producer; tests catch breakage. | Zero cost. | First incident notification arrives via a Dagster failure or, worse, a wrong contract issued. |
| **B. Producer-side schema registry** | Producers publish their schema to a shared registry (Confluent, Glue, custom Snowflake table); CI on producer side runs against the registry. | Architecturally clean. | Multi-quarter program requiring producer-team adoption. |
| **C. Bilateral contracts via dbt's `contracts:` feature** *(chosen as architectural target)* | dbt models declare their consumed contracts; CI on the consumer side fails when the producer's published schema drifts. | Native to our stack; visible in the same PR review surface as everything else. | Requires producers to also publish a contract — a partial dependency on B. |
| **D. Consumer-side schema validation at ingest, with quarantine** *(chosen as operational baseline)* | Every batch is validated against the expected schema; mismatches go to a `raw_quarantine` table that triggers an asset-check failure and a runbook entry. | Defends regardless of producer cooperation; high-volume operationally feasible (a few seconds per batch). | Catches the break *after* it ships, not before. |

Chosen: **D as the operational baseline; C as the architectural
target with producer engagement; B as a multi-year program if scale
justifies it.**

For a high-volume operation, D is the operational backbone — you
cannot rely on cross-team coordination for every schema change at the
producer. The quarantine table is itself an asset (P3 SDA) with an
asset check that fails on non-empty content; on-call sees the failure
within one nightly cycle. C is what mature data orgs converge to
once producer relationships are established and the political cost of
"your schema change broke us" is borne by the producer's CI rather
than your on-call rotation.

### 6. Schema registry — Pydantic + dbt YAML, drift-checked

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. In-code only (Pydantic classes)** | Schemas are Python. | Simplest. | Cross-system observability — "what is the current proposal shape?" — requires reading source code. |
| **B. Pydantic + dbt YAML, drift-checked** *(chosen — current state)* | Pydantic is canonical; dbt YAML is a generated projection; CI fails on drift. | Already implemented (P2.3); leverages existing infrastructure. | Two artefacts to maintain; the drift check is the discipline. |
| **C. External registry (Confluent / Glue / dedicated Snowflake table)** | Schemas published to a registry that other systems consume. | Cross-system observability. | New infrastructure; another thing to keep in sync. |
| **D. Both B and C** | Code is canonical for runtime; registry is canonical for cross-system observability. | Best of both. | Three artefacts to keep in sync. |

Chosen: **B for now; the upgrade to D becomes interesting only when
multiple producers each have their own schemas and need to discover
ours.** The drift check we already have is the load-bearing
mechanism.

### 7. Schema-change governance — tiered

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Engineering-only** | Any team member can propose any schema change. | Fast. | A breaking change can ship without compliance, ops, or downstream-consumer awareness. |
| **B. Two-person rule across the board** | Every schema change requires two reviewers. | Catches obvious mistakes. | Same review burden for "added an optional field" and "renamed three fields." |
| **C. Schema-review board** | Monthly meeting with compliance, ops, downstream-consumer reps. | All stakeholders involved. | Slow; meeting attendance becomes the bottleneck. |
| **D. Tiered** *(chosen)* | Additive changes (no major bump) are engineering-only with single review; breaking changes (major bump) require the board. | Most changes are additive — they stay fast. The expensive process applies only to the rare expensive change. | Two paths to document; the line between additive and breaking (sub-decision 2) becomes load-bearing. |

Chosen: **D**. The "additive vs breaking" written rule from
sub-decision 2 is what tells the engineer which lane they're in. The
board meets only when a major-version bump is proposed (typically
quarterly or less).

### 8. Erased rows across schema versions

This is where ADRs 007 and 008 intersect.

A row erased under v1 (tombstone-with-PII-null per ADR 007 §1)
remains in the table forever, carrying `schema_version: 1` and
`erased: true`. When v2 lands:

* The tombstoned v1 row is **immutable**: its `schema_version`
  remains 1, its retained non-PII fields are not migrated.
* The view-layer projection (sub-decision 4 option D) reads the v1
  row through the `v_proposals` view and projects it into the v2
  shape with NULL-fill for any fields v2 added — including any
  fields that would have been PII under v2 but didn't exist in v1.
* The audit snapshot in `_audit_erasures` (ADR 007 §4) carries the
  `schema_version` at time of erasure. A regulator query that needs
  to see "what was erased" gets the v1 shape, not a migrated-forward
  approximation.
* If v2's classification scheme (per ADR 006 §1) re-classifies a
  field that v1 considered non-PII, the v1 tombstoned row is **not**
  retroactively re-erased on the new field. The justification: the
  row was erased under v1's compliance model, which was correct at
  the time. A retroactive re-erasure pass is a separate, auditable
  operation triggered explicitly when a classification change has
  PII consequences for historical data.

This last point is consequential and is recorded explicitly in the
runbook as the "classification-change retroactive sweep" procedure.

## Out of scope

* **Migration of *current production* data to a versioned schema.**
  This ADR establishes the forward-going regime; the one-time bump
  to introduce `schema_version: 1` on existing rows is a separate
  Phase 2-revisit ticket.
* **Migration of *governance bundles* across versions.** Phase 4's
  `governance_version` is its own thing; this ADR concerns proposal
  and contract schemas.
* **Cross-version semantic drift.** A field whose *meaning* changes
  silently while its name and type stay the same is a problem this
  ADR does not solve. The mitigation is the written rule
  (sub-decision 2) requiring a major-version bump for any semantic
  change; the discipline is human.
* **Dagster asset versioning** for SDAs whose code changes. Dagster
  has its own `code_version` mechanism for asset checks; out of scope
  here but worth recording in the Phase 3 work.

## Consequences

* **Positive.** Replay (Phase 4) becomes well-defined: a v1 contract
  rerun against today's policy bundle produces a deterministic
  result, because the v1 proposal is parsed with `ProposalV1` and
  the shape it had on the date of writing is preserved exactly.
* **Positive.** Audit horizon is honoured at full fidelity. Seven
  years from now, a regulator can ask "what did the proposal look
  like" and the answer is exact, not a forward-migrated
  approximation.
* **Positive.** Upstream incident detection improves: the quarantine
  table + asset check + runbook entry catches a producer-side schema
  change within a nightly cycle, not at the next compliance review.
* **Positive.** Adding an optional field stays cheap (single review,
  PR, ship). The expensive process applies only when truly needed.
* **Negative.** The codebase carries multiple versioned `ProposalVN`
  classes after every major bump. We mitigate by enforcing a
  hard-deprecation horizon (e.g., a major-version goes read-only at
  N years and into archive at M > N), but the class count grows
  monotonically.
* **Negative.** The view-layer projection (sub-decision 4 option D)
  encodes "how to read v1 as v2" in SQL. That's business logic in a
  language not unit-testable the way Python is. Mitigation: every
  cross-version projection in the view layer has a paired pytest
  fixture that asserts equivalent results from the Python versioned
  parser.
* **Negative.** The "additive vs breaking" rule (sub-decision 2)
  carries real organisational weight. A team member who mis-classifies
  a breaking change as additive ships a silent compatibility break.
  Mitigation: a CI check that compares the new schema against the
  previous version's schema and flags any field rename, removal, or
  type-narrowing as a candidate breaking change requiring explicit
  acknowledgement.
* **Negative.** The board governance for major-version bumps adds
  calendar-time latency to genuine breaking changes. Acceptable —
  major bumps are rare and the board exists precisely for this.

## What changes in the codebase if accepted

* `CanonicalProposal` and `Contract` gain `schema_version: int = 1`
  and `schema_effective_date: date`.
* New module `catins.schema_evolution`:
  * `ProposalV1 = CanonicalProposal` initially; the discriminator
    pattern is documented but no V2 exists yet.
  * `parse_proposal(row: dict) -> ProposalV*` dispatch.
  * `compatibility_check(prev: type[BaseModel], next: type[BaseModel])
    -> CompatibilityReport` — used by CI to flag candidate breaking
    changes.
* dbt project gains:
  * `models/marts/v_proposals.sql` — cross-version projection view;
    initially trivial (one version) but the pattern is established.
  * `models/raw/raw_quarantine.sql` — landing table for ingest-side
    schema-validation failures.
  * Asset check on `raw_quarantine` (P3-adjacent ticket) that fails
    when row count > 0.
* `catins.dbt` extends the drift check to also fail on a candidate
  breaking change unless an `# evolution: breaking` annotation is
  present on the changed field.
* New CI step `mise run //python:schema:compat-check` running
  `catins.schema_evolution.compatibility_check` against the
  previous-commit schema; runs after the existing drift check.
* `tests/test_schema_evolution.py`:
  * Round-trip: `ProposalV1` instance → JSON → parse → equivalent
    instance.
  * Forward-projection: `ProposalV1` instance → `v_proposals` view →
    DataFrame row matches `ProposalV2` shape with NULL-fill.
  * Erasure-immutability: tombstoned `ProposalV1` row remains v1
    even after v2 lands; classification changes don't retroactively
    re-erase.
* `docs/RUNBOOK.md` (P3.6) gains:
  * Schema-bump procedure (additive path; major-bump path).
  * Quarantine-investigation procedure.
  * Classification-change retroactive-sweep procedure.
* `docs/PHASES.md` updated:
  * Phase 2-revisit: backfill `schema_version: 1` on existing data.
  * Phase 4 replay infrastructure: explicitly references this ADR's
    multi-version coexistence as a precondition.

## Open questions

1. **Major-version deprecation horizon.** When does a `ProposalV1`
   class get archived out of the live codebase? Defer to first
   major-version bump; informed by audit-horizon legal requirements.
2. **Schema-review board membership.** Compliance, ops, downstream
   consumer rep at minimum. Org-chart dependent.
3. **Producer engagement model for ADR 008 §5 option C (bilateral
   dbt contracts).** Which upstream producers do we approach first,
   and what's the value proposition? Strategic, not architectural;
   defer until Phase 3 ships and we have concrete pain to point at.

## References

* `docs/PHASES.md` "What is not yet in any phase" items #8 (schema
  evolution) and #14 (data contracts with upstream producers) —
  the prerequisites this ADR discharges.
* ADR 006 — PII and sensitive-data handling (the classification
  scheme that this ADR's evolution semantics inherit).
* ADR 007 — right-to-erasure (the tombstone-immutability claim that
  intersects with §8 of this ADR).
* dbt's `contracts:` feature documentation (the architectural target
  for §5 option C).
* Confluent Schema Registry / AWS Glue Schema Registry / Snowflake
  Schema Detection (alternatives considered for §6 option C).
