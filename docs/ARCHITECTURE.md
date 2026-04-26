# Architecture: Categorical Insurance on Snowflake

This document outlines the architecture for porting the `hx` categorical
insurance framework from Haskell to a Python-centric modern data stack
built on Snowflake.

The architecture decisions behind each component are recorded in
`docs/adr/`; the staged rollout from a laptop MVP to this architecture
is in `docs/PHASES.md`. Unless otherwise noted, the diagram below
depicts the **Phase 3+ steady state**; earlier phases use a
lightweight Python harness in place of Dagster (per ADR 002) and may
not yet exhibit the DMN authoring surface or every monoid choice.

## System Architecture

The architecture maps the categorical concepts of the original Haskell
implementation — Learners as morphisms, decisions as co-Kleisli arrows
valued in a monoid `M`, validation as a static guarantee on contract
construction — into distributed data-engineering primitives.

<!--
<div align="center">
  <img src="./architecture-bloc-diagram.svg" width="80%">
</div>
-->

```mermaid
graph TD
    subgraph Dagster ["Orchestration (light harness in Phase 2; Dagster in Phase 3+, per ADR 002)"]
        direction LR
        TriggerDBT[dbt Assets]
        TriggerML[Snowpark ML Assets]
        TriggerGov[Validation Assets]
    end

    subgraph Snowflake ["Snowflake (Zero Data-Movement Execution)"]
        direction TB

        %% Data Sources & Prep
        Raw[(Raw Unstructured Data)]
        CortexExtract[Cortex AI: LLM Extraction]
        RawSQL[(Raw Tables)]
        DBT[dbt: Feature Engineering]
        Proposals[(Proposals)]
        Observations[(Observations<br/>append-only)]
        StateView[(Learner State<br/>derived view)]

        Raw --> CortexExtract --> DBT
        RawSQL --> DBT
        DBT --> Proposals
        Observations --> StateView

        %% Learners Category
        subgraph Learners ["Category of Learners (Snowpark Python)"]
            Learner["Learner = (s, implement, update, request)"]
        end

        Proposals --> Learner
        StateView --> Learner

        %% Decision systems parameterised by a monoid
        subgraph DecisionSubgraph ["Decision Systems (ADR 004): Decision m = p → m"]
            ValidateUDF["Snowpark Vectorized UDF: validate_M<br/>M ∈ {Violations, RiskScore, joint product, ...}"]
        end

        Learner --> ValidateUDF

        %% Co-Kleisli validation outputs
        Contracts[(Bound Contracts<br/>+ payload m)]
        Rejections[(Rejected Proposals<br/>+ payload m)]
        CortexExplain[Cortex AI: Rejection Explanations]

        ValidateUDF -->|adm m| Contracts
        ValidateUDF -->|¬ adm m| Rejections
        Rejections --> CortexExplain
    end

    %% Orchestration edges
    TriggerDBT -.->|Executes SQL| DBT
    TriggerML -.->|Executes Python| Learners
    TriggerGov -.->|Executes Vectorized UDF| DecisionSubgraph
```

## Concept Mapping

### 1. State (`s`)
*   **Haskell:** Hidden state in the `Learner` existential type.
*   **Python/Snowflake:** State is *derived* from an append-only
    `observations` table via a SQL view (Phase 2). "Current state" is
    reproducible from history rather than mutable in place; Snowflake
    `TIME TRAVEL` recovers state-at-time-T for free. This restores
    most of the categorical encapsulation of the Haskell existential
    `s` even though anyone with `SELECT` can read the derived view.
    See ADR 003's *Category Model Fidelity* section for the
    encapsulation regression we accept and the mitigations that
    contain it.

### 2. The Category of Learners
*   **Haskell:** Optic-like quadruples (`State`, `Implement`,
    `Update`, `Request`) composed sequentially and in parallel.
*   **Python/Snowflake:** Snowpark Python functions running natively
    on Snowflake compute nodes for forward passes (`implement`),
    parameter updates (`update`), and input gradients (`request`). For
    closed-form learners (Bühlmann credibility, GLMs) Snowpark Python
    is ergonomic; for substantive gradient learners we expect to read
    state from Snowflake, train in external Python (PyTorch / JAX)
    where tensor work is most ergonomic, and write the updated state
    back. The categorical "category of learners" lives at the type
    level uniformly; only the runtime varies.

### 3. Decision Systems and Validation
*   **Haskell:** A `Decision m p = p -> m` for monoid `m`, with a
    `validate_{m, adm}` co-Kleisli arrow that returns a constructed
    `Contract` when `adm(aggregate(decisions, p))` holds and the
    aggregate `m` (in the left summand) otherwise. Governance is the
    `m = [Violation]` instance with `adm(m) = (m == [])`; Guardrails
    are the case where `m` is a richer monoid (additive risk score,
    score-and-worst-severity product, …) with a thresholding `adm`.
    See `math.tex` §VI and ADRs 004 and 005.
