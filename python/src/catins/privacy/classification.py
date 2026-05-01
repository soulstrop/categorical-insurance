"""Classification report for PII-annotated Pydantic models (ADR 006 §1).

The artifact this module emits is the source of truth that drives:

* Vault Transform role provisioning (P2R.7) — which fields need
  tokenisation.
* DDM masking policy generation (P2R.11) — which fields need
  masking and at what tier.
* Compliance review — auditors read the report to verify the
  classification matches the regulatory regime.

Library API: ``classify_table(model_cls)`` for one model;
``classify_models(models)`` for a batch.

CLI: ``python -m catins.privacy.classification`` (or
``//python:privacy:classify``) emits the full report as JSON.

Known limitation (the over-protection caveat from P2R.3): the report
classifies a field exactly per its annotation, so an unconditional
PII annotation on a flat column (like ``CanonicalProposal.holder_name``)
shows as PII even when the typed-union branch (``EntityHolder.name``)
is not. Both perspectives are present in the report — the union types
are classified independently — and downstream consumers that care
about the conditional case (per-row dispatch) consult the union
branches via ``IndividualHolder`` / ``EntityHolder``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from catins.privacy.pii import non_pii_fields, pii_fields


class FieldClassification(BaseModel):
    """One PII-annotated field's classification."""

    field: str
    category: str
    regimes: list[str]


class ModelClassification(BaseModel):
    """One model's per-field classification (PII + non-PII)."""

    model: str
    pii: list[FieldClassification]
    non_pii: list[str]


def classify_table(model_cls: type[BaseModel]) -> ModelClassification:
    """Produce a classification report for one Pydantic model.

    PII fields are sorted by category (direct → quasi → sensitive),
    then alphabetically — so the report is stable across runs and
    easy to diff in code review.
    """
    pii = pii_fields(model_cls)
    non_pii = sorted(non_pii_fields(model_cls))

    pii_entries = [
        FieldClassification(
            field=name,
            category=marker.category,
            regimes=sorted(marker.regimes),
        )
        for name, marker in pii.items()
    ]
    pii_entries.sort(key=lambda e: (_CATEGORY_ORDER.get(e.category, 99), e.field))

    return ModelClassification(model=model_cls.__name__, pii=pii_entries, non_pii=non_pii)


_CATEGORY_ORDER = {"direct": 0, "quasi": 1, "sensitive": 2}


def classify_models(models: list[type[BaseModel]]) -> dict[str, ModelClassification]:
    """Batch classification keyed by class name."""
    return {m.__name__: classify_table(m) for m in models}


def _report_as_dict(reports: dict[str, ModelClassification]) -> dict[str, Any]:
    """JSON-serialisable dict for the CLI's stdout."""
    return {name: report.model_dump() for name, report in reports.items()}


def _main() -> int:
    """CLI: ``python -m catins.privacy.classification``.

    Walks the tracked privacy models and emits the full report as
    JSON to stdout. The set tracked here is the same as the
    compat-check's ``TRACKED_MODELS`` so the two reports stay in
    sync.
    """
    # Imported here to avoid the privacy package importing from models
    # at package-init time (keeps the `catins.privacy` import cheap).
    from catins.models import (  # noqa: PLC0415
        CanonicalProposal,
        EntityHolder,
        IndividualHolder,
        Proposal,
    )

    models: list[type[BaseModel]] = [Proposal, CanonicalProposal, IndividualHolder, EntityHolder]
    reports = classify_models(models)
    print(json.dumps(_report_as_dict(reports), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
