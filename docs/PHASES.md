# Implementation Plan: Phased Rollout

This document sequences the production implementation of
`categorical-insurance` from a laptop-runnable MVP to a
multi-jurisdiction, audit-aware platform. Each phase has a
**conceptual frame** that names what kind of system it is at the
end of the phase, an explicit **scope** and **non-scope**, and
**done conditions** that are observable rather than aspirational.

The plan is sequential by default but each phase is meant to absorb
what was learned in the previous one. Phase boundaries are
revisable; the *direction* (toward more capability, more lineage,
more verification) is fixed.

## At-a-glance

| Phase | Frame | Runtime | Status |
|------:|-------|---------|--------|
| 0 | A working categorical pipeline on a laptop | Pure Python | implemented |
| 1 | Two learners, one real data source, laws verified | Python + Polars/DuckDB | implemented |
| 2 | Warehouse-native data and validation; training where ergonomic | dbt + Snowpark + Python harness | implemented |
| 2-revisit | PII boundary, erasure, schema versioning (per ADRs 006–008) | Same as Phase 2 + Vault, fnox | in progress (schema fields + PII marker + holder split + version registry/dispatch + compat-check landed) |
| 3 | Lineage and asset checks visible to ops users | Dagster on top of Phase 2 | in progress (P3.1–P3.7, P3.11 done; P3.8–P3.10 pending Phase-2-revisit) |
| 4 | Multi-jurisdiction; versioned policy bundles; replay | Phase 3 + policy-release infra | not started |
| 5 | Probabilistic outputs and audit-aware governance | Research-grade extensions | not started |

---

## Phase 0 — MVP: a categorical pipeline on a laptop

**Status: implemented** (commit `0d8970e`).

**Frame.** End-to-end working pipeline running in pure Python on a
single machine. No warehouse. No orchestrator. Synthetic data. The
Haskell types map to Python types; the Haskell laws are testable
locally.

**In scope.**
* `Proposal`, `Contract`, `Violation` as Pydantic models.
* The `Decision[M]` substrate (per ADR 004): `Decision[M] =
  Callable[[Proposal], M]` with a small `Monoid[M]` protocol
  (`empty`, `combine`). The initial concrete monoid is
  `M = list[Violation]` for **Governance** (per ADR 005), giving
  the familiar `Governance = list[Decision[list[Violation]]]`
  composed by `+`. Other monoid choices (Guardrails) are deferred
  to later phases but the substrate is parameterised from day 1.
* One closed-form learner: Bühlmann credibility (numpy).
* `validate(governed: Governed[Proposal], adm: M → bool)
  → Either[M, Contract]`, with the `M = list[Violation]`,
  `adm = (m == [])` instantiation as the day-1 case.
* A `Contract` constructor that is conventionally private (e.g., a
  single classmethod `Contract.from_validated(...)`); the
  abstraction barrier is documented in `CONTRIBUTING.md`.
* **Public/internal API hygiene.** Module-level `__all__`,
  leading-underscore convention for non-public names, and a
  `CONTRIBUTING.md` rule that direct imports of `_Contract`
  internals are a review-blocking offence. Python has no real
  privacy; the categorical guarantee around `Contract` becomes a
  social contract that the codebase has to enforce.
* **Reproducibility-seed discipline.** Every stochastic operation
  (synthetic-data generation, gradient steps, Hypothesis shrinks)
  accepts and propagates a seed. No reliance on
  process-default RNG.
* **Engineering toolchain.** Ruff + black for formatting and
  linting; `mypy --strict` on framework modules
  (`learner/`, `governance/`, `decisions/`, `contract/`), looser on
  examples; a lockfile via `uv` or `poetry`; `pre-commit` hooks;
  GitHub Actions running `pytest` on every push.
* **Test-as-documentation pattern.** Every example module exposes
  a `demo()` function that is both a runnable tutorial and a CI
  smoke test, mirroring the Haskell `Examples.Insurance.demo` /
  `Examples.RiskScore.demoRisk` convention.
* **License posture.** `LICENSE` (MIT, matching the Haskell
  sketch), license field in `pyproject.toml`, and
  `# SPDX-License-Identifier: MIT` on framework modules.
* Synthetic data fixtures.
* Tests in `pytest` covering happy paths and known violations.

**Out of scope.**
* Snowflake, dbt, Snowpark, Dagster, Cortex.
* Gradient learners.
* Real claims data.
* Property tests for category laws (Phase 1).

**Done conditions.**
1. `pytest` passes, including a test that demonstrates layered
   governance (`federal + california + internal`) rejecting a
   prohibited rating factor and approving a clean baseline.
2. A second engineer with a fresh machine reaches green in under
   30 minutes via `git clone && pip install -e . && pytest`, with
   no human help.
