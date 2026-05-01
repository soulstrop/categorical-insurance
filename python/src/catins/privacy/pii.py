"""PII marker and introspection over Pydantic models.

# math: math.tex §VI (Labelling worked instance)

The ``PII`` marker is the type-level annotation that tells the
classification, tokenisation, and access-policy machinery which fields
on a model carry regulated identifiers. It is the worked instance of
the **labelling** decision flavour from ADR 005: the admission
predicate is the constant ``True`` and the payload is the per-field
``PII`` instance, so applying the labelling decision system to a model
is structurally identical to running a guardrail — the result is a
labelling map ``{field_name → PII}``.

Usage::

    from typing import Annotated
    from catins.privacy import PII

    class IndividualHolder(BaseModel):
        name:     Annotated[str,  PII("direct", regimes={"GLBA"})]
        ssn:      Annotated[str,  PII("direct", regimes={"GLBA"})]
        zip_code: Annotated[str,  PII("quasi",  regimes={"GLBA"})]
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel
from pydantic.fields import FieldInfo

PIICategory = Literal["direct", "quasi", "sensitive"]


@dataclass(frozen=True)
class PII:
    """Marker carrying the classification of a sensitive field.

    ``category`` is one of:

    * ``"direct"``    — directly identifies a person (name, SSN);
                        tokenised at the staging boundary (ADR 006 §2).
    * ``"quasi"``     — a quasi-identifier (DOB, ZIP, age) whose
                        re-identification risk depends on combination
                        with other fields; protected at read time via
                        masking policies.
    * ``"sensitive"`` — health, biometric, or other special-category
                        data subject to a stricter regime (HIPAA);
                        access requires an elevated role.

    ``regimes`` is the set of regulatory regimes that classify this
    field as PII (e.g. ``{"GLBA"}``, ``{"GLBA", "HIPAA"}``). Empty
    means "PII per project policy" without a specific regulatory
    binding — the classification report (P2R.6) flags those for review.
    """

    category: PIICategory
    regimes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Accept ``regimes={"GLBA"}`` (a regular set) at the call site
        # and coerce to frozenset for hashability and immutability.
        if not isinstance(self.regimes, frozenset):
            object.__setattr__(self, "regimes", frozenset(self.regimes))


def _pii_marker(field_info: FieldInfo) -> PII | None:
    """Return the ``PII`` marker on a field, or ``None`` if absent."""
    for meta in field_info.metadata:
        if isinstance(meta, PII):
            return meta
    return None


def is_pii(field_info: FieldInfo) -> bool:
    """Whether a Pydantic field carries a ``PII`` annotation."""
    return _pii_marker(field_info) is not None


def pii_fields(model_cls: type[BaseModel]) -> dict[str, PII]:
    """Map ``{field_name: PII}`` for fields annotated as PII.

    Inherited fields are included — a metadata field declared on a
    parent class with a PII annotation is reported under every concrete
    subclass.
    """
    return {
        name: marker
        for name, info in model_cls.model_fields.items()
        if (marker := _pii_marker(info)) is not None
    }


def non_pii_fields(model_cls: type[BaseModel]) -> list[str]:
    """Field names without a ``PII`` annotation."""
    pii = set(pii_fields(model_cls).keys())
    return [name for name in model_cls.model_fields if name not in pii]