*   **Python/Snowflake:** *One* vectorized Snowpark UDF
    *implementation* parameterised by `m`, registered as one or more
    *instances*, one per active monoid (per ADR 004). The UDF returns
    `(admitted: bool, m: m)` per row; both contracts and rejections
    persist the `m` payload alongside the boolean admission, so
    downstream analytics can reason about the decision without
    re-running the rules.

### 4. Authoring Surfaces for Decisions
*   **Python predicates** are the first-class authoring surface
    (ADR 004 S1; available from Phase 0). `Decision[m]` modules live
    in version control alongside the rest of the codebase, are tested
    in `pytest`, type-checked, and debuggable.
*   **DMN tables with FEEL** cell expressions are the additional
    authoring surface adopted in Phase 4 for actuaries, underwriters,
    and compliance staff (ADR 004 S2). A build step compiles each
    table into a `Decision[m]` (the hit policy determines `m`); a
    Decision Requirements Diagram of several tables compiles into a
    co-Kleisli composite. The compiled Python is what the UDF runs.
*   **Imported regulator/partner DMN bundles** (S3) are translated by
    the same compilation path on demand.
*   **Rego** was considered (ADR 001 original framing, then ADR 004
    once DMN entered the picture) and not adopted; DMN occupies the
    "industry-standard declarative format" niche better for insurance
    specifically.

### 5. Governance and Guardrails — Same Substrate, Different Monoids
*   **Governance** is the case `m = list[Violation]`,
    `adm = (m == [])`. Hard rejections; conjunctive composition.
*   **Guardrails** are decisions valued in any other monoid — an
    additive risk score (`m = float`), a score-and-worst-severity
    product, an advisory list — with a thresholding `adm` (per
    ADR 005). Both flavours run through the same UDF.
*   **Joint** decision systems use the product monoid, e.g.
    `m = list[Violation] × float`, with admission the conjunction of
    the components'. A single UDF call evaluates both.
*   In analytics, governance violations belong in a per-violation side
    table (one row per `(contract_id, rule_name)` pair), whereas
    guardrail outputs belong in the `m` payload column on the contract
    row. The differing algebras imply differing analytical surfaces.

### 6. Optics & Feature Engineering
*   **Haskell:** Pure functions mapping external types into learner
    input types `A`.
*   **Python/Snowflake:** `dbt` is used strictly for the
    forward-propagation of features. It shapes raw data into the
    `Proposal` formats expected by the learners. The `Proposal` schema
    is Pydantic at the Python boundary and a `dbt` source contract at
    the SQL boundary; the two are generated from one source so they
    cannot drift (Phase 2).

### 7. Orchestration
*   **Haskell:** In-memory execution or manual GHCi REPL steps.
*   **Python/Snowflake:** Per ADR 002, orchestration adopts in two
    phases. Phase 2 uses a *lightweight Python harness* (a single
    `pipeline.py` invoking `dbt run` and the Snowpark validation UDF
    in order, scheduled by GitHub Actions, cron, or a Snowflake Task).
    Phase 3 migrates to **Dagster** when the asset graph or the demand
    for ops-visible lineage justifies the operational footprint. Once
    in Dagster, dbt models, Snowflake state views, and Contract tables
    are first-class Software-Defined Assets, with asset checks running
    continuously to formalise the invariants — governance always
    satisfied on the `contracts` table; guardrail-score distribution
    within learned band; Cortex spend within budget.

### 8. Cortex at the Boundaries
*   `Cortex EXTRACT_ANSWER` (or similar) at the source converts
    unstructured inputs (PDFs, adjuster notes) into structured
    `Proposal` records — a "boundary functor" entering the category
    of learners, not a learner inside it.
*   `Cortex` post-processing of rejection payloads produces
    human-readable rejection letters from a violation list and the
    `m` payload — also a boundary functor; not composed with learners.
*   See ADR 003 for the discipline that keeps Cortex out of the
    categorical core. The reasoning, summarised: Cortex models do not
    expose a `request` map, so they cannot participate in sequential
    composition; we use them only at the inlet and outlet, where
    composition with learners is not required.

## References

* `docs/math.tex` — formal mathematical development, including §VI
  on monoid-parameterised decision systems and Theorem 14
  (Generalised Static Admissibility).
* `docs/adr/001-governance-locality.md` — original governance
  evaluation locality decision: Python rule DSL inside a Snowpark
  vectorized UDF, with experimental criteria for Rego.
* `docs/adr/002-orchestration-dagster.md` — phased orchestration:
  light Python harness → Dagster.
* `docs/adr/003-learners-vs-cortex.md` — discipline keeping Cortex at
  the boundaries.
* `docs/adr/004-decision-systems.md` — `Decision[M]` substrate;
  Python and DMN as peer authoring surfaces; Rego considered, not
  adopted.
* `docs/adr/005-governance-vs-guardrails.md` — Governance and
  Guardrails as monoid choices on the same substrate.
* `docs/PHASES.md` — staged rollout from MVP to this architecture.
