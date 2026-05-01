"""Tests for the classification report (P2R.6)."""

from typing import Annotated

from pydantic import BaseModel

from catins.models import CanonicalProposal, EntityHolder, IndividualHolder
from catins.privacy import (
    PII,
    FieldClassification,
    ModelClassification,
    classify_models,
    classify_table,
)


def test_classify_table_returns_pii_and_non_pii() -> None:
    report = classify_table(CanonicalProposal)
    assert isinstance(report, ModelClassification)
    assert report.model == "CanonicalProposal"
    pii_field_names = {entry.field for entry in report.pii}
    assert pii_field_names == {"holder_name", "zip_code", "age"}
    assert set(report.non_pii) == {
        "schema_version",
        "schema_effective_date",
        "erased",
        "holder_kind",
        "premium",
    }


def test_pii_entries_include_category_and_regimes() -> None:
    report = classify_table(CanonicalProposal)
    by_field = {e.field: e for e in report.pii}
    assert by_field["holder_name"].category == "direct"
    assert by_field["holder_name"].regimes == ["GLBA"]
    assert by_field["zip_code"].category == "quasi"
    assert by_field["age"].category == "quasi"


def test_pii_entries_sorted_by_category_then_field() -> None:
    """Stable sort so the JSON report diffs cleanly across runs."""
    report = classify_table(CanonicalProposal)
    fields_in_order = [e.field for e in report.pii]
    # direct comes before quasi; within quasi, alphabetical.
    assert fields_in_order == ["holder_name", "age", "zip_code"]


def test_individual_holder_classification() -> None:
    """The union branch with PII on its name."""
    report = classify_table(IndividualHolder)
    pii_field_names = {entry.field for entry in report.pii}
    assert pii_field_names == {"name"}
    assert report.pii[0].category == "direct"
    assert report.pii[0].regimes == ["GLBA"]


def test_entity_holder_classification_has_no_pii() -> None:
    """Per ADR 006 §1: business records are not PII under GLBA."""
    report = classify_table(EntityHolder)
    assert report.pii == []
    assert "name" in report.non_pii
    assert "kind" in report.non_pii


def test_classify_models_batch() -> None:
    reports = classify_models([CanonicalProposal, IndividualHolder, EntityHolder])
    assert set(reports.keys()) == {"CanonicalProposal", "IndividualHolder", "EntityHolder"}
    assert all(isinstance(r, ModelClassification) for r in reports.values())


def test_model_with_no_pii_fields() -> None:
    """A model without any PII annotations reports an empty PII list."""

    class _NoPII(BaseModel):
        a: int
        b: str

    report = classify_table(_NoPII)
    assert report.pii == []
    assert set(report.non_pii) == {"a", "b"}


def test_model_with_multi_regime_field() -> None:
    """A field tagged under multiple regimes preserves both."""

    class _Health(BaseModel):
        diagnosis: Annotated[str, PII("sensitive", regimes={"HIPAA", "GLBA"})]

    report = classify_table(_Health)
    assert len(report.pii) == 1
    entry = report.pii[0]
    assert entry.category == "sensitive"
    assert entry.regimes == ["GLBA", "HIPAA"]  # sorted


def test_classification_serialises_to_json() -> None:
    """The Pydantic model dumps cleanly for the CLI's JSON output."""
    report = classify_table(CanonicalProposal)
    dumped = report.model_dump()
    assert dumped["model"] == "CanonicalProposal"
    assert "pii" in dumped
    assert "non_pii" in dumped
    # Each pii entry is a plain dict, not a Pydantic model.
    assert all(isinstance(e, dict) for e in dumped["pii"])


def test_field_classification_round_trip() -> None:
    """FieldClassification is a regular Pydantic model."""
    fc = FieldClassification(field="x", category="direct", regimes=["GLBA"])
    dumped = fc.model_dump()
    rehydrated = FieldClassification(**dumped)
    assert rehydrated == fc
