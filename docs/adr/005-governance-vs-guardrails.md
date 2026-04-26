# ADR 005: Governance and Guardrails — Same Category, Different Monoids

## Status
Accepted (2026-04-25). Builds on ADR 004 (Decision Systems and
Authoring Surfaces). Engineering-facing companion to `math.tex` §VI
(*Decision Systems Parameterised by a Monoid*).

## Context

Three flavours of "rule" come up in everyday engineering and
product discussion that look superficially alike but operate in
materially different ways.

1. **Hard rejections.** Statutory or absolute: a proposal is or is
   not admissible. *"No protected-class rating factor."* *"Loss
   ratio cap not exceeded."* Multiple failures are reported
   together; admission requires that none have fired.

2. **Risk scoring.** Soft and additive: each rule contributes a
   non-negative score; admission depends on the total. *"High
   concentration in a single zip code adds 0.3 to risk score."*
   *"Newly licensed driver adds 0.2."* A middle band routes to
   human review.

3. **Severity-flagged escalations.** Soft with a worst-element
   shortcut: a single rule may declare a proposal unfit even if
   the total score is acceptable. *"Any felony conviction in last
   3 years routes to senior underwriting."*

Without a shared vocabulary, teams give these distinct names
(*validations*, *scoring*, *checks*, *guardrails*) and duplicate
plumbing: separate Python modules, separate UDFs, separate
persistence, separate ops dashboards. Each team's choice is
locally reasonable; the cross-team result is fragmentation.

ADR 004 establishes the unified mathematical substrate: every
flavour above is a `Decision[M]` valued in some monoid `M`, with an
admission predicate `adm: M → bool`. This ADR records the
engineering vocabulary, the choice criteria, and the operational
practice that follows.

## Definitions

* **Governance.** A decision system valued in the free monoid on
  violations: `M = list[Violation]` with `adm(m) = (m == [])`. Hard
  rejections; conjunctive composition.

* **Guardrail.** A decision system valued in any other monoid with
  a thresholding (or thresholding + worst-element) admission.
  Common shapes:

  | Use | `M` | `combine` | `empty` | `adm` |
  |---|---|---|---|---|
  | Additive risk score | `float` | `+` | `0.0` | `m < cap` |
  | Score + worst severity | `(float, Severity)` | `(+, max)` | `(0, ⊥)` | `s < cap ∧ sev < CRITICAL` |
  | Score + advisories | `(float, list[Recommendation])` | `(+, ++)` | `(0, [])` | `m.score < cap` |

* **Joint decision system.** A decision system valued in the
  product monoid `list[Violation] × M_guardrail`, with admission
  the conjunction of components.

These three names cover the practical surface; the categorical
unification is `math.tex` §VI.

## When to use which

The choice is **not about authoring style** (Python vs. DMN — that
is ADR 004's territory). It is about the algebra of the decision
itself.

Use **Governance** when:
* The rule expresses a binary admit/deny condition.
* The source is statute, regulation, or a hard internal cap.
* Multiple failures of the same kind should *all* be reported
  together (an underpriced contract that is also overcovered should
  reject for both reasons; a regulator must be told about both).

Use a **Guardrail** when:
* The decision yields a graded output (a score, a flagged severity,
  a recommendation).
* Multiple rules of similar kind should *aggregate* — sum,
  maximum, concatenate — rather than each fire independently.
* Admission depends on *threshold comparisons* on the aggregate,
  not on whether any rule fired.

Use a **Joint** decision system when both kinds apply, which in
production they almost always do. The same UDF run handles both;
the same `(admitted, m)` payload records each.

A useful rule of thumb: *if the right answer to "what if two of
your kind both apply" is to list both reasons, it is governance;
if the right answer is to combine them somehow, it is a guardrail.*

## Code organisation

The framework treats Governance and Guardrails as monoid choices
on the same substrate. Engineering practice should reflect this.

* **One module per monoid choice**, not one module per "kind of
  rule." E.g., `monoids/violations.py`, `monoids/risk_score.py`,
  `monoids/product.py`. Each module exports the monoid (`empty`,
  `combine`) and the matching `adm`.
* **Rule modules export `Decision[M]` for a specific `M`,**
  importing the monoid they target. A federal-rules module might
  export `list[Decision[list[Violation]]]`; a concentration-
  guardrail module might export `list[Decision[float]]`.
* **The validation UDF is parameterised by `M`.** One Snowpark UDF
  *implementation* serves both flavours, swapping monoid + `adm` at
  registration time. There are several registered *instances*, one
  per active monoid (or one per joint product monoid).
* **The output column `m: M` is part of the contract record**,
  alongside the boolean admission. Downstream queries can ask
  *"what was the risk score?"* and *"what violations fired?"*
  without re-running the rules.
* **Combined regimes use the product monoid module.** A
  per-jurisdiction registered UDF instance evaluates the joint
  decision system in one pass.

## Operational considerations

Differing algebras imply differing operational treatments.

* **Governance violations** belong in a per-violation analytics
  table with one row per `(contract_id, rule_name)` pair, queried
  for *"how often does each rule fire?"* and *"are we rejecting
  more on rule X month over month?"*
* **Guardrail outputs** belong in a per-decision analytics table
  with one row per contract carrying the `m: M` payload, queried
  for *"distribution of risk scores,"* *"median score by zip,"*
  *"outliers above 0.9."*
* **Joint decisions** persist both: violations as a side table,
  guardrail payload as a column on the contract.
* **Asset checks (Phase 3+)** treat the two differently:
  * A *governance check* is "no row in `contracts` has any
    active-rule violation."
  * A *guardrail check* is "the distribution of guardrail scores
    has not drifted by more than X this week."
* **Audit trails** record both. Which violations fired (governance)
  *and* which guardrail values were produced; the latter is
  especially important when a threshold is later adjusted and we
  want to know what would have happened.

## Category Model Fidelity

This ADR is the engineering-facing projection of `math.tex` §VI
(*Decision Systems Parameterised by a Monoid*). Specifically:

* **Governance** here = the case `M = List(Violation)` with
  `adm(m) = (m = [])`.
* **Guardrail** here = any other choice of `M` with a thresholding
  `adm`.
* **Joint decision system** here = the product monoid construction
  in §VI's *Joint governance and guardrails* worked instance.

The Generalised Static Admissibility theorem (`math.tex` Theorem 14)
applies uniformly: the abstraction barrier on `Contract` holds for
Governance, Guardrails, and Joint decision systems alike, by the
same argument and with no special-casing.

## Consequences

* **Positive.** Engineers and product staff share a vocabulary
  whose distinctions are meaningful. The framework absorbs both
  flavours without architectural separation. Adding a new guardrail
  is the same kind of change as adding a new governance rule: a new
  `Decision[M]` in the relevant module.
* **Positive.** Operational analytics distinguish the two cleanly
  because their algebras differ; ops users can ask the right
  question of each.
* **Negative.** The substrate exposes a `Monoid` protocol that is
  informal at the type-system level. Property tests for monoid laws
  (associativity, identity) are required and must ship with each
  new monoid module.
* **Negative.** A team unfamiliar with the framework may invent a
  fourth ad-hoc category — *warnings*, *soft rejections*,
  *advisories* — rather than placing it in the existing taxonomy.
  This ADR exists in part to prevent that; a periodic review of
  rule modules is recommended to ensure new rules find their proper
  monoid home.
