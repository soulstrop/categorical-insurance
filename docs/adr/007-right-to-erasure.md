# ADR 007: Right-to-Erasure — Tombstone Semantics with US-Only Scope

## Status
Accepted (2026-04-30). Companion to ADR 006 (PII and Sensitive-Data
Handling). Adjacent to ADR 008 (Schema and Contract Evolution) on
the question of how erased records remain interpretable across
schema versions. The view-layer filter (§2) is a worked instance of
the **Visibility guardrail** introduced in ADR 005's 2026-04-30
extension; the erasure tombstone is the data primitive on which the
visibility decision is evaluated.

## Context

When a consumer (or a regulator on their behalf) demands "delete my
data," the system must respond — but the operational meaning of
"delete" is not obvious and the wrong choice has expensive
consequences.

A naïve `DELETE FROM proposals WHERE holder = …`:

* Breaks audit lineage. We can no longer answer "did we ever issue a
  policy to this individual" — itself a regulator-mandated capability
  in some jurisdictions.
* Breaks statistical aggregates. "How many policies issued in 2025"
  silently drifts as deletions accumulate.
* Breaks referential integrity. Foreign keys from `contracts` /
  `rejections` / `state_observations` / `audit_log` to the proposal
  row are left orphaned or violated.
* Doesn't actually reach all PII copies. Materialised derivatives,
  Dagster IO-manager outputs, query result caches, backup snapshots,
  and Snowflake `TIME TRAVEL` retain the data unless explicitly
  rebuilt and trimmed.

A scheme that addresses these concerns must answer six sub-questions.

### A note on the US-only scope

Insurance enjoys an unusual legal posture: most US state consumer
privacy laws (CCPA / CPRA, CPA, CTDPA, VCDPA, UCPA, …) exempt
information that is collected, processed, sold, or disclosed
**pursuant to GLBA** — which covers most underwriting, policy-issuance,
and claims data. The general individual right to deletion under those
state laws does not apply to GLBA-covered records used for the
financial product they were collected for.

**This ADR scopes itself to that GLBA-covered core path.** Outside
that path the analysis is different (see *Where the simplification
breaks*).

## Sub-decisions

### 1. Erasure semantics — tombstone with PII null

The chosen design: erasure marks the row with `erased = true`, nulls
the PII fields, and leaves the row physically present.

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Hard delete** | `DELETE FROM …` | Simplest mental model; minimises ongoing PII exposure surface. | Breaks audit, lineage, foreign keys, aggregates. |
| **B. Tombstone + PII null** *(chosen)* | `UPDATE … SET pii = NULL, erased = true`. Row stays; identifiers go. | Audit-lineage preserved; aggregates intact; foreign keys still resolve. | Storage not reduced; the row's continued existence is itself a data point about the customer. |
| **C. Cryptographic shredding** | Tombstone + destroy the per-customer key in Vault | Cryptographically defensible "we cannot read it." | Requires per-customer keys (much heavier Vault setup); no path back even if the request was a mistake. |
| **D. Tiered retention with auto-erase** | PII auto-tombstoned at retention deadline regardless of explicit request | Handles erasure and retention compliance jointly. | Requires a retention-policy decision we haven't made; aggressive auto-erase breaks legitimate analytical workflows. |

B is chosen for the GLBA-covered path. C is the right answer if the
threat model includes "a future engineer who can read past values
from backups"; we accept that risk because (a) Vault tokenisation
already separates direct identifiers from the warehouse, so what
remains in the warehouse to null is mostly quasi-identifiers, and
(b) the operational complexity of per-customer keys is not justified
by the marginal threat reduction in our threat model.

