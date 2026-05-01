"""Schema-compatibility check per ADR 008.

# math: math.tex §VII.B (breaking change ⇒ migration ⇒ commutativity proof)

Compares the current ``CanonicalProposal`` (and friends) against a
checked-in baseline JSON snapshot. Classifies each diff as **additive**
(safe, e.g. new field with default, optional→required relaxation) or
**breaking** (e.g. field removed, type changed, required field added,
default removed).

A breaking change is allowed only when accompanied by the
``# evolution: breaking`` annotation in ``catins.models``. The annotation
is the human attestation that the breaking change has a migration
plan; the compat-check is the machine enforcement that the annotation
is present.

Workflow:

1. Edit ``CanonicalProposal``.
2. Run ``python -m catins.schema_evolution.compat`` (or
   ``//python:schema:compat-check``):
   * Pure additive change → ``OK: additive``.
   * Breaking change with annotation → ``OK: breaking change with
     annotation acknowledged`` (and the engineer regenerates the
     baseline via ``--write`` and commits both).
   * Breaking change without annotation → ``BREAKING:`` summary;
     CI fails. Add the annotation and regenerate the baseline.
3. Regenerate baseline: ``python -m catins.schema_evolution.compat
   --write``.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from catins.models import CanonicalProposal, EntityHolder, IndividualHolder, Proposal

BREAKING_ANNOTATION = "# evolution: breaking"

# The list of models whose shapes are part of the externally-visible
# contract. Adding a model here brings it under compat-check; removing
# it is itself a breaking change.
TRACKED_MODELS: list[type[BaseModel]] = [
    Proposal,
    CanonicalProposal,
    IndividualHolder,
    EntityHolder,
]


def _type_repr(annotation: Any) -> str:
    """Canonical string repr of a type annotation for snapshot diffing."""
    if get_origin(annotation) is Literal:
        args = get_args(annotation)
        rendered = ", ".join(repr(a) for a in args)
        return f"Literal[{rendered}]"
    if hasattr(annotation, "__name__"):
        return str(annotation.__name__)
    return str(annotation)


def _field_snapshot(field_info: Any) -> dict[str, Any]:
    """Snapshot the relevant compat-check facts about one field."""
    return {
        "type": _type_repr(field_info.annotation),
        "required": field_info.is_required(),
    }


def snapshot_models(models: list[type[BaseModel]]) -> dict[str, Any]:
    """Capture the shape of each model in a JSON-serialisable dict."""
    return {
        model_cls.__name__: {
            name: _field_snapshot(info) for name, info in model_cls.model_fields.items()
        }
        for model_cls in models
    }


def current_snapshot() -> dict[str, Any]:
    """The snapshot of the in-tree model state (for comparison and `--write`)."""
    return snapshot_models(TRACKED_MODELS)


# --- diffing ---


@dataclass(frozen=True)
class Change:
    """A single diff between two snapshots."""

    kind: Literal["additive", "breaking"]
    model: str
    field: str | None  # None if the change is at the model level (added/removed)
    description: str


def _diff_field(model: str, name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """Compare one field's snapshot across old and new."""
    out: list[Change] = []
    if old["type"] != new["type"]:
        out.append(
            Change(
                kind="breaking",
                model=model,
                field=name,
                description=f"type changed: {old['type']} → {new['type']}",
            )
        )
    if old["required"] and not new["required"]:
        out.append(
            Change(
                kind="additive",
                model=model,
                field=name,
                description="required → optional (constraint relaxed)",
            )
        )
    if not old["required"] and new["required"]:
        out.append(
            Change(
                kind="breaking",
                model=model,
                field=name,
                description="optional → required (existing rows may lack a value)",
            )
        )
    return out


