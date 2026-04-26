# ADR 001: Implementation of Governance Validation

## Status
Accepted (revised 2026-04-25).

## Context
The Haskell categorical insurance project (`hx`) enforces a strict
boundary between `Proposals` and `Contracts` via a `validate`
function. Mathematically, a `Rule` is a function `P → 1 + Violation`
and a `Governance` is a `Monoid` of rules under list concatenation —
a structure that survives intact in any list-of-functions encoding.

In our architecture, every proposal must pass governance with zero
data movement out of Snowflake. The question this ADR settles is
*how* the predicates are expressed, evaluated, and composed.

## Options Considered

### 1. Python rule DSL inside a Snowpark vectorized UDF
A `Rule` is `Callable[[Proposal], Optional[Violation]]`. A
`Governance` is `list[Rule]`, composed by `+` or `itertools.chain`.
Rules are pure Python functions in version control. The vectorized
UDF receives a Pandas Series of proposals and returns a Series of
violation lists. Evaluation runs natively on virtual-warehouse nodes
alongside the data.

* **Pros**
  * **Direct, lossless port of the Haskell Monoid.** Composability
    is list concatenation; the categorical structure is preserved
    exactly.
  * **Zero new technology to operate.** Pure Python, packaged in a
    Snowpark UDF; no extra runtime, language, or evaluator.
  * **First-class developer ergonomics:** pytest, IDE autocomplete,
    breakpoints, `mypy`, coverage, debugger.
  * **Trivial multi-bundle composition** (`federal + california + internal`).
  * **Property tests are natural.** A parametric test asserting
    "any proposal satisfies `g1 + g2` iff it satisfies both" runs in
    milliseconds against tens of thousands of generated examples.
* **Cons**
  * Rule changes require UDF re-registration (vs. hot bundle reload).
  * Rule authorship is in Python — not as approachable to non-engineers
    as a declarative DSL would be.
  * Standard OPA tooling (Gatekeeper, Conftest, Playground) is
    inapplicable; if we want analyses they understand, we either
    write our own or translate.

### 2. Snowpark Python UDF with embedded Rego (regorus / WASM)
Same UDF wrapper, but rule evaluation is delegated to a Rego
evaluator (`regorus` Python bindings, or a WASM-compiled OPA)
loaded inside the UDF.

* **Pros**
  * Rego is a standard declarative policy language with rich
    deduction; well-suited to multi-tenant, role-aware, hierarchical
    policy.
  * External audit/compliance tooling (Gatekeeper, OPA Playground,
    Conftest) understands the bundle format.
  * Hot-swapping rule bundles without UDF re-registration is
    structurally straightforward.
* **Cons**
  * **Significant feasibility risk.** Running `regorus` or a WASM
    runtime inside Snowflake's sandboxed Python UDF, at production
    volume, on the current stable release, is unproven. The
    original ADR's "may require polyfill" understated this.
  * **The categorical Monoid does not surface naturally.** Rego
    bundles compose by `import` and package layout, not by `<>`;
    the `fed ⊕ state ⊕ internal` identity from the math weakens.
  * Adds a language and runtime that the team must learn, debug,
    and version.
  * For our actual rule library — Boolean predicates over a flat
    record — Rego's deduction engine is unused.

### 3. External OPA server (REST sidecar)
Standard OPA deployment.
* **Pros:** Standard, easy to debug.
* **Cons:** Breaks data locality. Per-row ingress/egress and
  network latency. Excluded for the reasons in the original ADR.

### 4. Snowpark Container Services running OPA
Stock OPA in an SPCS container inside Snowflake's perimeter.
* **Pros:** No ad-hoc embedding; full OPA toolchain available.
* **Cons:** Compute pools to manage; data still moves between
  warehouse and container nodes; OPA-only operational footprint.
* **Verdict:** Lower feasibility risk than Option 2 and worth
  treating as the realistic fallback if Option 2's experiments
  succeed on substance but fail on sandbox compatibility.

## Decision
We adopt **Option 1: a Python rule DSL inside a Snowpark vectorized UDF.**

The current rule library is a flat list of Boolean predicates over
a record type. Rego's value lives in features we do not need
(deduction graphs, role hierarchies, cross-tenant policy reuse),
and its costs (a new language, a new runtime, sandbox feasibility,
and a weaker categorical fit) are concrete. The Python DSL ships
faster, preserves the math, and matches the team we have.

This decision is **reversible**. The next two sections describe the
conditions that would prompt a re-evaluation and the experiments
that would have to clear specific bars before we'd switch.

## Reconsider Trigger
Re-evaluate this ADR if any of the following materialise:

1. **Compliance team takes over rule authorship.** Non-engineering
   authors with a stronger background in declarative rule systems.
2. **Cross-organization policy sharing.** A reinsurer, regulator,
   or partner provides policies in OPA bundle format that we'd
   otherwise translate by hand.
3. **Policy structure becomes deductive.** Rules of the form
   "if $A$ derives $B$ derives $C$ then $C$ holds" with substantial
   inference, rather than flat predicates.
4. **Hot-reload becomes a hard requirement.** Latency from
   merge-to-effect drops below the UDF re-registration cycle
   (typically a few minutes).

## Experimental Plan: Is Rego Worth It?
Before flipping to Option 2 (or Option 4), run the experiments
below in a dedicated spike. Each has a measurable success criterion;
none on its own is decisive, but together they describe what
"Rego earns its keep" would have to look like.

### E1. Authoring velocity (timed, qualitative)
**Question.** Does Rego make rule authorship faster for the
population that will write rules?

