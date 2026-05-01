"""Tests for schema_evolution.versions + .dispatch (P2R.4).

Covers:

* SchemaRegistry: register, get, current (highest), known_versions,
  empty-registry behaviour.
* parse_proposal: v1 row → CanonicalProposal; v2 row (synthetic) →
  the v2 model; unknown version, missing schema_version, and
  validation failure all → QuarantineRow with appropriate reason.
* DEFAULT_REGISTRY: pre-populated with v1 = CanonicalProposal at
  import time so production callers don't have to wire it.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from catins.models import SCHEMA_V1_EFFECTIVE_DATE, CanonicalProposal, Proposal
from catins.schema_evolution import (
    DEFAULT_REGISTRY,
    QuarantineRow,
    SchemaRegistry,
    SchemaVersion,
    parse_proposal,
)

_V1 = SchemaVersion(version=1, effective_date=SCHEMA_V1_EFFECTIVE_DATE)
_V2 = SchemaVersion(version=2, effective_date=date(2026, 9, 1))


def _v1_row(**overrides: object) -> dict[str, object]:
    base = {
        "schema_version": 1,
        "holder_kind": "individual",
        "holder_name": "Alice",
        "premium": 100.0,
        "zip_code": "10001",
        "age": 30,
    }
    base.update(overrides)
    return base


# A synthetic v2 model used only to exercise multi-version dispatch.
class _CanonicalProposalV2(Proposal):
    """A hypothetical v2 schema for dispatch testing.

    Adds a `policy_term_months` field that v1 doesn't have. A real v2
    would land via a future ticket along with its compat-check
    annotations; here it exists only as a fixture.
    """

    holder_kind: str = "individual"
    holder_name: str
    premium: float
    zip_code: str
    age: int
    policy_term_months: int


# --- SchemaRegistry ---


def test_registry_register_and_get() -> None:
    registry = SchemaRegistry()
    registry.register(_V1, CanonicalProposal)
    entry = registry.get(1)
    assert entry is not None
    schema, model_cls = entry
    assert schema == _V1
    assert model_cls is CanonicalProposal


def test_registry_get_missing_returns_none() -> None:
    registry = SchemaRegistry()
    assert registry.get(99) is None


def test_registry_current_returns_highest_version() -> None:
    registry = SchemaRegistry()
    registry.register(_V1, CanonicalProposal)
    registry.register(_V2, _CanonicalProposalV2)
    assert registry.current() == _V2


def test_registry_known_versions_sorted() -> None:
    registry = SchemaRegistry()
    registry.register(_V2, _CanonicalProposalV2)
    registry.register(_V1, CanonicalProposal)
    assert registry.known_versions() == [1, 2]


def test_registry_current_on_empty_raises() -> None:
    with pytest.raises(LookupError):
        SchemaRegistry().current()


# --- parse_proposal ---


def _registry_v1_only() -> SchemaRegistry:
    r = SchemaRegistry()
    r.register(_V1, CanonicalProposal)
    return r


def _registry_v1_and_v2() -> SchemaRegistry:
    r = _registry_v1_only()
    r.register(_V2, _CanonicalProposalV2)
    return r


def test_dispatch_v1_row_to_canonical_proposal() -> None:
    result = parse_proposal(_v1_row(), _registry_v1_only())
    assert isinstance(result, CanonicalProposal)
    assert result.holder_name == "Alice"


def test_dispatch_v2_row_to_v2_model() -> None:
    row = _v1_row(schema_version=2, policy_term_months=12)
    result = parse_proposal(row, _registry_v1_and_v2())
    assert isinstance(result, _CanonicalProposalV2)
    assert result.policy_term_months == 12


def test_dispatch_unknown_version_quarantines() -> None:
    row = _v1_row(schema_version=99)
    result = parse_proposal(row, _registry_v1_only())
    assert isinstance(result, QuarantineRow)
    assert result.reason == "unknown schema version"
    assert result.schema_version_seen == 99
    assert "known versions" in result.detail


def test_dispatch_missing_version_quarantines() -> None:
    row = _v1_row()
    del row["schema_version"]
    result = parse_proposal(row, _registry_v1_only())
    assert isinstance(result, QuarantineRow)
    assert result.reason == "missing schema_version"
    assert result.schema_version_seen is None


def test_dispatch_validation_failure_quarantines() -> None:
    row = _v1_row(premium="not a number")
    result = parse_proposal(row, _registry_v1_only())
    assert isinstance(result, QuarantineRow)
    assert result.reason == "validation failed"
    assert result.schema_version_seen == 1
    assert "premium" in result.detail


def test_dispatch_quarantined_row_preserves_payload() -> None:
    row = _v1_row(schema_version=99)
    result = parse_proposal(row, _registry_v1_only())
    assert isinstance(result, QuarantineRow)
    assert result.raw_payload == row


# --- DEFAULT_REGISTRY ---


def test_default_registry_has_v1_canonical() -> None:
    entry = DEFAULT_REGISTRY.get(1)
    assert entry is not None
    schema, model_cls = entry
    assert schema.version == 1
    assert schema.effective_date == SCHEMA_V1_EFFECTIVE_DATE
    assert model_cls is CanonicalProposal


def test_default_registry_current_is_v1() -> None:
    """Today (P2R.4 only); will tick up as future versions register."""
    assert DEFAULT_REGISTRY.current().version == 1


def test_default_registry_dispatches_v1_row() -> None:
    """End-to-end: a v1 row goes through DEFAULT_REGISTRY without setup."""
    result = parse_proposal(_v1_row(), DEFAULT_REGISTRY)
    assert isinstance(result, CanonicalProposal)
    # Sanity-check that the union view comes back too.
    assert result.holder.name == "Alice"


# --- SchemaVersion semantics ---


def test_schema_version_is_frozen_and_hashable() -> None:
    v = SchemaVersion(version=1, effective_date=date(2026, 4, 30))
    assert hash(v) is not None
    assert v == SchemaVersion(version=1, effective_date=date(2026, 4, 30))


def test_schema_version_ordering_by_version() -> None:
    """Different dates with same version: equal as far as the registry
    is concerned (current() picks by version, not by date)."""
    registry = SchemaRegistry()
    registry.register(_V1, CanonicalProposal)
    registry.register(
        SchemaVersion(version=1, effective_date=date(2026, 5, 1)),
        CanonicalProposal,
    )
    # Last registration wins for a given version number; semantics are
    # intentionally simple — use a new version number for any change
    # operationally distinct enough to dispatch differently.
    assert registry.current().version == 1
    assert registry.current().effective_date == date(2026, 5, 1)


def test_quarantine_row_is_frozen() -> None:
    """QuarantineRow uses frozen Pydantic config so callers can't mutate."""
    q = QuarantineRow(raw_payload={}, reason="missing schema_version")
    with pytest.raises(ValidationError, match="frozen"):
        q.reason = "different"  # type: ignore[misc]