def _diff_model(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """Compare one model's field set across old and new snapshots."""
    out: list[Change] = []
    old_fields = set(old.keys())
    new_fields = set(new.keys())

    for added in sorted(new_fields - old_fields):
        info = new[added]
        if info["required"]:
            out.append(
                Change(
                    kind="breaking",
                    model=name,
                    field=added,
                    description="new required field (existing rows lack a value)",
                )
            )
        else:
            out.append(
                Change(
                    kind="additive",
                    model=name,
                    field=added,
                    description="new optional field with default",
                )
            )

    for removed in sorted(old_fields - new_fields):
        out.append(
            Change(
                kind="breaking",
                model=name,
                field=removed,
                description="field removed",
            )
        )

    for shared in sorted(old_fields & new_fields):
        out.extend(_diff_field(name, shared, old[shared], new[shared]))

    return out


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """All diffs across all tracked models, additive and breaking."""
    out: list[Change] = []
    old_models = set(old.keys())
    new_models = set(new.keys())

    for added in sorted(new_models - old_models):
        out.append(
            Change(
                kind="additive",
                model=added,
                field=None,
                description="new model added to tracked set",
            )
        )
    for removed in sorted(old_models - new_models):
        out.append(
            Change(
                kind="breaking",
                model=removed,
                field=None,
                description="model removed from tracked set",
            )
        )

    for shared in sorted(old_models & new_models):
        out.extend(_diff_model(shared, old[shared], new[shared]))

    return out


# --- annotation scan ---


def has_breaking_annotation(source_paths: list[Path]) -> bool:
    """Whether ``# evolution: breaking`` appears in any source file."""
    return any(path.exists() and BREAKING_ANNOTATION in path.read_text() for path in source_paths)


# --- compat result ---


@dataclass(frozen=True)
class CompatResult:
    """Outcome of a full compat check."""

    passed: bool
    changes: list[Change]
    annotation_present: bool
    summary: str


def evaluate_compat(
    old: dict[str, Any],
    new: dict[str, Any],
    source_paths: list[Path],
) -> CompatResult:
    """Run the diff and the annotation scan; classify the outcome."""
    changes = diff_snapshots(old, new)
    breaking = [c for c in changes if c.kind == "breaking"]
    annotation = has_breaking_annotation(source_paths)

    if not changes:
        return CompatResult(
            passed=True, changes=[], annotation_present=annotation, summary="OK: no schema changes"
        )

    if not breaking:
        return CompatResult(
            passed=True,
            changes=changes,
            annotation_present=annotation,
            summary=f"OK: {len(changes)} additive change(s)",
        )

    if annotation:
        return CompatResult(
            passed=True,
            changes=changes,
            annotation_present=True,
            summary=(
                f"OK: {len(breaking)} breaking change(s) acknowledged via "
                f"`{BREAKING_ANNOTATION}` (regenerate baseline before merge)"
            ),
        )

    return CompatResult(
        passed=False,
        changes=changes,
        annotation_present=False,
        summary=(
            f"BREAKING: {len(breaking)} breaking change(s) without "
            f"`{BREAKING_ANNOTATION}` annotation in catins.models"
        ),
    )


# --- CLI ---

_REPO_PYTHON = Path(__file__).resolve().parents[3]
BASELINE_PATH = _REPO_PYTHON / "schema_baseline.json"
MODELS_PATH = _REPO_PYTHON / "src" / "catins" / "models.py"


def _format_changes(changes: list[Change]) -> str:
    return "\n".join(f"  [{c.kind}] {c.model}.{c.field or '*'}: {c.description}" for c in changes)


def _main() -> int:
    """CLI: ``python -m catins.schema_evolution.compat [--write]``."""
    write = "--write" in sys.argv

    new_snapshot = current_snapshot()

    if write:
        BASELINE_PATH.write_text(json.dumps(new_snapshot, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {BASELINE_PATH}")
        return 0

    if not BASELINE_PATH.exists():
        print(
            f"NO BASELINE: {BASELINE_PATH} does not exist. Run with --write to bootstrap.",
            file=sys.stderr,
        )
        return 1

    old_snapshot = json.loads(BASELINE_PATH.read_text())
    result = evaluate_compat(old_snapshot, new_snapshot, [MODELS_PATH])

    if result.changes:
        print(_format_changes(result.changes))
    print(result.summary)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
