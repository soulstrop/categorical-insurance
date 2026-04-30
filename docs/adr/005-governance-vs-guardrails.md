# ADR 005: Governance, Guardrails, Visibility, and Labellings — Same Category, Different Monoids

## Status
Accepted (2026-04-25). Extended (2026-04-30) with the
**Visibility guardrail** (worked instance: erasure visibility, ADR 007)
and the **Labelling** decision flavour (worked instance: PII
classification, ADR 006). Builds on ADR 004 (Decision Systems and
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

* **Visibility.** A guardrail flavour valued in a *visibility
  lattice* with a *meet* monoid (most-restrictive wins). The worked
  instance is erasure visibility (ADR 007):

  | Element | Meaning |
  |---|---|
  | `Visible` | Row may be returned to any role authorised on the table. |
  | `RestrictedTo({R₁, …})` | Row may be returned only when the querying role is in the set. |
  | `Erased` | Row was tombstoned per ADR 007; not visible to general roles. |

  with `combine(x, y) = meet(x, y)` (more restrictive of the two)
  and `empty = Visible`. Admission is the per-query predicate
  `adm(m) = role_admitted(m, current_role())`. Each row's stored
  visibility value is the aggregate of all visibility decisions
  evaluated against it; the consumer-facing view filter is
  `validate`-equivalent over this aggregate.

* **Labelling.** A decision flavour valued in a monoid whose purpose
  is to *describe* its input rather than *gate* it. Admission is
  trivial (`adm(_) = True`); the carried value `m: M` is the output.

  | Use | `M` | `combine` | `empty` |
  |---|---|---|---|
  | PII classification | `dict[FieldName, Sensitivity]` | per-field most-restrictive merge | `{}` |
  | Regulatory regime tagging | `set[Regime]` | `∪` | `∅` |
  | Lineage attribution | `set[SourceTable]` | `∪` | `∅` |

  Labellings are not "guardrails that always admit" — the conceptual
  shift is real. Governance and Guardrails answer *"may this proposal
  proceed?"* Labellings answer *"what is true about this proposal?"*
  Both are decision systems valued in monoids; they differ in whether
  the output is a gate or a description.

These five names cover the practical surface; the categorical
unification is `math.tex` §VI. (Visibility and Labelling extend the
worked instances; the underlying theorem — Generalised Static
Admissibility — is unchanged for guardrails, and degenerate-but-true
for labellings whose admission is constantly `True`.)

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

Use a **Visibility** guardrail when:
* The decision is per-query rather than per-issuance: the same row
  may be visible to one role and not to another at the same instant.
* Multiple visibility-affecting decisions should aggregate via
  *meet* (most-restrictive wins), not sum or list-append.
* The mechanism is enforced at the consumer surface (a view filter)
  rather than at contract construction.

Use a **Labelling** when:
* The output is descriptive, not gating. A regulator audit asking
  *"which fields in this proposal are direct PII?"* expects a list,
  not an admit/deny.
* The decision composes the output rather than collecting reasons
  for a possible failure.
* Multiple rules contributing to the same output should *merge* via
  the monoid (set union, per-key most-restrictive, lineage union)
  rather than list-append.

A useful rule of thumb:
* If the right answer to "what if two of your kind both apply" is
  to **list both reasons**, it is governance.
* If the right answer is to **combine them numerically or by
  threshold**, it is a guardrail.
* If the right answer is to **take the more restrictive of the
  two**, it is a visibility guardrail.
* If there is no "may this proceed" question — only "what is true
  about it" — it is a labelling.

## What this framework does not cover

**Access control** (who is allowed to invoke a query at all) is
delegated to the warehouse policy engine — Snowflake DDM and Row
Access Policies, evaluated by Snowflake's planner at query plan
time. ADR 006 §5 records the choice. The categorical decision
substrate is the wrong layer for access control because:

* The "proposal" being decided over is `(User, Request)`, not
  `Proposal`. Forcing the type alignment buys nothing.
* Snowflake's policy engine evaluates at planner cost rather than
  our compute cost. Re-implementing the same evaluation in Python
  would be slower, less secure (we own more of the trusted compute
  base), and produce no property the regulator cares about.
* Access policies are authored in declarative SQL and are themselves
  reviewable artefacts; replicating them in `Decision[M]` form would
  add a translation step that diverges from the deployed reality.

The line drawn here is consistent with ADR 003's discipline keeping
Cortex out of the categorical core: not every rule-shaped concern
belongs in the same algebra. The test is whether the concern's
operational substrate is itself a rule engine; access control's is.

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

For Visibility and Labellings the analogous operational treatment:

* **Visibility values** belong on the row (`erased: bool` plus, in
  general, a `visibility: VisibilityM` column when richer states are
  in play). The consumer-facing view applies `adm` per query and
  filters; the underlying value persists for audit. *Asset checks*
  on visibility ask "are there rows where the visibility decision
  has drifted from expectation" — useful when a new restriction is
  introduced and we want to confirm coverage.
* **Labelling outputs** belong in *metadata-shaped* tables —
  `field_classification`, `lineage_attribution` — keyed by the
  thing being labelled (table + column for PII classification,
  table + dataset for lineage). They are usually small and rarely
  written; they support generators (the dbt YAML emitter for
  PII classification, lineage-aware compaction policies) rather than
  per-query reads. *Asset checks* on labellings ask "is every new
  field classified" or "did any field's classification change."

The same `Decision[M]` substrate; differing operational surfaces
because the algebras differ.

## Category Model Fidelity

This ADR is the engineering-facing projection of `math.tex` §VI
(*Decision Systems Parameterised by a Monoid*). Specifically:

* **Governance** here = the case `M = List(Violation)` with
  `adm(m) = (m = [])`.
* **Guardrail** here = any other choice of `M` with a thresholding
  `adm`.
* **Joint decision system** here = the product monoid construction
  in §VI's *Joint governance and guardrails* worked instance.
* **Visibility** here = a guardrail flavour where `M` is a
  *visibility lattice* with a *meet* monoid; admission is per-query
  rather than per-issuance. Erasure (ADR 007) is the worked instance.
* **Labelling** here = a decision flavour with trivial admission
  (`adm(_) = True`); the monoid value is the output, not a gate.
  PII classification (ADR 006) is the worked instance.

The Generalised Static Admissibility theorem (`math.tex` Theorem 14)
applies uniformly to Governance, Guardrails, Joint, and Visibility
decision systems alike, by the same argument and with no
special-casing — the abstraction barrier on `Contract` holds because
admission is a function of the monoid value. For Labellings the
theorem is degenerate-but-true: with `adm` constantly `True` every
proposal admits, and the abstraction barrier reduces to "the carried
label is whatever the labelling system computed." This is the
expected behaviour: a labelling does not refuse to construct a
contract; it *describes* the contract being constructed.

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
* **Positive (extension).** Adding the Visibility and Labelling
  flavours unifies four operational concerns under one substrate:
  governance (gating), guardrails (grading), visibility (filtering),
  classification (describing). Adding a new compliance regime — a
  state law that mandates a new visibility restriction or a new
  classification axis — becomes a new module in the existing pattern
  rather than a bespoke subsystem.
* **Negative (extension).** The catalogue grows: four flavours +
  joint products and visibility-product combinations. The "what is
  this rule?" decision tree gets longer, and a new contributor must
  internalise the four-flavour distinction before authoring a rule.
  The rule of thumb in *When to use which* exists to compress the
  decision; new contributors should be pointed there first.