### 2. Scope of erasure — source nulled, derivatives view-filtered, sweep rebuilds

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Source only** | Null the `raw.proposals` row; derivatives untouched. | Trivial. | Derived `contracts` table still has full PII. Doesn't satisfy the request. |
| **B. Source + lineage walk** | Trace lineage; null in every materialised table. | Thorough. | Per-request lineage walk is expensive; every new dbt model becomes a leak point that must be remembered. |
| **C. Source + view-layer filter** *(chosen)* | Null at source. Every consumer-facing view filters `WHERE erased = false`. Stale materialisations are eventually rebuilt. | Adding a new model doesn't add a new leak point; the discipline is "every view filters." | Stale materialised tables retain values until next rebuild — bounded but non-zero exposure window. |
| **D. C + scheduled sweep** *(chosen extension)* | Periodic rebuild of materialisations after erasure batch. | Bounds the staleness window to one sweep cycle. | Rebuild cost; the sweep itself becomes an operational concern (must succeed; must alert on failure). |

The combined choice is C+D: tombstone at source immediately, every
view filters, a scheduled "cleaning sweep" rebuilds materialisations.
The sweep is deferred ("at some future point" per the design
direction); the view-layer filter alone is sufficient for compliance
because the consumer-facing query path never returns erased rows.

#### Visibility as a guardrail decision system

The view-layer filter is the worked instance of the **Visibility
guardrail** flavour added to ADR 005 (2026-04-30 extension).
Concretely:

```python
VisibilityM = Visible | RestrictedTo[set[Role]] | Erased
# combine: meet (most-restrictive of two)
# empty:   Visible
# adm:     role_admitted(m, current_role())

VisibilityDecision = (Proposal, QueryContext) -> VisibilityM
```

Each visibility-affecting rule is a `VisibilityDecision`:

* The erasure rule: `if proposal.erased: Erased else Visible`.
* (Future) A litigation-hold rule: `if proposal.under_litigation:
  RestrictedTo({"LITIGATION", "PRIVACY_OFFICER"}) else Visible`.
* (Future) A claims-investigation rule: similar.

The system aggregates them via meet (most-restrictive wins). The
view-layer SQL `WHERE` clause is `validate`-equivalent over the
aggregate — for the consumer-facing role,
`adm(Erased) = False`, and the row is filtered out; for the
`PRIVACY_OFFICER` role looking at `_audit_erasures`,
`adm(Erased) = True` because that role is admitted on Erased.

Today only the erasure rule is implemented, so the visibility
decision system is degenerate: a single rule that returns `Erased`
or `Visible`. The categorical framing matters because **adding the
next visibility rule (litigation hold, claims hold, or any future
constraint) becomes a new module, not a new view-filter pattern.**
A new restriction is one decision in `catins.privacy.visibility`;
the meet-monoid composes it with erasure automatically; the view
layer's `WHERE` clause is regenerated by the dbt macro.

A `# math: math.tex §VI guardrail (visibility) instance` annotation
on the visibility module makes the categorical correspondence
explicit. The Generalised Static Admissibility theorem (math.tex
Theorem 14) applies: the abstraction barrier on the consumer-facing
view holds because the filter is a function of the visibility monoid
value alone.

### 3. Erasure latency — tombstone synchronous, sweep asynchronous

The tombstone update happens within the request that records the
erasure. The sweep that rebuilds derivatives runs on a schedule,
within the regulator's tolerated window (CCPA: 45 days, often
extendable to 90).

The operationally important consequence: **the consumer-visible
behaviour of "erased" is immediate**, because the view-layer filter
takes effect the moment the source row is updated. Materialised
copies that have not yet been rebuilt are not consumer-facing; they
sit in `analytics_*` schemas behind RBAC.

### 4. Audit trail — separate `_audit_erasures` table, separately governed

Erasure produces a row in a dedicated `_audit_erasures` table:

```
_audit_erasures (
    erasure_id      UUID,
    request_id      VARCHAR,        -- supplied by the consumer-facing API
    request_hash    VARCHAR,        -- content-addressed digest of request
    erased_at       TIMESTAMP,
    erased_by       VARCHAR,        -- system or operator identity
    affected_table  VARCHAR,
    affected_row_id VARCHAR,
    pre_erasure_snapshot VARIANT    -- the row's PII content before nulling
)
```

The table is owned by a single `PRIVACY_OFFICER` role (Snowflake) /
ABAC-attribute-bearing role; SELECT is forbidden to the general
`PII_FULL` role. The pre-erasure snapshot exists *because* a
regulator audit may require proof that the erasure was carried out
on the right record — and to do that, the auditor needs to see what
was erased.