3. The `Proposal` and `Contract` types' fields are documented in
   one place (Pydantic + a one-page README).
4. The categorical correspondence is annotated in code: each
   public function under the framework modules carries a `math:`
   reference (e.g., `# math: math.tex Definition 3`); a
   `pre-commit`/CI check enforces the presence of an annotation on
   every public function.
5. CI on each push runs `pytest`, `ruff`, `mypy --strict` (on
   framework modules), and a fresh-checkout install, all green.
6. Every example module exports a `demo()` function that is
   invoked under `pytest` as a smoke test.
7. All stochastic operations accept and propagate a `seed`
   parameter; running the suite twice with the same seed produces
   bit-identical artefacts (where determinism is expected).

---

## Phase 1 — Data: two learners, one real source, laws verified

**Status: implemented** (commit `2908bfc`).

**Frame.** The MVP grows up. A real (small) data source replaces
synthetic fixtures; a second learner exercises composition; property
tests verify the Haskell laws (associativity, identity, conjunctive
governance composition).

**In scope.**
* DuckDB- or Polars-backed local feature engineering, replacing
  fixture generators.
* A second learner: linear regression with online SGD (matches the
  `Lin` example in `math.tex`).
* **Learner Algebra**: Sequential composition (`compose`), identity
  (`id_learner`), and parallel product (`parallel`) implementations,
  mapping to the optic-like combinators in `math.tex`.
* Property-based tests (Hypothesis) for:
  * `compose(g, identity) ≡ g` and `compose(identity, f) ≡ f`
  * `compose(compose(h, g), f) ≡ compose(h, compose(g, f))` up to
    observable behaviour
  * `p ⊨ G1 + G2 ⇔ p ⊨ G1 ∧ p ⊨ G2` (conjunctivity, ADR 001)
  * Monoid laws on every registered `Monoid[M]` instance —
    associativity, left identity, right identity — required per
    ADR 005 *for each instance separately*, not as a single
    parametric assertion.
* **Hypothesis strategy library** (`tests/strategies.py`):
  named generators for `proposals()`, `rules()`, `risk_scores()`,
  `decision_systems(monoid)` etc. Strategies for `Proposal` types
  are derived from Pydantic metadata (using `model_json_schema`) to
  ensure they stay in sync with the models.
* **Smoke tests for learner correctness** on a holdout, distinct
  from the categorical property tests above. Each learner has a
  test of the form "after training on this fixture, the
  prediction error is below this tolerance" — catches `update`
  arithmetic regressions that the property tests alone would not
  notice. (This is *correctness on a fixture*, not *drift
  monitoring*; the latter is Phase 3.)
* **Performance sanity ceiling.** No single test takes more than
  5 s; the full `pytest` suite completes in under 60 s on
  commodity hardware. A coarse cap, not a budget; meant to catch
  O(n) → O(n²) regressions, not to drive optimisation.
* Validation outputs persisted as Parquet for downstream
  inspection.

**Out of scope.**
* Snowflake.
* Production data volumes.
* Multi-jurisdiction policy bundles (Phase 4).

**Done conditions.**
1. Hypothesis-based property tests pass in CI, with strategies
   centralised in `tests/strategies.py`.
2. The second learner is added with no surgery to the framework
   (only a new module).
3. A real claims dataset (anonymised public, e.g., French TPL motor
   data) flows end-to-end to a Parquet contracts file.
4. The `compose` and `parallel` operations are documented with
   short examples in the README, naming the `math.tex` theorems they
   instantiate.
5. Each registered `Monoid[M]` has its own associativity and
   identity property tests (not a single parametric assertion),
   and they pass in CI.
6. Each learner has at least one correctness smoke test on a
   fixture; the test asserts a numeric tolerance (`pytest.approx`
   or equivalent), not just non-failure.
7. The full `pytest` suite runs under 60 s on commodity hardware
   in CI; any single test exceeding 5 s fails the suite.

---

## Phase 2 — Warehouse: data and validation in Snowflake; training where ergonomic

**Status: implemented** (mock-first; commits `f790e21` and
`3e8d0c6`). Categorical surface and warehouse-native substrate
shipped against DuckDB + dbt-duckdb + MockCortex; sandbox-time
swap to Snowflake/Cortex sits behind the protocols established in
the same commits.

**Frame.** Data and feature engineering move into Snowflake;
governance runs as a Snowpark UDF over warehouse data; learner
*scoring* runs in-warehouse; learner *training* runs in external
Python where the ergonomics are best. State is a derived view over
an append-only observation table, so "current state" is reproducible
from history rather than mutable.

**In scope.**
* dbt project for feature engineering with sources and contracts.
* Pydantic ↔ dbt source-contract generation: a single source of
  truth for the `Proposal` shape across Python and SQL.
