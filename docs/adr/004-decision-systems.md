# ADR 004: Decision Systems and Authoring Surfaces

## Status
Accepted (2026-04-25). Supersedes the *framing* of ADR 001 in part:
its substrate decision (a Python rule evaluator running in a
Snowpark vectorized UDF) stands and is generalised here. Its
exclusive Python-vs-Rego framing is replaced by one that names
authoring surfaces independent of the runtime substrate.

## Context

Two intuitions emerged during architecture review that this ADR
records and acts on.

**1. Industry standard for insurance decisioning is DMN/FEEL.**
The OMG's Decision Model and Notation (DMN), with its companion
expression language FEEL (Friendly Enough Expression Language), is
the operative standard in carrier underwriting, claims, and
rate-making. DMN decision tables natively express scored decisions
via `Collect` hit policies with aggregators (`Sum`, `Min`, `Max`,
`Count`, `Aggregate`). Decision Requirements Diagrams (DRDs)
compose decisions via DAGs that mirror co-Kleisli composition.
Visual modellers (Camunda, Trisotech, OpenRules) make the format
approachable to actuaries and underwriters. Auditors and
regulators recognise it.

**2. Governance and Guardrails are the same category, parameterised
differently.** The current Haskell formalism's `Governance(P) :=
List(Rule_P) × List(Tag)`, with rules valued in `1 + Violation`, is
a *specialisation* of a more general object: a *decision system*
valued in some monoid `M`. Governance is the case `M =
List(Violation)` with admission predicate "is `M` empty";
Guardrails are the case where `M` is a richer monoid (an additive
risk score, a worst-severity max-monoid, a product of scores and
advisories) with admission predicate a thresholding function on
`M`. Both are co-Kleisli arrows over the Env comonad of decision
lists, differing only by the monoid carried.

These two intuitions interact: DMN tables naturally produce
M-valued outputs (where `M` is determined by hit policy), and DRDs
express the co-Kleisli composition of M-valued decisions. The
categorical generalisation gives DMN its right place in the
architecture and unifies Governance with Guardrails.

## Substrate (the runtime decision)

The runtime substrate is unchanged from ADR 001 in shape, and
generalised in type:
**a vectorized Snowpark UDF evaluating `Decision[M]` over a
partition of proposals**, where

```
Decision[M]       = Callable[[Proposal], M]
DecisionSystem[M] = list[Decision[M]]
```

and `M` is a monoid. Aggregation across a list of decisions is by
`M`'s `<>` operation; admission of a contract is by a fixed
predicate `adm: M → bool`.

This substrate decision was implicit in ADR 001 (Python `Rule = P
→ Optional[Violation]` is a `Decision[List[Violation]]` under
list-concatenation, with `adm = (m == [])`) and is now stated
explicitly so that other authoring surfaces can target it without
a runtime change.

## Authoring surfaces (the choices that depend on who authors)

Three authoring surfaces, ranked roughly by author proximity to
engineering.

### S1. Python predicates
A `Decision[M]` is a Python `Callable[[Proposal], M]` in version
control. This is the first-class authoring surface: native to the
codebase, fast iteration, full IDE/test/debug tooling.

* **Best for:** engineering-authored rules, fast iteration,
  anything that benefits from breakpoints, fixtures, and unit tests.
* **Adopted at:** all phases.

### S2. DMN decision tables (with FEEL cell expressions)
Decision tables authored in a DMN-aware modeller (Camunda,
Trisotech) and exported as XML. A build step compiles each table
into a `Decision[M]`; the hit policy determines `M`. A DRD over
several tables compiles into a co-Kleisli composite. The compiled
Python is what the UDF runs.

* **Best for:** rules authored by actuaries, underwriters, or
  compliance staff; rules that benefit from visual review; rule sets
  that need to be communicated to auditors or regulators in a
  recognised format.
* **Adopted at:** Phase 4 of the implementation plan, when
  multi-jurisdiction and multi-party authoring make the
  visual-modeller payoff concrete.

### S3. Imported policy bundles (e.g., DMN bundles from a regulator)
A regulator or partner publishes a DMN bundle that we honour
without rewriting. A build-time importer translates the bundle
into `Decision[M]` via the same compilation path as S2.

* **Best for:** policies whose authoritative source is external;
  cases where rewriting would diverge from the authoritative version
  over time.
* **Adopted at:** on demand; not built ahead of need.

### Considered, not adopted: Rego
Rego (Option 2 of ADR 001) remains a candidate authoring surface in
principle. We do not pursue it because:

* DMN occupies the "industry-standard declarative format" niche
  better for this domain — its risk-scoring affordances and auditor
  familiarity are substantial.
* Rego's hot-reload advantage (its remaining structural strength
  over Python) is a thin reed against the operational cost of
  carrying a second runtime in the UDF.
* The categorical Monoid is preserved by Python lists and by DMN
  `Collect` hit policies; Rego bundle import has no clean Monoid
  identity.

ADR 001's experimental plan E1–E7 remains valid as a generic
"is the declarative authoring surface worth its cost" rubric;
DMN-specific experiments are listed below.

## Decision

* **Adopt S1 (Python predicates) at all phases.** Production-grade
  decisions can be authored end-to-end in Python without any other
  tooling.
* **Adopt S2 (DMN/FEEL via build-time compilation to Python)
  starting in Phase 4** of `docs/PHASES.md`.
* **Reserve S3 (imported DMN bundles) for any specific regulator or
  partner** that publishes one.
* **Do not adopt Rego.** ADR 001's analysis remains valid; DMN is
  the better-positioned alternative for this domain.

## Substrate realisation

In code, the substrate is shaped roughly as follows. (Sketch only;
exact API to be settled in Phase 0 / Phase 2.)

```python
from typing import Callable, Protocol, TypeVar
M = TypeVar("M")

