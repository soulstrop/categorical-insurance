"""Tests for the IndividualHolder | EntityHolder discriminated union (P2R.3).

Covers:

* Discriminated-union construction from flat columns.
* Per-branch PII annotations: ``IndividualHolder.name`` is direct
  PII under GLBA; ``EntityHolder.name`` is not PII (per ADR 006 §1).
* The ``CanonicalProposal.from_holder`` classmethod and ``.holder``
  accessor round-trip.
* The flat-column over-protection caveat: ``CanonicalProposal.holder_name``
  is annotated PII unconditionally, so an entity-holder proposal still
  reports its name as PII at the proposal level (the typed-union view
  is the only place where the conditional semantic is preserved).
"""

from catins.models import (
    CanonicalProposal,
    EntityHolder,
    IndividualHolder,
    extraction_fields,
    proposal_domain_fields,
)
from catins.privacy import is_pii, pii_fields


def test_individual_holder_name_is_direct_pii_under_glba() -> None:
    fields = pii_fields(IndividualHolder)
    assert "name" in fields
    assert fields["name"].category == "direct"
    assert "GLBA" in fields["name"].regimes


def test_entity_holder_name_is_not_pii() -> None:
    """Per ADR 006 §1: business records are not PII under GLBA."""
    fields = pii_fields(EntityHolder)
    assert "name" not in fields
    assert not is_pii(EntityHolder.model_fields["name"])


def test_holder_kind_discriminator_default() -> None:
    """holder_kind defaults to 'individual' so existing call sites
    constructing CanonicalProposal with only holder_name continue
    to work before the entity-detection layer lands."""
    p = CanonicalProposal(holder_name="Alice", premium=100.0, zip_code="10001", age=30)
    assert p.holder_kind == "individual"


def test_typed_holder_round_trip_individual() -> None:
    p = CanonicalProposal(
        holder_kind="individual",
        holder_name="Alice",
        premium=100.0,
        zip_code="10001",
        age=30,
    )
    holder = p.holder
    assert isinstance(holder, IndividualHolder)
    assert holder.name == "Alice"
    assert holder.kind == "individual"


def test_typed_holder_round_trip_entity() -> None:
    p = CanonicalProposal(
        holder_kind="entity",
        holder_name="Acme Corp",
        premium=500.0,
        zip_code="94102",
        age=0,
    )
    holder = p.holder
    assert isinstance(holder, EntityHolder)
    assert holder.name == "Acme Corp"
    assert holder.kind == "entity"


def test_from_holder_classmethod_individual() -> None:
    holder = IndividualHolder(name="Alice")
    p = CanonicalProposal.from_holder(holder, premium=100.0, zip_code="10001", age=30)
    assert p.holder_kind == "individual"
    assert p.holder_name == "Alice"


def test_from_holder_classmethod_entity() -> None:
    holder = EntityHolder(name="Acme Corp")
    p = CanonicalProposal.from_holder(holder, premium=500.0, zip_code="94102", age=0)
    assert p.holder_kind == "entity"
    assert p.holder_name == "Acme Corp"


def test_extraction_fields_excludes_defaulted_holder_kind() -> None:
    """Required-only filter: holder_kind has a default, so Cortex
    extraction does not need to populate it."""
    fields = extraction_fields(CanonicalProposal)
    assert "holder_kind" not in fields
    assert "holder_name" in fields
    assert set(fields) == {"holder_name", "premium", "zip_code", "age"}


def test_proposal_domain_fields_includes_both_holder_columns() -> None:
    """Warehouse-level introspection sees both flat columns."""
    fields = proposal_domain_fields(CanonicalProposal)
    assert "holder_kind" in fields
    assert "holder_name" in fields


def test_flat_holder_name_pii_over_protection_caveat() -> None:
    """Per the docstring: holder_name is annotated PII unconditionally.

    This means an entity-holder's name is over-protected at the
    proposal level. The typed-union view (.holder) is the place
    where the conditional semantic is preserved.
    """
    p = CanonicalProposal(
        holder_kind="entity",
        holder_name="Acme Corp",
        premium=500.0,
        zip_code="94102",
        age=0,
    )
    # Proposal-level: holder_name carries the PII annotation.
    assert is_pii(CanonicalProposal.model_fields["holder_name"])
    # Union-level: the entity branch does not.
    holder = p.holder
    assert isinstance(holder, EntityHolder)
    assert "name" not in pii_fields(EntityHolder)