* **Monoid Serialization**: Definition of the `M -> JSON` mapping
  for monoid payloads. By convention established in Phase 1, `M`
  must either be a primitive or a Pydantic model (or a list thereof),
  enabling trivial persistence into Snowflake `VARIANT` columns.
* **Vectorized UDF Adaptation**: A validator factory that lifts
  row-level `validate` calls into vectorized Snowpark UDFs
  compatible with Pandas Series, registered as one or more
  *instances* (one per active monoid, per ADR 004). This includes
  optimised, bulk Pydantic parsing (e.g., `TypeAdapter.validate_python`)
  to prevent single-row instantiation bottlenecks inside Pandas.
* The UDF returns `(admitted: bool, m: M)` per row; the `m`
  payload is persisted alongside the contract or rejection so that
  downstream analytics can reason about the decision without
  re-running the rules.
* **State Reconstruction from History**: Observation table (append-only)
  and a SQL view that derives current learner state (e.g., `CredState`)
  from history via precision-weighted aggregation. Because composite
  and gradient-based learners (like `Lin` SGD) cannot be derived
  purely via SQL views, state management bifurcates: closed-form
  learners use SQL views, while sequential learners rely on scheduled
  Python training jobs that write state back to a `VARIANT` column.
* Cortex `EXTRACT_ANSWER`-style functions for unstructured inputs,
  in their own dbt model with explicit per-run token budget.
* Python harness (`pipeline.py`) running `dbt run` then the
  Snowpark validation UDF, ordered explicitly (per ADR 002,
  Phase A).
* Output tables `contracts` and `rejections`. A
  `rejection_summary` view exposes counts by rule for analyst
  consumption.
* A nightly schedule (cron, GitHub Actions, or a Snowflake Task
  wrapping the harness).

**Out of scope.**
* Dagster (Phase 3).
* Asset checks beyond dbt tests (Phase 3).
* Cortex `EXPLAIN`-style human-readable rejection letters (Phase 3
  — they need ops-visible lineage to be worth wiring up).
* Multi-jurisdiction policy releases (Phase 4).

**Done conditions.**
1. Production-volume validation runs end-to-end via the Snowpark
   UDF without out-of-warehouse data movement.
2. Given a contract, the pipeline can reconstruct the learner
   state used to score it, via Snowflake `TIME TRAVEL` or the
   derived-state view.
3. The Pydantic `Proposal` model and the dbt source contract are
   generated from one source; manual SQL drift fails CI.
4. A Cortex extraction step turns at least one real unstructured
   input into a structured proposal that flows through the rest of
   the pipeline; per-run token budget is enforced and observable.

---

## Phase 2-revisit — PII boundary, erasure, and schema versioning

**Status: implementation in progress.** ADRs 006/007/008 land the
design in commit `868de27`; ADR 005 categorical lift in `8f67112`;
cross-doc consistency sweep in commits `78979e3` through `dab3dc8`.
Implementation in progress:
* The three metadata fields on `Proposal`
  (`schema_version: int = 1`,
  `schema_effective_date: date = SCHEMA_V1_EFFECTIVE_DATE`,
  `erased: bool = False`) and the
  `proposal_domain_fields(...)` projection that keeps validators
  and Cortex extraction operating on the concrete-subclass fields
  while warehouse storage flows the full column set through.
* The `catins.privacy` package with the `PII` marker
  (`PII(category, regimes={...})`) and Pydantic introspection
  (`pii_fields`, `non_pii_fields`, `is_pii`).
  `CanonicalProposal.holder_name` is annotated `PII("direct",
  regimes={"GLBA"})`; `zip_code` and `age` are
  `PII("quasi", regimes={"GLBA"})`. The annotation is invisible to
  the dbt drift check (Pydantic exposes the underlying SQL-mapped
  type) and to Pydantic validation.
* The holder discriminated union: `IndividualHolder | EntityHolder`
  with a `kind` literal, per-branch PII annotations
  (individual.name = direct PII; entity.name = not PII per ADR 006
  §1), and a `CanonicalProposal.holder` property that reconstructs
  the typed union from the flat `holder_kind` / `holder_name`
  warehouse columns. `extraction_fields(...)` returns the required
  domain fields Cortex should populate, excluding defaulted ones
  like `holder_kind`. The flat-column over-protection caveat
  (proposal-level `holder_name` is annotated PII unconditionally)
  is documented; the typed-union view is the only place where the
  conditional semantic is preserved.