This creates a tension: the very purpose of erasure is undermined by
keeping a snapshot. The mitigation is **strict access control on the
audit table itself**, with every SELECT logged to ACCESS_HISTORY +
SIEM-forwarded per ADR 006 §6, and a documented retention horizon on
the audit-snapshot column (e.g., 7 years per typical state insurance
record-retention requirements, then the snapshot column is itself
nulled — the row showing the erasure happened remains; the snapshot
of what was erased does not).

### 5. Restoration — irreversible

Erasure is irreversible. Once tombstoned, the operational data is
gone. If a consumer later wants to re-engage, they re-submit a
proposal under the standard new-customer path. The audit table
preserves the *fact* of the prior relationship for regulator-facing
purposes only.

The alternative — a "soft delete" with restore-on-request — was
rejected because (a) it weakens the compliance story ("we didn't
*really* delete it for 30 days"), (b) it makes the consumer-facing
state ambiguous, and (c) the protection it offers (against mistaken
erasure requests) is better served by a verification step *before*
tombstoning, not a window of soft-deletion afterwards.

### 6. Idempotency

Erasure is idempotent. A second request for an already-erased record
returns success without modifying state. The consumer-facing API
treats both first-time and repeat requests as "your data is
inaccessible" — true in both cases.

## Where the simplification breaks

The "US-only insurance, GLBA-covered" assumption holds for the core
underwriting and policy-issuance path. It does not hold for:

| Scenario | Regime that re-introduces deletion rights | Mitigation |
|---|---|---|
| Marketing data collected outside the GLBA "financial product" purpose | CCPA / CPRA / CPA / CTDPA / VCDPA / UCPA all apply | Out of current scope; if the company adds a marketing CRM, that data lives outside the warehouse and gets its own retention policy. |
| Health-product underwriting (life, disability) | HIPAA has its own retention and deletion rules; some state laws do not exempt health-related insurance data uniformly | If health products are introduced, this ADR is revisited. |
| Cross-border workers (e.g., a Canadian employee handling US claims data) | PIPEDA, GDPR (if any EU presence) | Employee data in HRIS is out of scope; this ADR covers customer data only. |
| Future expansion to a state without the GLBA exemption | Some state laws apply the exemption narrowly; legal landscape changes | A periodic legal review (annual) checks whether new state law affects the assumption. |
| EU resident transiently in scope | GDPR applies if any processing happens "in the context of activities of an establishment" in the EU | The "no EU establishment" assumption is part of the corporate posture; if that changes the ADR is revisited. |
| Genetic / biometric data inputs | GINA federally + most state biometric laws | If we ever ingest genetic information for underwriting, this ADR is revisited along with ADR 006 §1's classification. |

The pattern: **the design is correct for the current scope, and the
scope is documented**. New scope demands a new ADR or an amendment
here.

## Out of scope

* **Schema and contract evolution.** How an erased row written under
  schema v1 remains interpretable when v2 introduces new fields:
  ADR 008.
* **Right-to-access** (CCPA's "give me my data" requirement). Out of
  scope; the warehouse can answer such a request via standard SELECT
  by the privacy-officer role, but there is no consumer-facing API.
* **Right-to-correct.** Same disposition.
* **Right-to-portability.** Same disposition.
* **Backup and disaster-recovery handling of erased records.** A
  Snowflake `TIME TRAVEL` query within retention can recover an
  un-tombstoned version of the row. Acceptable risk for the GLBA-
  exempted core path; if the exemption assumption is ever revisited,
  this becomes urgent.

## Consequences

* **Positive.** Compliance posture for the in-scope GLBA-covered path
  is straightforward and defensible. Audit lineage, statistical
  aggregates, and referential integrity all survive erasure.
* **Positive.** The view-layer filter discipline scales: adding a new
  dbt model adds zero new leak points as long as the model reads
  through the canonical filtered views. CI can enforce this with a
  custom dbt test.
* **Positive.** Operational mental model is simple. Engineers don't
  need to remember "is this an erased customer?" because the
  filtered views handle it implicitly. Only the privacy officer's
  audit queries see the full picture.
* **Negative.** The `_audit_erasures` snapshot column is a "dark"
  copy of erased PII that *exists* despite the user's request, and
  must be aggressively access-controlled. The 7-year-then-null
  horizon on the snapshot column is itself a discipline that must be
  scheduled and audited.
* **Negative.** Stale materialised derivatives carry erased PII
  until the sweep runs. The window is bounded by the sweep schedule
  (a runbook decision, not a code one); it is not zero.
* **Negative.** "Cleaning sweep added at some future point" is
  technical debt with a compliance angle. The ADR records it as a
  known follow-up; PHASES.md should add it as an explicit Phase 3+
  ticket.
* **Negative.** The US-only / GLBA-exempt simplification has an
  expiration date. Ten of the new state privacy laws (Colorado,
  Connecticut, Virginia, Utah, Texas, Oregon, Iowa, Tennessee, New
  Jersey, Indiana, etc.) treat the GLBA exemption with varying
  breadth. An annual legal review is required to confirm the
  assumption still holds.

## What changes in the codebase if accepted

* `Proposal` and `Contract` models gain `erased: bool = False`.
* The classification scheme from ADR 006 §1 is consulted to decide
  which fields get nulled on erasure (everything classified as
  `direct` or `quasi`; financial / non-PII columns are retained for
  aggregate analytics).
* New module `catins.privacy.erasure`:
  * `tombstone(session, table, row_id) -> EraseResult` — performs
    the tombstone update and writes the audit row.
  * `is_erased(session, table, row_id) -> bool` — convenience.
  * `audit_log_select(session, since: datetime) -> DataFrame` —
    privacy-officer query helper.
* dbt project gains:
  * `models/marts/v_proposals.sql`, `v_contracts.sql`, etc. —
    canonical filtered views; consumer-facing schemas reference these
    only.
  * `tests/test_view_filters_erased.sql` — generic test asserting
    every consumer-facing view filters `erased = false`.
  * `models/audit/_audit_erasures.sql` (Snowflake) / view-emulation
    (DuckDB) — locked-down per ADR 006 §5.
* `tests/test_erasure.py` — round-trip: insert proposal, erase,
  assert (a) source row updated with PII null and `erased=true`,
  (b) consumer view returns no row, (c) audit table contains the
  snapshot, (d) re-erasure is a no-op success.
* `docs/RUNBOOK.md` (P3.6) gains an erasure-incident-response
  section: how to verify a request was completed, how to respond to a
  regulator audit query, what to do if the audit snapshot was
  accidentally exposed.
* `docs/PHASES.md` adds a Phase 3+ ticket: implement the cleaning
  sweep as a Dagster scheduled job with asset checks on freshness
  and completion.

## Open questions

1. **Sweep schedule.** Daily, weekly, or event-triggered (after every
   erasure batch above N requests)? Defer until the cost of
   rematerialisation in the dev / mock stack is understood.
2. **Audit snapshot retention horizon.** Default proposed: 7 years
   per typical state insurance record-retention requirements. Legal
   review required to confirm.
3. **Privacy-officer role provisioning.** Single named individual,
   role inherited via ABAC, or both? Consult HR / legal on org-chart
   permanence.

## References

* `docs/PHASES.md` "What is not yet in any phase" item #4 (PII
  handling, of which erasure is a sub-aspect).
* ADR 005 (2026-04-30 extension) — Visibility guardrail flavour, of
  which §2's view-layer filter is the worked instance.
* ADR 006 — PII and sensitive-data handling.
* ADR 008 — schema and contract evolution: the question of how
  erased records remain interpretable across schema changes.
* GLBA Title V (15 U.S.C. §6801 et seq.) — financial privacy.
* CCPA / CPRA — Cal. Civ. Code §1798.140 et seq., particularly the
  GLBA exemption at §1798.145(e).
* NAIC Model Act #672 — insurance privacy of consumer financial and
  health information.
