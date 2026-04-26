# ADR 002: Orchestration — Phased Adoption Toward Dagster

## Status
Accepted (revised 2026-04-25).

## Context
Our architecture coordinates multiple distinct execution
environments:
1. `dbt` for SQL feature engineering and data preparation.
2. `Snowpark Python` for executing the Learner pipelines
   (implement, update, request).
3. `Snowpark UDFs` for governance validation (per ADR 001).

These steps must run in the right order, with awareness of state
and freshness, ideally with first-class lineage that non-engineers
can navigate.

## Options Considered

### 1. Snowflake Tasks & Task Graphs
* **Pros:** Native to Snowflake; no external infrastructure; cheapest
  to operate at small scale.
* **Cons:** Imperative, task-shaped mental model; limited integration
  with `dbt`; not testable outside a deployed Snowflake account; no
  native asset/lineage tracking.

### 2. Lightweight Python harness (`pipeline.py` + cron / GitHub Actions)
A small Python file that calls `dbt run`, then `snowpark <udf>` in
sequence, scheduled by GitHub Actions, cron, or a Snowflake Task
wrapping a stored procedure.

* **Pros:** No new dependencies. Trivial to read, debug, and operate.
  Fully local-testable. Onboards in an afternoon. Identical
  invocation in dev, CI, staging, and prod.
* **Cons:** No first-class lineage, no asset state tracking, no UI
  for ops users, no asset checks. Reaches its limits when the
  pipeline graph grows past a handful of nodes or when ops/analyst
  users need to navigate "where did this contract come from?"
  without engineering help.

### 3. Dagster
* **Pros:** Software-Defined Asset model aligns with categorical
  thinking (assets-as-objects, computations-as-morphisms, asset
  checks-as-governance). First-class `dbt` and Snowpark integrations.
  Excellent local-test story. UI exposes lineage to non-engineers.
* **Cons (concrete, not gestural):**
  * Webserver, daemon, run launcher, code locations, sensors,
    schedules to run and monitor.
  * SSO + secret management to Snowflake.
  * Upgrade cadence (Dagster releases roughly monthly; non-trivial
    changes occasionally land in minor versions).
  * Onboarding: ~1 week for engineers; longer for ops/analyst users
    to navigate the UI confidently.
  * The asset-graph mental model is its own learning curve and
    rewards investment.

### 4. Prefect / Airflow
Mentioned for completeness; both viable; neither matches Dagster's
asset-graph alignment with our categorical model, and both bring
similar operational footprints. Not pursued.

## Decision
We adopt orchestration in **two phases**.

### Phase A — MVP and early production
Use **Option 2: a lightweight Python harness.** A single
`pipeline.py` invokes `dbt run` then the Snowpark validation UDF in
order; runs locally for development; runs in CI for staging; runs
as a scheduled GitHub Action (or Snowflake Task wrapping a Python
stored procedure) in production.

Rationale: the pipeline graph at this stage is small. Operational
cost should match operational benefit. Adopting Dagster before we
feel the pain it solves premature-optimises for problems we do not
yet have, and trains the team in a tool whose payoff arrives only
later.

### Phase B — Scale and observability
Migrate to **Option 3: Dagster** when *any* of the following hold:

1. The pipeline graph exceeds ~10 distinct asset types and
   non-engineers ask "where did this come from?" on a regular
   cadence.
2. We need asset-level lineage to answer governance/audit
   questions (e.g., "which feature pipeline produced the data the
   model trained on at the time this contract was issued?").
3. We need first-class asset checks running continuously, rather
   than as one-shot tests in CI.
4. Multiple teams contribute pipeline code and need a shared
   catalogue.

This migration is anticipated, not feared: the Phase A harness is a
thin imperative wrapper over the same SQL/Snowpark calls Dagster
would issue declaratively. Migration is an asset-graph rewrite, not
a re-architecture.

## Category Model Fidelity
Dagster's Software-Defined Asset model has a clean categorical
reading:

* **Objects:** asset *types* (e.g., `Proposal`, `LearnerState`,
  `Contract`).
* **Morphisms:** asset definitions — computations producing one
  asset type from others.
* **Composition:** the asset graph itself; Dagster materialises
  paths through it.
* **Identity:** trivial pass-through assets (rare in practice but
  available).
* **Asset checks:** predicates on derived assets, structurally
  identical to governance rules on proposals — both are co-Kleisli
  arrows from a context-laden value to `Pass + Failure(violations)`.

This is why we name Dagster as the destination: its native
abstractions echo the math we have already worked through in
`math.tex`. A lightweight Python harness (Phase A) preserves the
*underlying* graph but does not expose it as a first-class object.
We accept this temporary fidelity gap because the graph is small
enough that ad-hoc readability suffices, and we revisit when it is
not.

## Consequences

### Phase A
* **Positive.** Minimum viable orchestration. Matches the actual
  size of the pipeline. Engineers move fast; ops cost is near zero.
  The same `pipeline.py` runs everywhere; no environment skew.
* **Negative.** No lineage UI, no continuous asset-check infra; we
  rely on tests, conventions, and small-graph readability.

### Phase B
* **Positive.** Lineage, observability, and asset checks graduate
  to first-class concerns. Non-engineers gain self-service
  visibility. Asset checks formalise invariants we previously
  relied on convention to enforce.
* **Negative.** Dagster's operational footprint, paid only when
  its value is clear.