* The `catins.schema_evolution` package: `SchemaVersion(version,
  effective_date)` value object + `SchemaRegistry` mapping
  integer version → `(SchemaVersion, model_cls)`, plus
  `parse_proposal(row, registry)` that dispatches a flat row to
  the registered model or returns a `QuarantineRow` (with
  ``reason`` and ``schema_version_seen``) on missing version,
  unknown version, or Pydantic validation failure. A populated
  `DEFAULT_REGISTRY` (v1 = `CanonicalProposal`) is exported for
  production callers; tests construct their own registry to
  exercise multi-version dispatch in isolation. P2R.11 wires
  `QuarantineRow` instances into the `raw_quarantine` table.
* The compat-check (`catins.schema_evolution.compat`): snapshots
  `Proposal` / `CanonicalProposal` / `IndividualHolder` /
  `EntityHolder` into `schema_baseline.json` and classifies any
  diff against the in-tree state as additive (safe) or breaking
  (field removed, type changed, optional→required, required field
  added). Breaking changes pass only when the `# evolution:
  breaking` annotation is present in `catins/models.py` — the
  marker P2R.3 placed in CanonicalProposal's docstring is the
  worked example. Two new mise tasks: `//python:schema:compat-check`
  (CI gate) and `//python:schema:write-baseline` (regenerate
  alongside a breaking change).

Production data flow is still gated on the rest of the revisit.

**Frame.** ADRs 006, 007, and 008 (2026-04-30) introduce
operational requirements that the original Phase 2 scope did not
account for. They were identified during a consistency audit after
Phase 2 shipped its categorical and warehouse-native pieces. The
categorical core and the substrate from Phase 2 remain unchanged;
this revisit adds the privacy and evolution machinery that wraps
them. Production data flow is gated on this revisit; the existing
Phase 2 substrate is exercisable against synthetic / mock data
today.

**In scope.**
* `PII` field marker (`catins.privacy`); CI check that every new
  sensitive field is annotated.
* `IndividualHolder | EntityHolder` discriminated union on
  `CanonicalProposal.holder`.
* `schema_version: int = 1`, `schema_effective_date: date`, and
  `erased: bool = False` fields on `Proposal` and `Contract`.
* `catins.schema_evolution` package: `parse_proposal`
  discriminated-union dispatch; `compatibility_check` CI helper
  for additive-vs-breaking detection.
* `catins.privacy` package: classification helpers, Vault
  Transform client (`hvac`), tokenisation round-trip.
* `vault/` config-as-code tree at the monorepo root: transform-
  engine roles and transformations.
* `fnox.toml` for secret resolution; CI updated to invoke through
  `fnox exec`.
* dbt project extensions:
  * `models/marts/v_proposals.sql`, `v_contracts.sql` — canonical
    filtered views with `WHERE erased = false` and masking
    applied.
  * `models/raw/raw_quarantine.sql` — schema-validation failure
    landing.
  * `models/audit/_audit_erasures.sql` — privacy-officer access
    only.
  * Per-target compilation macros: `compile_grants.sql`,
    `compile_masking.sql`, `feature_set.sql`. Three targets —
    Enterprise (real DDM + RAP), Standard (view-emulation),
    DuckDB (mock).
  * Generic dbt test `test_view_filters_erased.sql` asserting
    every consumer-facing view filters `erased = false`.
* `catins.dbt` extensions: classification-aware YAML generation;
  drift check fails on a candidate breaking schema change unless an
  `# evolution: breaking` annotation accompanies it.
* New CI steps:
  * `mise run //python:schema:compat-check` — runs
    `compatibility_check` against the previous-commit schema.
  * Vault round-trip tests (mock layer + real Vault behind
    `pytest.mark.vault`).
  * Masking-policy parity tests (DuckDB view-emulation produces
    the same masked rows that prod-tier `MASKING POLICY` would,
    on every classified field).
* Pipeline harness updated: `Cortex output → Vault tokenisation →
  warehouse landing` on ingress; `Vault detokenisation → Cortex
  letter generation → delivery` on egress.

**Out of scope.**
* Snowflake Enterprise deployment itself (sandbox-time activity).
* Real Vault Enterprise cluster (sandbox-time; CI uses a
  containerised dev Vault for round-trip tests).
* Real Cortex calls (CI uses `MockCortex`).
* Backfill of `schema_version: 1` across already-existing data
  (a separate one-time migration ticket).

**Done conditions.**
1. CI green: lint, drift check, schema-compat check, Vault
   round-trip tests, masking-policy parity tests, full pytest.
2. A proposal flowing through the pipeline cannot land a direct
   identifier in the warehouse — only a tokenised reference.
3. An erased row is invisible through the consumer-facing view and
   visible through the privacy-officer audit table; both
   asserted by tests.
4. A breaking schema change without the `# evolution: breaking`
   annotation fails CI; with the annotation it passes and
   surfaces a schema-review-board notification.
