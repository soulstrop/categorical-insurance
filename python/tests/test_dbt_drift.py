"""Tests for the Pydantic ↔ dbt source-contract drift check."""

from pathlib import Path

from catins.dbt import check_dbt_source_drift, expected_columns
from catins.models import CanonicalProposal, Proposal

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_YAML = REPO_ROOT / "dbt" / "models" / "staging" / "_sources.yml"


def test_canonical_proposal_matches_committed_sources() -> None:
    """The committed _sources.yml is in sync with CanonicalProposal."""
    passed, details = check_dbt_source_drift(
        CanonicalProposal, SOURCES_YAML, source_name="raw", table_name="proposals"
    )
    assert passed, f"dbt source drift detected: {details}"


def test_drift_detects_missing_column() -> None:
    """A model with a column the YAML lacks fails the drift check."""

    class DriftedProposal(Proposal):
        holder: str
        premium: float
        zip_code: str
        age: int
        new_field: str

    passed, details = check_dbt_source_drift(
        DriftedProposal, SOURCES_YAML, source_name="raw", table_name="proposals"
    )
    assert not passed
    assert "new_field" in details["missing"]


def test_drift_detects_type_mismatch() -> None:
    """A model with a different SQL type for an existing column fails."""

    class WrongTypeProposal(Proposal):
        holder: str
        premium: int  # was float -> DOUBLE in the YAML
        zip_code: str
        age: int

    passed, details = check_dbt_source_drift(
        WrongTypeProposal, SOURCES_YAML, source_name="raw", table_name="proposals"
    )
    assert not passed
    assert "premium" in details["type_mismatches"]


def test_expected_columns_for_canonical() -> None:
    cols = expected_columns(CanonicalProposal)
    assert cols == {
        "schema_version": "INTEGER",
        "schema_effective_date": "DATE",
        "erased": "BOOLEAN",
        "holder_kind": "VARCHAR",
        "holder_name": "VARCHAR",
        "premium": "DOUBLE",
        "zip_code": "VARCHAR",
        "age": "INTEGER",
    }