**Setup.** Pick 10 representative new rules drawn from real
regulatory text (e.g., a state's new auto-rating restrictions).
Have the same author implement each in Python and in Rego, freshly,
in random order. Measure time-to-correct (rule passes its own test
cases). If a non-engineer is in scope, repeat with a non-engineer.

**Decision threshold.** Rego wins if it is at least 2× faster on
median, *or* if non-engineers cannot reach correctness in Python
within a reasonable training budget but can in Rego.

### E2. Reviewer comprehension (qualitative)
**Question.** When the same rule is shown in both forms to a
compliance reviewer or external auditor, which form yields more
correct edge-case identification per minute of review?

**Setup.** Show 5 paired rules to (a) an internal compliance
reviewer, (b) an external auditor or legal counsel. Ask each to
list edge cases and whether each is or is not handled. Measure:
correctly-identified edge cases per minute.

**Decision threshold.** Rego wins if reviewers identify materially
more edge cases per unit time, or if review approval cycles
shorten by ≥30% in pilot use.

### E3. Layered composition complexity
**Question.** Does Rego's deduction engine pay off when policies
compose with conflict semantics?

**Setup.** Implement a deliberately tricky four-layer policy:
federal default + state override + product-line carve-out +
carrier exception. Measure code volume (LOC), tests required for
100% branch coverage, and time-to-debug a planted bug in each form.

**Decision threshold.** Rego wins if the deductive form is
materially shorter or faster to debug for the same correctness
guarantee.

### E4. Vectorized UDF throughput and memory
**Question.** Once running, which form is cheaper at warehouse
scale?

**Setup.** Validate 10M synthetic proposals against a 50-rule
policy in a single Snowpark UDF call, in each form. Measure
throughput (proposals/sec/credit), peak UDF memory, and cold-start
latency. Test on small (XS), medium (M), and large (L) warehouse
sizes.

**Decision threshold.** Python wins by default; Rego must beat it
by at least 1.5× at the same warehouse size to offset the
operational cost of carrying a second runtime.

### E5. Sandbox feasibility (binary, prerequisite)
**Question.** Can `regorus` (Python bindings) or a WASM-compiled
OPA actually be loaded, warmed, and called from inside a Snowflake
vectorized UDF on the current stable release?

**Setup.** Cold-start a UDF with the runtime preloaded; call it
1k times in a batch; observe error modes when sandbox restrictions
trigger (FFI, filesystem access, network egress). Re-run on a
fresh release of Snowflake to confirm robustness across upgrades.

**Decision threshold.** Hard prerequisite. If E5 fails, Option 2
is de facto unavailable and the comparison narrows to Option 1
vs. Option 4 (SPCS), which then needs its own set of experiments
around container provisioning, scaling, and cost.

### E6. Hot-reload cycle time
**Question.** From "rule change committed" to "validation uses new
rule in production," what is the wall-clock time in each form?

**Setup.** Time each path end to end. For Python: package, deploy,
re-register the UDF. For Rego: publish a new bundle and trigger a
reload inside the UDF.

**Decision threshold.** Rego wins if the gap exceeds an hour and
release-frequency expectations exceed once-per-business-day.

### E7. Versioning + diffing review
**Question.** Which form is more reviewable when policies change?

**Setup.** Take a real v1 → v2 policy diff in each form (e.g.,
adding three rating-factor restrictions). Show to a non-author
reviewer. Measure review time and reviewer-reported clarity (1–5).

**Decision threshold.** Inform but do not gate; integrate into E2.

### Aggregation
A switch to Option 2 is justified if **E5 passes outright** and
**either of the following holds**:

* E1 + E2 jointly indicate Rego authoring/comprehension wins large
  enough to plausibly amortise its operational cost (pre-registered:
  ≥40% time savings on E1, ≥30% comprehension lift on E2), or
* E3 indicates a deductive complexity threshold has been crossed
  that Python predicates can no longer carry without painful
  ad-hoc machinery.

Throughput (E4) and reload (E6) are tiebreakers, not justifications.

## Category Model Fidelity
The Haskell `Governance(P) := List(Rule_P) × List(Tag)` with
`<>` = list concatenation maps **one-to-one** to a Python
`list[Rule]` under `+`. The Monoid's identity (`mempty`) is `[]`;
associativity and unitality hold by Python list semantics.
Validation `validate : Governed_P P → List(Violation) + Contract(P)`
becomes the UDF
`validate(Proposal, list[Rule]) → list[Violation] | Contract`,
preserving the cokleisli arrow shape. The functoriality of
`M ↦ W_M` from monoid choices to comonad implementations
(see `math.tex`, *Functoriality of $W_{(-)}$*) lifts directly:
choosing a different list of rules gives a different validator;
the structure is preserved.

By contrast, Rego policy composition is **not a Monoid in the same
sense.** Bundle import is not associative-up-to-iso the way list
concatenation is, and Rego's `package`/`data` namespacing introduces
structure that has no analog on the Haskell side. A move to Option 2
would require us to either (a) constrain ourselves to a flat-bundle
discipline that simulates the Monoid, or (b) accept a structural
mismatch between math and implementation.

## Consequences
* **Positive.** Fastest path to production. Lowest operational
  surface area. Direct preservation of the categorical Monoid. Full
  Python tooling. The existing team is productive on day 1.
* **Negative.** No off-the-shelf policy tooling. Non-engineering
  rule authorship is not as approachable as a declarative DSL would
  be. Hot-reload requires UDF re-registration. If we eventually
  need Rego features, we pay a migration cost rather than a
  greenfield cost — a tradeoff we accept based on current rule
  complexity, with the experimental plan above as our trigger.
