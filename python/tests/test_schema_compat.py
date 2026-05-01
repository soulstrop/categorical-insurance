"""Tests for the compat-check (P2R.5).

Covers diff classification (additive vs breaking across each kind of
schema change) and the annotation-gate logic (breaking changes require
the ``# evolution: breaking`` marker; additive changes don't).

P2R.3's holder-split is the worked example: the in-tree
``catins.models`` carries the annotation, so a baseline that lacks
holder_kind/holder_name still passes when measured against the current
model + the annotation. (We don't exercise that path here — those
files are already aligned, so the test does the equivalent against
synthetic snapshots.)
"""

from pathlib import Path

import pytest

from catins.schema_evolution.compat import (
    BASELINE_PATH,
    BREAKING_ANNOTATION,
    MODELS_PATH,
    current_snapshot,
    diff_snapshots,
    evaluate_compat,
    has_breaking_annotation,
    snapshot_models,
)


def _model(fields: dict[str, dict[str, object]]) -> dict[str, object]:
    return {"M": fields}


# --- diff classifications ---


def test_no_change_yields_no_diffs() -> None:
    snapshot = _model({"a": {"type": "int", "required": True}})
    assert diff_snapshots(snapshot, snapshot) == []


def test_additive_optional_field_added() -> None:
    old = _model({"a": {"type": "int", "required": True}})
    new = _model(
        {
            "a": {"type": "int", "required": True},
            "b": {"type": "str", "required": False},
        }
    )
    changes = diff_snapshots(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "additive"
    assert changes[0].field == "b"


def test_breaking_required_field_added() -> None:
    old = _model({"a": {"type": "int", "required": True}})
    new = _model(
        {
            "a": {"type": "int", "required": True},
            "b": {"type": "str", "required": True},
        }
    )
    changes = diff_snapshots(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "breaking"
    assert changes[0].field == "b"


def test_breaking_field_removed() -> None:
    old = _model(
        {
            "a": {"type": "int", "required": True},
            "b": {"type": "str", "required": False},
        }
    )
    new = _model({"a": {"type": "int", "required": True}})
    changes = diff_snapshots(old, new)
    assert any(c.kind == "breaking" and c.field == "b" for c in changes)


def test_breaking_type_changed() -> None:
    old = _model({"a": {"type": "int", "required": True}})
    new = _model({"a": {"type": "str", "required": True}})
    changes = diff_snapshots(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "breaking"
    assert "int" in changes[0].description
    assert "str" in changes[0].description


def test_additive_required_to_optional() -> None:
    """Relaxing a constraint is additive — old data still validates."""
    old = _model({"a": {"type": "int", "required": True}})
    new = _model({"a": {"type": "int", "required": False}})
    changes = diff_snapshots(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "additive"


def test_breaking_optional_to_required() -> None:
    """Tightening a constraint is breaking — old rows may lack a value."""
    old = _model({"a": {"type": "int", "required": False}})
    new = _model({"a": {"type": "int", "required": True}})
    changes = diff_snapshots(old, new)
    assert len(changes) == 1
    assert changes[0].kind == "breaking"


def test_breaking_model_removed() -> None:
    old = {"M1": {"a": {"type": "int", "required": True}}, "M2": {}}
    new = {"M1": {"a": {"type": "int", "required": True}}}
    changes = diff_snapshots(old, new)
    assert any(c.kind == "breaking" and c.model == "M2" and c.field is None for c in changes)


def test_additive_model_added() -> None:
    old = {"M1": {"a": {"type": "int", "required": True}}}
    new = {"M1": {"a": {"type": "int", "required": True}}, "M2": {}}
    changes = diff_snapshots(old, new)
    assert any(c.kind == "additive" and c.model == "M2" and c.field is None for c in changes)


# --- annotation scan ---


def test_annotation_scan_finds_marker(tmp_path: Path) -> None:
    src = tmp_path / "models.py"
    src.write_text(f'class Foo:\n    """{BREAKING_ANNOTATION} — explanation."""\n')
    assert has_breaking_annotation([src])


def test_annotation_scan_misses_marker(tmp_path: Path) -> None:
    src = tmp_path / "models.py"
    src.write_text("class Foo:\n    pass\n")
    assert not has_breaking_annotation([src])


def test_annotation_scan_handles_missing_file(tmp_path: Path) -> None:
    """A missing source file is treated as 'no annotation found',
    not as a crash — keeps the CI failure mode sensible."""
    assert not has_breaking_annotation([tmp_path / "nonexistent.py"])


# --- evaluate_compat outcome classification ---


def test_no_changes_passes(tmp_path: Path) -> None:
    snapshot = _model({"a": {"type": "int", "required": True}})
    result = evaluate_compat(snapshot, snapshot, [tmp_path / "any.py"])
    assert result.passed
    assert "no schema changes" in result.summary


def test_additive_only_passes_without_annotation(tmp_path: Path) -> None:
    src = tmp_path / "models.py"
    src.write_text("class Foo: pass\n")  # no annotation
    old = _model({"a": {"type": "int", "required": True}})
    new = _model(
        {
            "a": {"type": "int", "required": True},
            "b": {"type": "str", "required": False},
        }
    )
    result = evaluate_compat(old, new, [src])
    assert result.passed
    assert "additive" in result.summary
    assert not result.annotation_present


def test_breaking_with_annotation_passes(tmp_path: Path) -> None:
    src = tmp_path / "models.py"
    src.write_text(f'"""{BREAKING_ANNOTATION} — see migration ticket"""\n')
    old = _model({"a": {"type": "int", "required": True}})
    new = _model({"a": {"type": "str", "required": True}})  # type change
    result = evaluate_compat(old, new, [src])
    assert result.passed
    assert "breaking" in result.summary
    assert "acknowledged" in result.summary


def test_breaking_without_annotation_fails(tmp_path: Path) -> None:
    src = tmp_path / "models.py"
    src.write_text("class Foo: pass\n")  # no annotation
    old = _model({"a": {"type": "int", "required": True}})
    new = _model({"a": {"type": "str", "required": True}})
    result = evaluate_compat(old, new, [src])
    assert not result.passed
    assert "BREAKING" in result.summary
    assert BREAKING_ANNOTATION in result.summary


# --- snapshotting an in-tree model ---


def test_snapshot_models_captures_canonical_proposal_shape() -> None:
    from catins.models import CanonicalProposal  # noqa: PLC0415

    snapshot = snapshot_models([CanonicalProposal])
    assert "CanonicalProposal" in snapshot
    fields = snapshot["CanonicalProposal"]
    assert "holder_name" in fields
    assert fields["holder_name"]["type"] == "str"
    assert fields["holder_name"]["required"] is True
    assert fields["schema_version"]["required"] is False
    assert fields["holder_kind"]["type"].startswith("Literal[")


# --- end-to-end against the in-tree baseline ---


@pytest.mark.skipif(
    not BASELINE_PATH.exists(),
    reason="baseline not yet bootstrapped; run `python -m catins.schema_evolution.compat --write`",
)
def test_in_tree_baseline_matches_current_models() -> None:
    """The committed baseline is in sync with `catins.models`.

    If this fails: either someone changed a model and forgot to
    regenerate the baseline (run `--write`), or the change is
    breaking and needs the `# evolution: breaking` annotation in
    `catins/models.py`. The CI surface for this is
    `//python:schema:compat-check`.
    """
    import json  # noqa: PLC0415

    old = json.loads(BASELINE_PATH.read_text())
    new = current_snapshot()
    result = evaluate_compat(old, new, [MODELS_PATH])
    assert result.passed, result.summary
