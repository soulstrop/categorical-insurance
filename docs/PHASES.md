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

| Phase | Frame | Runtime |
|------:|-------|---------|
| 0 | A working categorical pipeline on a laptop | Pure Python |
| 1 | Two learners, one real data source, laws verified | Python + Polars/DuckDB |
| 2 | Warehouse-native data and validation; training where ergonomic | dbt + Snowpark + Python harness |
| 3 | Lineage and asset checks visible to ops users | Dagster on top of Phase 2 |
| 4 | Multi-jurisdiction; versioned policy bundles; replay | Phase 3 + policy-release infra |
| 5 | Probabilistic outputs and audit-aware governance | Research-grade extensions |

---

## Phase 0 — MVP: a categorical pipeline on a laptop

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
   public function carries a one-line docstring naming the Haskell
   counterpart it implements.

---

## Phase 1 — Data: two learners, one real source, laws verified

**Frame.** The MVP grows up. A real (small) data source replaces
synthetic fixtures; a second learner exercises composition; property
tests verify the Haskell laws (associativity, identity, conjunctive
governance composition).

**In scope.**
* DuckDB- or Polars-backed local feature engineering, replacing
  fixture generators.
* A second learner: linear regression with online SGD (matches the
  `Lin` example in `math.tex`).
* Sequential composition (`compose`) and parallel product
  (`parallel`) implementations, exercised by tests.
* Property-based tests (Hypothesis) for:
  * `compose(g, identity) ≡ g` and `compose(identity, f) ≡ f`
  * `compose(compose(h, g), f) ≡ compose(h, compose(g, f))` up to
    observable behaviour
  * `p ⊨ G1 + G2 ⇔ p ⊨ G1 ∧ p ⊨ G2` (conjunctivity, ADR 001)
  * Monoid laws on the registered `Monoid[M]` instances
    (associativity, left/right identity) — required for every new
    monoid module per ADR 005.
* Validation outputs persisted as Parquet for downstream
  inspection.

**Out of scope.**
* Snowflake.
* Production data volumes.
* Multi-jurisdiction policy bundles (Phase 4).

**Done conditions.**
1. Hypothesis-based property tests pass in CI.
2. The second learner is added with no surgery to the framework
   (only a new module).
3. A real claims dataset (anonymised public, e.g., French TPL motor
   data) flows end-to-end to a Parquet contracts file.
4. The `compose` and `parallel` operations are documented with
   short examples in the README, naming the `math.tex` theorems they
   instantiate.

---

## Phase 2 — Warehouse: data and validation in Snowflake; training where ergonomic

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
* A *single* Snowpark vectorized UDF implementation parameterised
  by `M` (per ADR 004); registered as one or more *instances*, one
  per active monoid choice. The Phase 2 instance evaluates the
  Governance monoid `M = list[Violation]`.
* The UDF returns `(admitted: bool, m: M)` per row; the `m`
  payload is persisted alongside the contract or rejection so that
  downstream analytics can reason about the decision without
  re-running the rules.
* Observation table (append-only) and a SQL view that derives
  current learner state from history.
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

## Phase 3 — Asset graph: lineage and checks visible to ops

**Frame.** The pipeline graph that already exists implicitly in
Phase 2 becomes a first-class object via Dagster Software-Defined
Assets. Asset checks formalise the invariants we relied on
convention to maintain. Cortex generates human-readable rejection
letters. Non-engineers gain self-service lineage and freshness via
the Dagster UI.

**In scope.**
* Dagster project alongside the existing Phase 2 code; assets
  defined for raw → features → proposals → state → contracts /
  rejections.
* Asset checks for:
  * Every row in `contracts` satisfies the active governance
    bundle (re-runs the predicate; pages on mismatch).
  * Cortex token spend per run stays under budget.
  * Rejection rate per rule per day stays within a learned band
    (catches both new failure modes and rules that have stopped
    firing).
  * Guardrail-distribution stability: per-day distribution of the
    Phase 3 guardrail's `m` payload does not drift beyond a
    learned envelope (per ADR 005's operational practice).
* The first **Guardrail** in production: an additive risk score
  with thresholded admission, using the same `Decision[M]`
  substrate (per ADR 005). Concrete monoid:
  `M = float`, `combine = +`, `empty = 0`, `adm(s) = s < cap`.
* The validator runs as a **Joint** decision system in the product
  monoid `list[Violation] × float`, persisting both the violation
  list and the risk score on each contract row; admission is the
  conjunction of components' `adm`.
* SLA / freshness policies on key assets.
* Cortex-based `explain_rejection` step producing a draft
  human-readable letter from a `Violation` list and the guardrail
  payload.
* On-call runbook: top three failure modes and first-step
  responses.

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
| Local-first dev loop | 0 |
| Annotate categorical correspondence in docstrings | 0 |
| Property tests for Learner laws | 1 |
| Hypothesis tests for governance conjunctivity | 1 |
| Monoid-law property tests per registered `Monoid[M]` (ADR 005) | 1 |
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

1. **Data quality and freshness of inputs.** The plan covers how
   data flows through; not how to detect when upstream sources
   break. Schema validation, freshness SLAs, distribution
   monitoring (Great Expectations, Anomalo, custom SQL checks).
   For learners that drift with input quality, this is upstream of
   every guarantee we make. *Likely needed by Phase 2.*
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
4. **PII and sensitive-data handling.** Insurance data is
   regulated (financial PII, HIPAA-adjacent for health products,
   GINA for genetic information). Encryption at rest, dynamic data
   masking, row access policies, audit logging. None of the ADRs
   touch this. *Compliance will require a dedicated ADR before
   Phase 2.*
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
8. **Schema evolution.** The Pydantic `Proposal` will grow fields
   over time. How do you version the schema such that old
   contracts remain interpretable? `governance_version` solves
   this for policy; the analogous mechanism for proposal/contract
   schema is not yet in the plan. *Likely needed by Phase 2 and
   acutely by Phase 4.*
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
    common incident vector. *Useful at Phase 2; required by
    Phase 3.*
15. **Open-source posture.** Whether the framework is to be
    published under an open licence, alongside an academic paper,
    or kept internal. Influences ABI stability, public docs, and
    naming conventions. *Strategic, not phase-bound.*

These are not architectural choices about how to model the math;
they are operational and product choices about how to run a
regulated production system built on top of it. They belong in
their own ADRs, but the phased plan tells us roughly when each
becomes load-bearing.