class Monoid(Protocol[M]):
    def empty(self) -> M: ...
    def combine(self, x: M, y: M) -> M: ...

Decision       = Callable[[Proposal], M]
DecisionSystem = list[Decision[M]]

def evaluate(system: DecisionSystem[M],
             p: Proposal,
             m: Monoid[M]) -> M:
    out = m.empty()
    for d in system:
        out = m.combine(out, d(p))
    return out
```

Concrete monoids in this framework:

| Use | `M` | `combine` | `empty` | `adm` |
|---|---|---|---|---|
| Governance (current) | `list[Violation]` | `+` | `[]` | `len(m) == 0` |
| Risk score | `float` (≥ 0) | `+` | `0.0` | `m < threshold` |
| Risk profile | `(float, Severity)` | `(+, max)` | `(0.0, ⊥)` | `score < cap ∧ sev < CRITICAL` |
| Joint | `list[Violation] × RiskProfile` | componentwise | `([], (0, ⊥))` | conjunction of components' `adm` |

The Snowpark UDF wraps `evaluate` over a Pandas Series of
proposals, returning `(admitted: bool, m: M)` per row. The
`m`-payload is persisted alongside the contract or rejection so
that downstream analytics can reason about why a decision came
out as it did.

## Category Model Fidelity

The substrate is the categorical generalisation of what ADR 001
describes for governance specifically. The Haskell `Governance(P)
:= List(Rule_P) × List(Tag)` is the special case `M =
List(Violation) × List(Tag)` with admission predicate "is the
violation list empty." The functoriality of `M ↦ W_M`
(`math.tex`, *Functoriality of W_{(-)}*) lifts: changing the choice
of monoid changes the comonad and the validator while preserving
the structure.

Both Governance and Guardrails are now formally one notion —
*decision systems valued in a monoid* — distinguished only by the
monoid choice and admissibility predicate. A separate ADR (005)
records this Governance-vs-Guardrails distinction for the
engineering reader; the corresponding mathematical development
appears in a new section of `math.tex`.

DMN slots into this picture as a notation: a DMN decision table is
a notation for a single `Decision[M]`, with `M` determined by hit
policy; a DRD is a notation for a co-Kleisli composite of decisions.
We do not treat DMN as an alternative substrate; we treat it as one
of several authoring surfaces over the same substrate.

## Experimental Plan: DMN authoring surface

ADR 001's E1–E7 transfer mutatis mutandis. The DMN-specific
experiments add:

### DMN-E1. Authoring velocity, actuary cohort
**Question.** Can an actuary or underwriter author a non-trivial
production rule in DMN faster than they could specify the same rule
for an engineer to implement in Python?

**Setup.** Three real rules from the carrier rule library, three
authors, randomised order. Measure time from prompt to a rule that
passes acceptance tests, plus reviewer-confirmed correctness.

**Decision threshold.** DMN authoring earns its place if the
authoring loop is at least 1.5× faster *and* round-trip correctness
is at least as high.

### DMN-E2. Reviewer comprehension
Same shape as ADR 001's E2; substitute DMN tables for Rego.

### DMN-E3. Composition fidelity (DRD vs. layered Python)
Implement a four-decision DRD (federal default → state override →
product carve-out → carrier exception) in both forms. Measure
authoring time, reviewer comprehension, and time to debug a planted
bug.

### DMN-E4. Vectorized UDF throughput
Compile a 50-decision DMN bundle to Python; benchmark in the
vectorized UDF on 10M proposals. Measure throughput, memory, and
cold-start latency.

**Decision threshold.** DMN-compiled-to-Python should be within
1.5× of hand-written Python at the same warehouse size; if not,
the compilation pipeline is the bottleneck and worth tuning.

### DMN-E5. In-UDF DMN evaluation (binary, optional)
Comparable to ADR 001's E5 for Rego.
**Question.** Can a Python DMN evaluator (`pyDMN`, `OpenRules`
Python bindings, or a bounded interpreter for the FEEL subset we
use) be loaded and run inside a Snowpark vectorized UDF?

**Decision threshold.** Hard prerequisite *only if* we want to
support runtime DMN evaluation (i.e., updating decisions without
re-deploying the UDF). For build-time compilation to Python
(the default), this experiment is informational.

### DMN-E6. Tooling round-trip
**Question.** Can we generate a DMN export from Python-authored
decisions for audit purposes, and import a DMN-authored decision
into the Python evaluator, without round-trip drift?

**Setup.** Author 5 rules in Python; export to DMN; re-import; run
both originals and re-imports on a fixture set; verify identical
behaviour. Author 5 rules in DMN; import; export; re-import;
verify.

**Decision threshold.** Round-trip drift in either direction is a
red flag; means the build pipeline is incomplete.

## Reconsider triggers

Revisit this ADR if:

1. **DMN-E1 fails.** Authoring in DMN is not faster for the target
   author cohort. We then keep S1 only and stop investing in the
   DMN pipeline.
2. **A regulator standardises on something else** (XBRL, an
   industry-SIG OPA bundle format, etc.). We re-run S3-class import
   against that format.
3. **A Python rule body grows beyond what expression-only evaluation
   can hold safely** (e.g., decisions want to query external data
   sources at evaluation time). We then need a more constrained
   evaluator on the substrate, not a richer authoring surface.

## Consequences

* **Positive.** Substrate is unified across Governance and
  Guardrails. Authoring surfaces are independent choices that can
  be added without runtime changes. The path to DMN/FEEL adoption
  is a build-time compilation pipeline, not a runtime port.
* **Positive.** Decision payloads (the `m: M` value) are first-class
  outputs of validation, not just side effects of a binary
  decision; this makes downstream analytics on decisions richer
  without further architectural work.
* **Negative.** A second authoring surface is a second build-time
  compiler to maintain. We pay this cost only when DMN-E1 justifies
  it (Phase 4 onward).
* **Negative.** The Python `Monoid` protocol is informal at the type
  system level; we rely on tests and conventions to guarantee
  associativity and unit laws. Property tests for these laws should
  ship with the Phase 0 / Phase 1 framework.
