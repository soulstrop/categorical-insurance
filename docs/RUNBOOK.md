# Runbook

On-call playbook for the `categorical-insurance` Phase 3 pipeline.
This document is consulted under stress; the top-level table is the
quick-reference, the per-failure sections give detailed diagnosis and
resolution, the privacy / schema-evolution sections are procedural
references called from the failure sections.

**Status.** The runbook covers asset-check failures and the three
operational procedure classes implied by ADRs 006/007/008. Service-
level objectives, paging integration, and on-call rotation
themselves are still open (see *Out of scope* at the bottom and
`docs/PHASES.md` "What is not yet in any phase" items 7 and 9).

---

## Quick reference

| Signal in Dagster UI | Check name | First action | Section |
|---|---|---|---|
| Red asset check on `raw_proposals` | `check_schema_drift` | [Schema drift](#schema-drift-on-raw_proposals) | §1 |
| Red asset check on `validated_outcomes` | `check_guardrail_stability` | [Guardrail drift](#guardrail-distribution-drift) | §2 |
| Red asset check on `rejection_letters` | `check_cortex_budget` | [Cortex budget](#cortex-token-budget-warning) | §3 |
| Asset freshness state = WARN or FAIL | (auto, per asset) | [Stale asset](#asset-freshness-warning-or-failure) | §4 |
| Red asset check on `raw_proposals` (static dbt) | `check_view_filter_compliance` | [View-filter compliance](#view-filter-compliance) | §5 |
| Non-empty `raw_quarantine` partition | `quarantine_check` (Phase-2-revisit) | [Quarantine](#quarantine-investigation) | §7 |
| `pii_access_anomaly_check` red | (Phase-2-revisit) | [PII access](#pii-access-anomaly-investigation) | §6 |
| `erasure_latency_check` red | (Phase-2-revisit) | [Erasure latency](#erasure-latency-breach) | §6 |

---

## §1. Schema drift on `raw_proposals`

**Signal.** `check_schema_drift` is red. The asset-check description
identifies the drift as one or more of: missing column, extra column,
type mismatch.

**What it means.** The DataFrame produced by `raw_proposals` does
not match `CanonicalProposal`. The same Pydantic model drives the
dbt source contract, the masking-policy compiler, and (per
ADR 008) the schema-versioning machinery; any drift here will
cascade.

**Diagnose.**

1. Read the check's description in the Dagster UI; it lists the
   missing / extra / type-mismatched columns explicitly.
2. Cross-reference against `python/src/catins/models.py` —
   `CanonicalProposal` is the source of truth.
3. If the drift came from upstream (the producer changed the raw
   feed), check `raw_quarantine` for rejected rows from the same
   batch — every batch that fails ingest schema validation lands
   there with the failure reason.

**Resolve.**

* **If the upstream producer changed.** Engage the producer team.
  In the meantime, the pipeline will refuse to advance bad rows;
  ops impact is bounded to "no new contracts written" rather than
  "wrong contracts written."
* **If the change was intentional and on our side.** Land a PR
  that updates `CanonicalProposal` *and* either accepts an
  additive change (`schema_version` bump within the major; default
  for new optional fields) or annotates a breaking change with
  `# evolution: breaking` (per ADR 008 §2). The
  `//python:schema:compat-check` CI step (Phase-2-revisit) will
  enforce the discipline; without the annotation, breaking changes
  fail CI.

**Escalate.** If neither side can identify the cause within 15
minutes, page the data-platform lead. A schema-drift incident that
masks an unidentified upstream regression is a higher-order
concern than the asset-check failure itself.

---

## §2. Guardrail-distribution drift

**Signal.** `check_guardrail_stability` is red. The description
reads `Mean risk score X.YZ >= cap 0.6`.

**What it means.** The mean of the joint payload's risk-score
component has crossed the configured cap. This is a
*distribution* signal, not a per-row governance failure: every
proposal in the batch may have passed its individual rules and
still produced an aggregate that the underwriting model considers
abnormal.

**Diagnose.**

1. Pull the latest `validated_outcomes` materialisation. Look at
   the per-row distribution of the second element of the `payload`
   column (the risk score).
2. Identify whether the shift is:
   * **A few outliers** — investigate those rows specifically; they
     may indicate fraud, data corruption, or a single high-impact
     rating-factor change.
   * **A distributional shift** — the whole batch is shifted
     upward. Cross-reference against historical means via the
     `cortex_run_log` (Phase-2-revisit asset) or the `contracts`
     table.
3. If the shift coincides with an upstream feature pipeline
   change, escalate to the producer team per §1.

**Resolve.**

* **If outliers.** Process per-row: confirm legitimate writeups,
  flag suspicious cases for review, kick the rest forward.
* **If distributional shift.** *Stop the daily schedule* before
  the next run if the shift has not been explained. The
  guardrail's `m` payload is what the framework uses to bound
  portfolio risk; an unexplained distribution change is a
  pre-incident signal.
* **If the cap itself is wrong.** A revisit of
  `MAX_PORTFOLIO_RISK_SCORE` is a *governance* change — engage
  the underwriting team; do not silently bump the constant.

**Escalate.** Distributional shift without explanation: page
underwriting + data-platform jointly within 30 minutes.

---

## §3. Cortex token-budget warning

**Signal.** `check_cortex_budget` is red. Description reads
`Cortex spend <total>/<cap> tokens (X.Y% of cap; warn threshold
Z%)`.

**What it means.** The run did not overrun the *hard cap* (if it
had, the rejection-letter asset would have raised
`BudgetExceededError` and the run would have failed entirely).
The realised spend crossed the *soft threshold* — a forewarning
that the next run may hit the hard cap if input volume or
prompt-length distribution drifts upward.

**Diagnose.**

1. Pull the latest run metadata. The check's metadata field
   `total_tokens` shows realised spend; `budget` shows the cap;
   `utilisation_pct` is the ratio.
2. Compare against the previous N runs (when the
   `cortex_run_log` asset lands per Phase-2-revisit; today, dig
   through Dagster run history manually).
3. If spend is climbing run-over-run, identify what changed:
   batch size, prompt template, model version.

**Resolve.**

* **Short-term.** Raise the cap on the `CortexResource` in
  `definitions.py`; redeploy. Buys breathing room; doesn't
  diagnose the cause.
* **Medium-term.** Identify the drift source. If batch size has
  grown, that's expected — adjust the cap and the warn threshold
  proportionally. If prompt-length has grown silently, investigate
  the explanation template (`catins/cortex/explain.py`).
* **Long-term.** Wire the SIEM forwarding for vault-tokenised /
  PII_FULL accesses (ADR 006 §6) so anomalies surface in
  real-time rather than at the next nightly cycle.

**Escalate.** Repeated soft-threshold breaches over three runs
without an identified cause: data-platform lead.

---

## §4. Asset freshness WARN or FAIL

**Signal.** The asset's freshness state in the Dagster UI is WARN
(materialisation older than 12 hours) or FAIL (older than 24 hours).
Affects `validated_outcomes`, `contracts`, `rejections` per the
`FreshnessPolicy.time_window` attached to those assets.

**Schedule alignment.** `catins_daily_schedule` runs at `0 6 * * *`
UTC. The 06:00-UTC start composed with the 12h-warn / 24h-fail
windows gives 18h+ of headroom before WARN and 6h+ before FAIL,
even after a generous overrun. A WARN that fires before 18:00 UTC
on the same day usually means the schedule did not run at all, not
that it ran slow.

**What it means.** The asset has not been re-materialised within
the SLA window. Either the daily schedule failed, the
materialisation took longer than the window, or the schedule was
disabled.

**Diagnose.**

1. Check the Dagster UI for the most recent run of
   `catins_validation_job`. If it failed, the run page has the
   error.
2. If no recent run exists, the schedule is paused or
   misconfigured.
3. If the last run succeeded but the asset is still WARN/FAIL,
   the materialisation actually completed — but the check is
   reading a stale event log. Rare; usually requires a Dagster
   instance restart.

**Resolve.**

* **Failed run.** Triage per the failing asset: schema drift (§1),
  guardrail (§2), Cortex (§3), or another error.
* **Disabled schedule.** Re-enable in the UI or via
  `dagster schedule start catins_daily_schedule`.
* **Stale event log.** Restart the `dagster-daemon` process.

**Escalate.** A 24-hour FAIL on `contracts` is a customer-facing
incident — page on-call + comms.

---

## §5. View-filter compliance

**Signal.** `check_view_filter_compliance` is red. The asset-check
description names the offending model(s) and reports
`N/M consumer-facing views are missing WHERE erased = false`.

**What it means.** A consumer-facing view (under `models/marts/`,
materialised as a view) does not contain the literal predicate
prescribed by ADR 007 §2. The check is a *static* read of the dbt
manifest, not of runtime data — failure means the SQL is wrong, not
that any specific row leaked. But: the SQL is wrong, so on the next
materialisation this view *will* return erased rows to consumers.

**Two failure modes.**

* **Model authored without the filter.** Most common. The model
  author either forgot the convention or wrote `NOT erased` /
  `erased IS FALSE` (rejected — see ADR 007 §2 and the check's
  regex; the canonical form is the only accepted form).
* **dbt manifest stale.** If the manifest hasn't been regenerated
  since the model was added, the check sees an old graph. Less
  common but worth ruling out.

**Diagnose.**

1. Read the asset-check description; it lists each offending
   `model.<package>.<name>` id.
2. For each, open the file at `python/dbt/models/marts/<name>.sql`.
3. Confirm the SQL is missing the literal `WHERE erased = false`
   (or contains a non-canonical form like `NOT erased`).
4. If the SQL *does* contain the canonical form, regenerate the
   manifest: `cd python/dbt && dbt parse`.

**Resolve.**

* **Add the filter.** Append `WHERE erased = false` to the offending
  view (or `AND erased = false` if a `WHERE` already exists).
* **Rewrite a non-canonical form.** Replace `NOT erased`,
  `erased IS FALSE`, etc. with `erased = false`. The convention
  is intentional — it makes the check, dbt generic test, and
  reviewer grep all line up on one form.
* **Regenerate manifest.** If the model is correct, run
  `dbt parse` from `python/dbt/`.

**Escalate.** A red view-filter check that has been red for >1
business day implies a consumer view is currently leaking erased
PII into downstream queries. Page the privacy officer; they may
decide to disable the offending view (`dbt run --exclude <model>`)
until the filter is added.

---

## §6. Privacy-officer procedures (ADRs 006/007)

These procedures are gated on the Phase-2-revisit implementation
landing. They are documented now so the runbook is complete from
the moment the Phase-2-revisit ships.

### Responding to an erasure request

**Per ADR 007.**

1. Confirm the request originator and identity-match against the
   target customer record. Two-person verification is required;
   the privacy officer initiates, a second authorised reviewer
   confirms.
2. Run `catins.privacy.erasure.tombstone(session, table, row_id)`
   for the source `Proposal` row. The function:
   * Sets `erased = true`.
   * Nulls every column classified as `direct` or `quasi`.
   * Writes a row to `_audit_erasures` with the pre-erasure
     snapshot, request ID, and timestamp.
3. Confirm via `catins.privacy.erasure.is_erased(...)` that the
   tombstone is visible. The consumer-facing view `v_proposals`
   will return zero rows for the holder; the audit table will
   contain one row with the snapshot.
4. The cleaning sweep (`erasure_cleaning_sweep`, scheduled
   Dagster job) rebuilds materialised derivatives within the
   sweep cadence. *Do not run an ad-hoc rebuild* unless the
   cadence is unacceptable for this specific request — the
   bounded staleness window is the design.

**Common pitfalls.**

* The erasure is **irreversible**. There is no undo. If the
  request is later disputed, the audit table preserves the *fact*
  of the request and the snapshot for regulatory inspection, but
  the operational data is gone.
* The audit snapshot itself is sensitive PII. Access to
  `_audit_erasures` is restricted to the `PRIVACY_OFFICER` role;
  do not share queries against it casually.

### Vault-related incidents

**Per ADR 006.**

* **Vault outage.** Ingestion stalls (encode calls fail);
  analytics on tokens continues unaffected; rejection-letter
  generation stalls (decode calls fail). Restart the cluster per
  the Vault upstream runbook; if data has accumulated, it lands
  through the catch-up batch when Vault returns.
* **Vault key compromise.** Activate the key-rotation runbook
  *before* attempting to re-tokenise data. The transform engine
  supports versioned keys; old tokens remain decryptable until
  explicitly retired.
* **Misclassification incident.** A field that should have been
  tokenised was instead landed in the warehouse as plaintext.
  Two parallel actions: (a) immediately apply the masking policy
  to hide the column from non-`PII_FULL` roles; (b) trigger the
  `classification_change_sweep` to re-evaluate and re-tokenise.
  The sweep is *not* automatic on classification change — it
  requires explicit invocation and audit.

### PII access anomaly investigation

**Per ADR 006 §6.** The `pii_access_anomaly_check` reads
`ACCESS_HISTORY` and fires when access patterns deviate from a
learned envelope.

1. Pull the recent ACCESS_HISTORY rows for the suspect role /
   user. The anomaly check's metadata identifies which envelope
   was breached.
2. Confirm with the user whether the activity was legitimate.
3. If unexplained: revoke the user's PII_FULL grant immediately;
   begin incident-response procedure (gated; see *Out of scope*).
4. If legitimate: update the envelope baseline.

---

## §7. Schema-evolution procedures (ADR 008)

### Adding a field (additive change)

1. Edit `CanonicalProposal` in `python/src/catins/models.py`.
2. Add the new field with a default and a `PII` annotation if
   sensitive.
3. Run `mise run //python:dbt:check-drift` to regenerate the
   YAML. Commit both the model and the YAML in the same change.
4. Run `mise run //python:schema:compat-check` (Phase-2-revisit)
   to verify the change is *additive* — no field renamed,
   removed, or retyped. If it flags a breaking-candidate, see
   the next procedure.
5. CI will refuse the change if the drift check or compat check
   fails.

### Breaking change (major version bump)

1. Land the change with the new field renamed/retyped/removed
   plus a `# evolution: breaking` annotation on the field
   declaration. CI's compat-check step requires the annotation
   to accept a breaking change.
2. Add a new `ProposalV2` discriminated-union member that
   reflects the new shape; keep `ProposalV1` for read of old
   rows. Update `parse_proposal` to dispatch by `schema_version`.
3. Update `v_proposals` SQL view to project v1 rows into the v2
   shape with NULL-fill for new fields.
4. Schedule a board review (compliance, ops, downstream-consumer
   reps) before merge per ADR 008 §7.

### Quarantine investigation

`quarantine_check` (Phase-2-revisit) fires when `raw_quarantine`
is non-empty for the latest partition. Each quarantined row
carries a reason (the validation error).

1. Identify the upstream batch. The reason column tells you what
   failed.
2. If the upstream producer published a breaking change, engage
   them. Hold the rest of the batch in quarantine pending
   resolution.
3. If a transient producer error, replay the batch after
   producer fix.

### Classification-change retroactive sweep

When ADR 006's PII classification scheme changes (e.g., a field
previously tagged `quasi` is reclassified as `direct`), the
historical rows in the warehouse retain their *prior*
classification. Per ADR 008 §8, tombstoned rows are immutable —
the classification-change sweep is a separate, auditable
operation:

1. Initiated by the privacy officer. Two-person review.
2. Runs `classification_change_sweep` against the affected
   tables.
3. The sweep regenerates masking-policy DDL and triggers
   re-tokenisation of any direct identifiers that were not
   previously vaulted.
4. Audit table records the sweep with the originating
   classification change.

---

## Out of scope (open questions)

The following operational concerns are not yet defined and are
flagged in `docs/PHASES.md` "What is not yet in any phase":

* **Service-level objectives.** Latency SLOs on validation,
  freshness SLOs beyond the asset-check window, alerting wiring,
  paging integration. (PHASES item 7.)
* **Incident-response playbook.** The procedures above are
  *response* playbooks for known check failures. A bad-contract-
  slipped-through incident — the rare case where governance was
  satisfied at the time but later judgment finds the contract
  defective — needs its own playbook including quarantine,
  remediation, and notification. (PHASES item 9.)
* **On-call rotation.** Who is paged, on what cadence, with what
  escalation paths.

These will land as separate ADRs and runbook sections; the
sections above are the engineering-controlled procedures that
exist on day one of Phase 3 production.