5. Dev-tier view-emulation produces the same masked outputs that
   prod-tier `MASKING POLICY` would, on every classified field,
   in parity tests (one assertion per `(field, role)` pair).
6. A non-empty `raw_quarantine` partition is detected by an asset
   check (Phase 3) and surfaces a runbook entry.

---

## Phase 3 — Asset graph: lineage and checks visible to ops

**Status: in progress.** P3.1–P3.7 (the originally-numbered
tickets) shipped: Definitions + Resources (`a4cedec`), Cortex
token-spend check (`291136b`), FreshnessPolicy on terminal
assets (`719bdc8`), canonical-generator schema-drift check
(`6b3407f`), planted-regression test for guardrail-stability
(`4ed800b`), on-call runbook (`ddb532b`), daily
ScheduleDefinition (`632e33e`). P3.11 view-filter compliance
landed mock-first against today's manifest (passes vacuously; will
fire when Phase-2-revisit adds `models/marts/` views without the
filter). P3.8–P3.10 (quarantine, PII access anomaly, erasure
latency) are catalogued below and pending — they need
Phase-2-revisit-side assets (`raw_quarantine`, `_audit_erasures`,
`ACCESS_HISTORY` integration) to read from.

**Frame.** The pipeline graph that already exists implicitly in
Phase 2 becomes a first-class object via Dagster Software-Defined
Assets. Asset checks formalise the invariants we relied on
convention to maintain. Cortex generates human-readable rejection
letters. Non-engineers gain self-service lineage and freshness via
the Dagster UI.

**In scope.** Items prefixed with **[done]** have shipped; the rest
are pending tickets.
* **[done]** Dagster project alongside the existing Phase 2 code;
  assets defined for raw → features → proposals → state →
  contracts / rejections (P3.1, commit `a4cedec`).
