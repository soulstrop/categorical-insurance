"""Tests for the PII marker and Pydantic introspection (P2R.2).

Verifies that:

* ``PII("category", regimes={...})`` constructs a frozen, hashable
  marker that survives ``Annotated[T, PII(...)]`` round-trips.
* ``pii_fields`` / ``non_pii_fields`` partition the model fields per
  the annotations.
* The annotation does not interfere with Pydantic's normal validation
  or the existing dbt drift check (the drift check sees the underlying
  ``str`` / ``int`` types, not ``Annotated``).
"""

from typing import Annotated

from pydantic import BaseModel

from catins.dbt import expected_columns
from catins.models import CanonicalProposal
from catins.privacy import PII, is_pii, non_pii_fields, pii_fields


def test_pii_marker_is_frozen_and_hashable() -> None:
    marker = PII("direct", regimes={"GLBA"})
    assert hash(marker) is not None  # frozen → hashable
    # frozenset coercion: the constructor takes a regular set, the
    # stored value is a frozenset.
    assert marker.regimes == frozenset({"GLBA"})
    assert isinstance(marker.regimes, frozenset)


def test_pii_marker_default_regimes_empty() -> None:
    marker = PII("quasi")
    assert marker.regimes == frozenset()


def test_pii_marker_equality() -> None:
    a = PII("direct", regimes={"GLBA"})
    b = PII("direct", regimes={"GLBA"})
    c = PII("direct", regimes={"HIPAA"})
    assert a == b
    assert a != c


def test_pii_fields_on_canonical_proposal() -> None:
    """Per ADR 006, holder is direct; zip_code and age are quasi."""
    fields = pii_fields(CanonicalProposal)
    assert set(fields.keys()) == {"holder", "zip_code", "age"}
    assert fields["holder"].category == "direct"
    assert fields["zip_code"].category == "quasi"
    assert fields["age"].category == "quasi"
    for marker in fields.values():
        assert "GLBA" in marker.regimes


def test_non_pii_fields_on_canonical_proposal() -> None:
    """Operational metadata + premium are not PII."""
    non_pii = non_pii_fields(CanonicalProposal)
    assert set(non_pii) == {
        "schema_version",
        "schema_effective_date",
        "erased",
        "premium",
    }


def test_partition_covers_all_fields() -> None:
    """PII + non-PII = all model fields, no overlap."""
    pii = set(pii_fields(CanonicalProposal).keys())
    non_pii = set(non_pii_fields(CanonicalProposal))
    all_fields = set(CanonicalProposal.model_fields.keys())
    assert pii.isdisjoint(non_pii)
    assert pii | non_pii == all_fields


def test_is_pii_field_check() -> None:
    fields = CanonicalProposal.model_fields
    assert is_pii(fields["holder"])
    assert is_pii(fields["zip_code"])
    assert not is_pii(fields["premium"])
    assert not is_pii(fields["schema_version"])


def test_pii_annotation_does_not_break_validation() -> None:
    """A model with PII-annotated fields still validates as usual."""
    p = CanonicalProposal(holder="Alice", premium=100.0, zip_code="10001", age=30)
    assert p.holder == "Alice"
    assert p.zip_code == "10001"


def test_pii_annotation_does_not_break_dbt_drift() -> None:
    """The dbt drift check reads the underlying SQL types, not the marker."""
    cols = expected_columns(CanonicalProposal)
    assert cols["holder"] == "VARCHAR"
    assert cols["zip_code"] == "VARCHAR"
    assert cols["age"] == "INTEGER"


def test_pii_annotation_round_trip_on_custom_model() -> None:
    """A user-defined model with the PII marker can be introspected."""

    class CustomHolder(BaseModel):
        name: Annotated[str, PII("direct", regimes={"GLBA"})]
        nickname: str

    fields = pii_fields(CustomHolder)
    assert set(fields.keys()) == {"name"}
    assert fields["name"].category == "direct"
    assert fields["name"].regimes == frozenset({"GLBA"})
