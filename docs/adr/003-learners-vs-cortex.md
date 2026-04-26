# ADR 003: Core Learners and the Role of Cortex AI

## Status
Accepted

## Context
Snowflake Cortex AI provides powerful, managed machine learning models and LLMs accessible via SQL and Python. Given that our data stack is centered on Snowflake, it is tempting to use Cortex AI for the `Learner` implementations.

However, the mathematical premise of the `hx` architecture (based on Fong, Spivak, and Tuyéras' *Backprop as Functor*) models machine learning as a symmetric monoidal category. To sequentially compose two learners $A \to B$ and $B \to C$, the downstream learner must be able to calculate a residual or gradient (the `request` map) and pass it back to the upstream learner.

## Options Considered

1. **Use Cortex AI for Core Learners:**
   * *Pros:* Fast to implement, fully managed, highly optimized infrastructure.
   * *Cons:* Cortex AI models are black boxes. They do not expose their internal state ($s$), their custom update loops, or their gradients. It is impossible to extract a `request` map from a Cortex classification function to pass upstream. This fundamentally breaks the ability to compose learners sequentially.
2. **Use Snowpark Python for Core Learners:**
   * *Pros:* Full control over the algorithmic logic. We can explicitly write the `implement`, `update`, and `request` maps in Python using tensor libraries or raw math, ensuring categorical composability.
   * *Cons:* We have to write and maintain the ML algorithms ourselves.

## Decision
We will manage the **core categorical Learners using Snowpark Python (Option 2)**, and use **Cortex AI only at the edges of the pipeline**.

Because we require algebraic transparency to compose our pipelines, the core mathematical loops (e.g., Bayesian credibility updates, gradient descent steps) will be explicitly written in Python and executed via Snowpark.

**Where we *will* use Cortex AI:**
Cortex AI will act as non-composable functors at the absolute boundaries of our architecture:
1. **The Source (Unstructured Extraction):** Using Cortex LLM functions (e.g., `EXTRACT_ANSWER`) during the dbt phase to convert messy PDFs and adjuster notes into the structured `Proposal` inputs ($A$) required by our formal learners.
2. **The Sink (Terminal Predictors):** If a user requires a standard ML model that does *not* need to propagate gradients upstream, Cortex ML functions can be used as terminal learners.
3. **The Post-Processor (Explainability):** Using Cortex LLMs to ingest the raw JSON violations produced by the Rego governance layer and translate them into human-readable rejection letters or internal underwriting guidance.

## Category Model Fidelity
This is the most directly faithful of the three ADRs to the Haskell
formulation:

* **Core learners** (`Cred`, `Lin`, …) are morphisms in
  $\mathsf{Learn}$: they expose `(implement, update, request)` and
  may compose sequentially or via $\otimes$. Snowpark Python is
  the runtime; the structure is preserved verbatim from the
  Haskell category.
* **Cortex calls** are non-composable functors at the boundaries of
  $\mathsf{Learn}$:
  $\mathrm{extract} \colon \mathrm{RawText} \to \Proposal$ at the
  source, and
  $\mathrm{explain} \colon \mathrm{Violations} \to \mathrm{Letter}$
  at the sink. They enter and leave $\mathsf{Learn}$ but do not
  compose with its morphisms. They are the "boundary functors"
  described in `math.tex`.

The one place this decision strains the math is **state
encapsulation.** Haskell's existential parameter $s$ is hidden
inside the `Learner` type; Snowflake state lives in tables that
anyone with `SELECT`/`UPDATE` can touch. The mathematical model
treats state as private to the learner; the production model
treats it as a shared resource. We accept this regression in
exchange for warehouse-native compute and mitigate it via:

1. **Snowflake row-access policies** on state tables, enforced via
   role.
2. **Append-only observation tables with derived state** (Phase 2
   of the implementation plan) so that "current state" is
   reproducible from history rather than mutable.
3. **A documented convention** that state tables are not direct
   query surfaces; downstream consumers read through views.

These mitigations are not equivalent to existential encapsulation,
but they recover most of its operational guarantees.

## Consequences
* **Positive:** The mathematical integrity and composability of the framework are preserved. We still leverage Snowflake's AI capabilities where they provide the most value (unstructured data processing and NLP) without compromising our functional architecture.
* **Negative:** Increased code maintenance for the core mathematical learners.