* Asset checks for:
  * **[pending P3.4]** Schema drift (formalising the dbt contract
    generation logic into a runtime check against the Pydantic
    schema; the existing `check_schema_drift` is column-set-only
    and will be lifted to use the canonical generator).
  * **[done P3.2]** Cortex token spend per run stays under budget
    (commit `291136b`; soft warning threshold on the
    `BudgetedCortex.total_tokens` accumulator carried by the
    Cortex resource).
  * **[done, with planted-regression test pending P3.5]**
    Guardrail-distribution stability: per-day distribution of the
    Phase 3 guardrail's `m` payload does not drift beyond a
    learned envelope (per ADR 005's operational practice). The
    check exists; the planted-regression demonstration that
    discharges Phase 3 done-condition #3 is P3.5.
* **[done]** The first **Guardrail** in production: an additive
  risk score with thresholded admission, using the same
  `Decision[M]` substrate (per ADR 005). Concrete monoid:
  `M = float`, `combine = +`, `empty = 0`, `adm(s) = s < cap`.
* **[done]** The validator runs as a **Joint** decision system in
  the product monoid `list[Violation] × float`, persisting both the
  violation list and the risk score on each contract row;
  admission is the conjunction of components' `adm`.
* **[done P3.3]** SLA / freshness policies on key assets (commit
  `719bdc8`; `FreshnessPolicy.time_window(fail=24h, warn=12h)` on
  `validated_outcomes`, `contracts`, `rejections`).
* **[done]** Cortex-based `explain_rejection` step producing a
  draft human-readable letter from a `Violation` list and the
  guardrail payload (implemented via the `MockCortex` stub
  established in Phase 2; resource-injected per P3.1).
* **[done P3.6]** On-call runbook: top three failure modes and
  first-step responses (`docs/RUNBOOK.md`, commit landing with
  this ticket; covers schema drift, guardrail drift, Cortex
  budget, freshness, plus the privacy-officer / Vault / schema-
  evolution procedures from ADRs 006/007/008).
* **[done P3.7]** Daily `ScheduleDefinition` for the
  `catins_validation_job`. Cron `0 6 * * *` UTC; aligns with the
  P3.3 24-hour freshness window with 18+ hours of overnight
  headroom before the 12-hour warn threshold trips.
* (Phase-2-revisit follow-ups, per ADR 002's 2026-04-30
  revision and ADRs 006/007/008. **P3.11 landed mock-first;
  P3.8–P3.10 still pending Phase-2-revisit.**)
  Additional asset checks and scheduled jobs:
  * **[pending P3.8]** `quarantine_check` (ADR 008): fails when
    `raw_quarantine` is non-empty for the latest partition.
  * **[pending P3.9]** `pii_access_anomaly_check` (ADR 006): reads
    `ACCESS_HISTORY`; fails when access to PII columns deviates
    from a learned envelope.
  * **[pending P3.10]** `erasure_latency_check` (ADR 007): SLA on
    time from erasure-request to tombstone (tracked against
    CCPA's 45-day window even though the system's GLBA-only
    scope means the SLA is operational, not legal).
  * **[done P3.11]** `view_filter_compliance_check`
    (ADR 007): static check over the dbt manifest asserting every
    consumer-facing view filters `erased = false`. Currently passes
    vacuously (no `models/marts/` views exist yet); becomes
    load-bearing the moment Phase-2-revisit adds them.
  * **[pending Phase-2-revisit]** `schema_compat_check` (ADR 008):
    fails on candidate breaking schema change without
    `# evolution: breaking` annotation. (Listed here since the
    check itself is a Dagster surface; the implementing module
    lands in the Phase-2-revisit ticket set.)
  * **[pending Phase-2-revisit + P3]** `erasure_cleaning_sweep`
    (ADR 007): scheduled Dagster job that rebuilds materialised
    derivatives downstream of erasure batches; bounds the
    staleness window.
  * **[pending Phase-2-revisit + P3]** `classification_change_sweep`
    (ADR 006): sensor-triggered job that re-evaluates the PII
    labelling decision system when a classification module
    changes; rewrites masking policies; emits a per-table report.

**Out of scope.**
* Multi-jurisdiction policy versioning (Phase 4).
* Audit-trail-aware rules (Phase 5).

**Done conditions.**
1. An ops/analyst user answers "what produced this contract?" via
   the Dagster UI alone, without engineer assistance.
2. All Phase 2 dbt tests are now Dagster asset checks running
   continuously, not only at deploy time.
3. A planted regression — e.g., a feature pipeline silently
   missing a column — is caught by an asset check inside one
   nightly cycle, not in the next compliance review.

---

## Phase 4 — Multi-jurisdiction at scale: versioned policy bundles, replay

**Status: not started.** ADR 008 (multi-version coexistence)
establishes the precondition; replay infrastructure itself is
unstarted.

**Frame.** The categorical insight that `Governance` is a Monoid
becomes a product feature: every contract carries an explicit
governance version; jurisdictions are interchangeable carrier
choices in a bundled policy; the system can replay historical
proposals against a new policy version to answer "what would have
happened?"

**In scope.**
* `decision_releases` table: each row is a versioned bundle of
  decisions (governance and guardrail combined), signed and
  immutable. (Generalises "governance bundle" — bundles
  versioned together include both monoids' decision lists.)
* Every `contracts` row carries a `decision_version` foreign key.
* Per-jurisdiction Snowpark UDF instances that are nothing more
  than `compose(federal, state[X], internal_governance,
  internal_guardrail)`; adding a new state is a one-file change.
* Replay job:
  `replay(proposals, decision_version) → contracts'` for
  retrospective analysis.
* Carrier-internal bundles (a separate namespace for
  non-regulatory rules, both governance and guardrail) composed
  alongside the regulatory ones.
* Two-person rule on changes to regulatory bundles, enforced via
  branch-protection plus an `OWNERS` file.
* The **DMN/FEEL authoring surface** (per ADR 004's S2): actuaries
  and underwriters author decision tables in a DMN modeller
  (Camunda, Trisotech) with FEEL cell expressions; a build step
  compiles each table into a `Decision[M]` (with `M` determined
  by hit policy) and registers it alongside the
  Python-authored decisions. DRDs of related tables compile to
  co-Kleisli composites. Python remains the engineering authoring
  surface; DMN is added because Phase 4's multi-party authoring
  makes its visual-modeller payoff concrete.
* A round-trip test in CI (per ADR 004's DMN-E6): Python decisions
  export to DMN; re-import; behaviour identical on a fixture set.

**Out of scope.**
* Probabilistic outputs (Phase 5).
* Rules that inspect audit trails (Phase 5).

**Done conditions.**
1. Adding a new jurisdiction (e.g., Texas) takes < 1 day of work
   and 0 architectural changes.
2. Replay answers "with today's decision bundle, how many of last
   quarter's approved contracts would have been rejected, and how
   would the guardrail distribution have shifted?" as a single
   SQL query against the replay output.
3. A bundle-release diff is reviewable by compliance staff in
   their preferred form (Python predicates, DMN tables, or both)
   and carries a version bump that propagates automatically to
   every newly-issued contract.
4. At least one production rule has been authored end-to-end in
   DMN and one in Python within the same release; both pass the
   round-trip equivalence test.

---

## Phase 5 — Distributions and audit-aware governance (research)

**Status: not started.** Research-grade extensions; criteria
exploratory.

**Frame.** Implements the Outlook section of `math.tex`. Learner
codomains lift from point estimates to distributions (Giry monad
analog). Rules can inspect not only a `Proposal` but its full audit
trail. The `Governed` comonad's `extend` and `duplicate` become
instrumental rather than incidental.

**In scope.**
* Distribution-valued predictions: e.g., a credibility learner's
  `implement` returns a posterior, not just a posterior mean.
* `AuditTrail(Proposal)` type: training-set provenance, learner
  state at scoring time, governance version applied.
* Rules over `(Proposal, AuditTrail)`:
  * "Reject if the posterior variance exceeds threshold."
  * "Audit if the learner's training history shows distribution
    drift."
  * "Require human review if the proposal sits more than 3σ from
    the training distribution."
* Optional: explicit Para/Optic encoding of learner state, enabling
  lens-style composition.
* Optional: comonad-transformer-shaped layered governance with
  cross-layer interaction (e.g., a federal rule that sees the
  state-level outcome before deciding).

**Out of scope.** Open research; criteria are exploratory.

**Done conditions.**
1. At least one variance-aware rule is in production.
2. At least one audit-trail-aware rule is in production.
3. A short retrospective (paper or post) articulates what the
   comonadic structure actually buys, with examples drawn from
   production.

---

## Mapping of suggestions to phases

| Suggestion | Phase |
|---|---|
| `Decision[M]` substrate with `Monoid[M]` protocol (ADR 004) | 0 |
| `M = list[Violation]` Governance instantiation (ADR 005) | 0 |
| Pydantic `Proposal`/`Contract` types | 0 |
| Convention-based `Contract` abstraction barrier | 0 |
| Public/internal API hygiene (`__all__`, `_`-prefix, contributing rule) | 0 |
| Reproducibility-seed discipline | 0 |
| Engineering toolchain (ruff + black + mypy + lockfile + pre-commit + CI) | 0 |
| Test-as-documentation: `demo()` per example module | 0 |
| License + SPDX headers | 0 |
| Local-first dev loop | 0 |
| Categorical-correspondence annotation, CI-enforced | 0 |
| Property tests for Learner laws | 1 |
| Hypothesis tests for governance conjunctivity | 1 |
| Monoid-law property tests per registered `Monoid[M]` (ADR 005) | 1 |
| Centralised Hypothesis strategy library (`tests/strategies.py`) | 1 |
| Per-learner correctness smoke tests on a fixture | 1 |
| Performance sanity ceiling (5 s/test, 60 s suite) | 1 |
| Polars/DuckDB local feature engineering | 1 |
| Append-only observation table; SQL-derived state | 2 |
| Pydantic ↔ dbt source-contract generation | 2 |
| Snowpark vectorised UDF parameterised by `M` (ADR 004) | 2 |
| Decision-payload `(admitted, m)` persisted on contract row | 2 |
| Cortex extraction at the boundary, with budget guard | 2 |
| Lightweight Python harness as orchestrator | 2 |
| Defer Dagster | 2 (deferral) → 3 (adoption) |
| Rejection analytics tables (queryable basics) | 2 |
| Dagster Software-Defined Assets | 3 |
| Asset checks for governance invariants | 3 |
| Asset checks for guardrail-distribution stability (ADR 005) | 3 |
| First production Guardrail (additive risk score) (ADR 005) | 3 |
| Joint Governance × Guardrail product-monoid admission | 3 |
| Cortex spend asset checks | 3 |
| Rejection analytics surfaced for ops | 3 |
| Cortex-based rejection-letter generation | 3 |
| Versioned decision-release bundles (governance + guardrail) | 4 |
| Per-jurisdiction UDFs by composition | 4 |
| DMN/FEEL authoring surface (ADR 004 S2) | 4 |
| Python ↔ DMN round-trip equivalence test | 4 |
| Replay infrastructure | 4 |
| Two-person rule on regulatory bundles | 4 |
| Distribution-valued learner outputs | 5 |
| Audit-trail-aware rules | 5 |
| Comonad transformers for layered governance | 5 |
| Para/Optic encoding of learner state | 5 |

Every architecture-review suggestion has a phase home.

---

## What is not yet in any phase

The plan above concentrates on the categorical mathematics, its
mapping to Snowflake/Python primitives, and the orchestration
around that. Production systems carry several other concerns that
the plan does not yet cover and which deserve their own decisions.
Each of these likely merits an ADR before the corresponding phase
ships.

**Reading note.** Items struck through (~~like this~~) have been
fully discharged by an ADR or implementation; they are kept in
the list so a reader can see the original gap audit, not as
outstanding work. Partially-discharged items remain in normal
weight with their "*Partially discharged / Still open*" notes
intact.

1. **Data quality and freshness of inputs.** The plan covers how
   data flows through; not how to detect when upstream sources
   break. Schema validation, freshness SLAs, distribution
   monitoring (Great Expectations, Anomalo, custom SQL checks).
   For learners that drift with input quality, this is upstream of
   every guarantee we make. *Partially discharged:* schema
   validation and quarantine in ADR 008; freshness SLAs in Phase 3
   asset checks. *Still open:* distribution monitoring of upstream
   inputs (the "is this batch like the training distribution"
   question, distinct from output guardrail-stability).
2. **Model performance monitoring** (distinct from governance).
   "The model is running" ≠ "the model is any good." Calibration,
   prediction-interval coverage, holdout accuracy by cohort. For
   pricing, miscalibrated severity costs money even if every
   contract passes governance. *Likely needed by Phase 3.*
3. **Backtesting and shadow deployment.** Before promoting a new
   learner or a new policy version, run it on N quarters of
   history; compare contracts, rejections, financial outcomes.
   Phase 4 implements *replay for governance*; the analogous flow
   for *learners* is not in the plan. *Likely needed by Phase 4.*
4. ~~**PII and sensitive-data handling.** Insurance data is
   regulated (financial PII, HIPAA-adjacent for health products,
   GINA for genetic information). Encryption at rest, dynamic data
   masking, row access policies, audit logging.~~ **Discharged by
   ADR 006 (PII Handling) and ADR 007 (Right-to-Erasure)
   2026-04-30.** Implementation is the Phase-2-revisit ticket set;
   production data flow is gated on it.
5. **Data retention and disaster recovery.** Snowflake `TIME
   TRAVEL` retention is bounded (default 1 day; max 90 with
   Enterprise edition). Long-term archival (`FAILSAFE`, S3
   Glacier), point-in-time recovery, retention policy for
   regulated artefacts (contracts, audit logs). Especially
   load-bearing for Phase 4's replay claims. *Likely needed by
   Phase 4.*
6. **Cost observability.** Snowflake credits, Cortex tokens,
   Dagster compute, storage growth. Budget alerts, cost
   attribution by pipeline stage, per-run cost recorded with run
   metadata. Without active management, cost surprises everyone
   late. *Useful at Phase 2; required by Phase 3.*
7. **Service-level objectives and on-call.** "Down" is not yet
   defined. Latency SLOs on validation, freshness SLOs on
   contracts, alerting wiring, runbooks, on-call rotation. Phase 3
   gestures at this; it deserves its own document. *Required by
   Phase 3.*
8. ~~**Schema evolution.** The Pydantic `Proposal` will grow fields
   over time. How do you version the schema such that old
   contracts remain interpretable? `governance_version` solves
   this for policy; the analogous mechanism for proposal/contract
   schema is not yet in the plan.~~ **Discharged by ADR 008
   (Schema and Contract Evolution) 2026-04-30.** Implementation
   is in the Phase-2-revisit ticket set.
9. **Incident response.** When a bad contract slips through (it
   will, eventually), what is the recovery? Quarantine table?
   Reconstructing active governance at issue time? The replay
   infrastructure (Phase 4) supports forensic analysis, but
   incident playbooks need their own work. *Required by Phase 3
   onward.*
10. **Governance of governance.** Who can change a rule? Two-person
    review is in Phase 4; full audit trail of policy changes (who,
    when, why, approved by whom) needs explicit design. *Required
    by Phase 4.*
11. **Documentation strategy.** Architecture docs (have);
    runbooks (need); onboarding (partial); API/contract docs for
    downstream systems (need). Phase 0's "30 minutes to green" is
    a start. *Continuously needed.*
12. **Performance budgets and regression tracking.** Without an
    explicit per-stage performance budget, regressions accumulate
    silently. Set targets (e.g., "validation latency < 1s p95"),
    monitor, alert. Phase 3 has the infrastructure (asset checks);
    the budgets and alerts are policy, not infra. *Required by
    Phase 3.*
13. **A/B and shadow deployment of learners.** Distinct from
    backtesting (#3): a new learner version runs alongside the old
    one without binding contracts; outputs compared online before
    promotion. *Useful at Phase 3; required by Phase 5.*
14. **Data contracts with upstream producers.** If raw data comes
    from a claims system, an underwriting system, or an external
    feed, what guarantees do we have? Schema breaks upstream are a
    common incident vector. *Partially discharged by ADR 008 §5
    (consumer-side ingest validation with quarantine as
    operational baseline; bilateral dbt contracts as architectural
    target).* Implementation of the consumer-side baseline is in
    the Phase-2-revisit ticket set; bilateral contracts with
    producers remain open and require producer-team engagement.
15. **Open-source posture.** Whether the framework is to be
    published under an open licence, alongside an academic paper,
    or kept internal. Influences ABI stability, public docs, and
    naming conventions. *Strategic, not phase-bound.*

These are not architectural choices about how to model the math;
they are operational and product choices about how to run a
regulated production system built on top of it. They belong in
their own ADRs, but the phased plan tells us roughly when each
becomes load-bearing.
