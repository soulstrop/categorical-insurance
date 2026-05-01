"""Multi-version row dispatch per ADR 008.

# math: math.tex §VII.B

Reads the ``schema_version`` discriminator on an inbound row and
either:

* Constructs the corresponding Pydantic model (success path), or
* Returns a ``QuarantineRow`` carrying the original payload and a
  reason — which is what P2R.11's ``raw_quarantine`` table stores.

The dispatcher is the only path by which external rows enter the
typed model space; downstream code can assume a row that came
through ``parse_proposal`` has already been validated.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from catins.schema_evolution.versions import SchemaRegistry


class QuarantineRow(BaseModel):
    """A row that did not make it through schema dispatch.

    Stored in ``raw_quarantine`` (P2R.11) for the on-call to
    investigate. ``schema_version_seen`` records what (if anything)
    was on the row's ``schema_version`` field; ``reason`` is a
    short ops-readable label, ``detail`` is the full message
    (validation error, etc.).
    """

    model_config = ConfigDict(frozen=True)

    raw_payload: dict[str, Any]
    reason: str
    schema_version_seen: int | None = None
    detail: str = ""


_REASON_MISSING = "missing schema_version"
_REASON_UNKNOWN = "unknown schema version"
_REASON_VALIDATION = "validation failed"


def parse_proposal(
    row: dict[str, Any],
    registry: SchemaRegistry,
) -> BaseModel | QuarantineRow:
    """Dispatch a flat row to the model registered for its schema version.

    Failure paths (each producing a ``QuarantineRow``):

    * Row has no ``schema_version`` key, or it is ``None``.
    * The version is not registered.
    * The model rejects the row at Pydantic validation.
    """
    version = row.get("schema_version")
    if version is None:
        return QuarantineRow(
            raw_payload=row,
            reason=_REASON_MISSING,
            schema_version_seen=None,
        )

    entry = registry.get(version)
    if entry is None:
        return QuarantineRow(
            raw_payload=row,
            reason=_REASON_UNKNOWN,
            schema_version_seen=version,
            detail=f"known versions: {registry.known_versions()}",
        )

    _, model_cls = entry
    try:
        return model_cls(**row)
    except ValidationError as exc:
        return QuarantineRow(
            raw_payload=row,
            reason=_REASON_VALIDATION,
            schema_version_seen=version,
            detail=str(exc),
        )
