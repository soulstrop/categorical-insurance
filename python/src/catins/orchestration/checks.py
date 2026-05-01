"""Dagster Asset Checks for the insurance pipeline."""

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from dagster import AssetCheckResult, asset_check

from catins.dbt import expected_columns
from catins.models import CanonicalProposal
from catins.orchestration.resources import CortexResource

MAX_PORTFOLIO_RISK_SCORE = 0.6

# `python/src/catins/orchestration/checks.py` → parents[3] = `python/`.
DBT_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "dbt" / "target" / "manifest.json"

# ADR 007 §2 prescribes the literal predicate ``erased = false`` (case-
# insensitive, whitespace-flexible). Equivalents like ``NOT erased``
# are intentionally rejected: a single canonical form keeps grep,
# review, and this check aligned.
_ERASURE_FILTER_PATTERN = re.compile(r"\berased\s*=\s*false\b", re.IGNORECASE)

# Pandas dtype string -> SQL type used by ``catins.dbt.TYPE_MAPPING``.
# The mapping intentionally collapses 32 / 64-bit width (DuckDB's
# INTEGER vs BIGINT, etc.) onto a single SQL family — the drift check
# is a *shape* check, not a precision check; size mismatches are
# caught by the Pydantic boundary at ingest.
_PANDAS_DTYPE_TO_SQL = {
    "int8": "INTEGER",
    "int16": "INTEGER",
    "int32": "INTEGER",
    "int64": "INTEGER",
    "Int8": "INTEGER",
    "Int16": "INTEGER",
    "Int32": "INTEGER",
    "Int64": "INTEGER",
    "uint8": "INTEGER",
    "uint16": "INTEGER",
    "uint32": "INTEGER",
    "uint64": "INTEGER",
    "float32": "DOUBLE",
    "float64": "DOUBLE",
    "Float32": "DOUBLE",
    "Float64": "DOUBLE",
    "object": "VARCHAR",
    "string": "VARCHAR",
    "str": "VARCHAR",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
}


def _df_to_sql_columns(df: pd.DataFrame) -> dict[str, str]:
    """Project a DataFrame's column dtypes into the SQL-type vocabulary."""
    return {col: _PANDAS_DTYPE_TO_SQL.get(str(df[col].dtype), "VARIANT") for col in df.columns}


def _evaluate_schema_drift(df: pd.DataFrame) -> AssetCheckResult:
    """Compare a DataFrame's columns against ``CanonicalProposal``.

    Reuses ``catins.dbt.expected_columns`` — the same function the CI
    ``//python:dbt:check-drift`` task uses against the dbt YAML — so a
    single source of truth (the Pydantic ``CanonicalProposal``) drives
    both the warehouse-side contract and the runtime asset check.
    """
    expected = expected_columns(CanonicalProposal)
    actual = _df_to_sql_columns(df)

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    type_mismatches: dict[str, Any] = {
        name: {"expected": expected[name], "actual": actual[name]}
        for name in sorted(set(expected) & set(actual))
        if expected[name] != actual[name]
    }

    passed = not missing and not extra and not type_mismatches
    if passed:
        description = "Schema matches CanonicalProposal."
    else:
        parts: list[str] = []
        if missing:
            parts.append(f"missing: {missing}")
        if extra:
            parts.append(f"extra: {extra}")
        if type_mismatches:
            parts.append(f"type mismatches: {type_mismatches}")
        description = "Schema drift: " + "; ".join(parts)

    return AssetCheckResult(
        passed=passed,
        description=description,
        metadata={
            "missing_columns": missing,
            "extra_columns": extra,
            "type_mismatches": str(type_mismatches),
        },
    )


@asset_check(asset="raw_proposals")
def check_schema_drift(raw_proposals: pd.DataFrame) -> AssetCheckResult:
    """Ensure raw_proposals' columns and dtypes match CanonicalProposal."""
    return _evaluate_schema_drift(raw_proposals)


def _evaluate_guardrail_stability(df: pd.DataFrame) -> AssetCheckResult:
    """Mean risk score below ``MAX_PORTFOLIO_RISK_SCORE`` ⇒ passed.

    The check defends against silent drift in the guardrail's `m`
    payload distribution — the kind of regression that would not
    register as a governance failure (no rule fires) but indicates the
    portfolio is shifting toward higher aggregate risk than the
    underwriting model expects.
    """
    scores = [payload[1] for payload in df["payload"]]
    if not scores:
        return AssetCheckResult(
            passed=True,
            description="No scores to evaluate.",
            metadata={"mean_score": 0.0, "n_rows": 0},
        )
    mean_score = sum(scores) / len(scores)
    passed = mean_score < MAX_PORTFOLIO_RISK_SCORE
    return AssetCheckResult(
        passed=passed,
        description=(
            f"Mean risk score {mean_score:.3f} "
            f"({'<' if passed else '>='} cap {MAX_PORTFOLIO_RISK_SCORE})"
        ),
        metadata={
            "mean_score": mean_score,
            "n_rows": len(scores),
            "cap": MAX_PORTFOLIO_RISK_SCORE,
        },
    )


@asset_check(asset="validated_outcomes")
def check_guardrail_stability(validated_outcomes: pd.DataFrame) -> AssetCheckResult:
    """Ensure the mean risk score is within a learned boundary."""
    return _evaluate_guardrail_stability(validated_outcomes)


def _consumer_views(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``[(model_id, compiled_code), …]`` for consumer-facing views.

    Heuristic per ADR 007 line 280: consumer-facing views live under
    ``models/marts/`` and are materialised as views (tables and
    incrementals are managed by the cleaning sweep, not by the
    view-filter discipline). Anything outside ``models/marts/`` is
    treated as intermediate and exempt from the filter rule.
    """
    out: list[tuple[str, str]] = []
    for node_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") != "model":
            continue
        if node.get("config", {}).get("materialized") != "view":
            continue
        path = node.get("original_file_path") or ""
        if "models/marts/" not in path.replace("\\", "/"):
            continue
        out.append((node_id, node.get("compiled_code") or ""))
    return out


def _has_erasure_filter(sql: str) -> bool:
    """Whether ``sql`` contains the canonical ``erased = false`` predicate."""
    return bool(_ERASURE_FILTER_PATTERN.search(sql))


def _evaluate_view_filter_compliance(manifest: dict[str, Any]) -> AssetCheckResult:
    """Static check: every consumer-facing view filters ``erased = false``.

    Implements ADR 007 §2 at the Dagster layer (complementary to the
    dbt generic test of the same purpose). A vacuous pass — no
    consumer views found — is the expected state until Phase-2-revisit
    introduces ``models/marts/``; the check exists now so that the
    moment a view lands without the filter, ops sees red.
    """
    views = _consumer_views(manifest)
    convention = "WHERE erased = false"
    if not views:
        return AssetCheckResult(
            passed=True,
            description="No consumer-facing views found under models/marts/.",
            metadata={"n_views": 0, "n_violations": 0, "convention": convention},
        )
    violations = sorted(vid for vid, sql in views if not _has_erasure_filter(sql))
    passed = not violations
    if passed:
        description = f"All {len(views)} consumer-facing views filter `{convention}`."
    else:
        description = (
            f"{len(violations)}/{len(views)} consumer-facing views are missing "
            f"`{convention}`: {violations}"
        )
    return AssetCheckResult(
        passed=passed,
        description=description,
        metadata={
            "n_views": len(views),
            "n_violations": len(violations),
            "violations": violations,
            "convention": convention,
        },
    )


@asset_check(asset="raw_proposals")
def check_view_filter_compliance() -> AssetCheckResult:
    """Static check over the dbt manifest for ADR 007 view-filter discipline.

    Bound to ``raw_proposals`` because every current view ultimately
    reads from the raw source; the check itself is a property of the
    dbt project, not of the asset's data, so it takes no inputs.
    """
    if not DBT_MANIFEST_PATH.exists():
        return AssetCheckResult(
            passed=False,
            description=(
                f"dbt manifest not found at {DBT_MANIFEST_PATH}. Run `dbt parse` from python/dbt/."
            ),
            metadata={"manifest_path": str(DBT_MANIFEST_PATH)},
        )
    manifest = json.loads(DBT_MANIFEST_PATH.read_text())
    return _evaluate_view_filter_compliance(manifest)


@asset_check(asset="rejection_letters")
def check_cortex_budget(cortex: CortexResource) -> AssetCheckResult:
    """Fail when realised Cortex utilisation exceeds the soft warning threshold.

    Reads ``total_tokens`` and ``budget_max`` from the same
    ``CortexResource`` instance the rejection-letter asset wrote to —
    Dagster manages resource lifecycle per run, so the same instance is
    shared across all assets and checks within one materialisation.

    Hard-cap overrun is signalled by the *asset* failing
    (``BudgetedCortex`` raises ``BudgetExceededError`` mid-run). This
    check is the *soft-threshold* warning: it fails when utilisation
    crosses ``warn_utilisation`` of the cap, giving ops a signal to
    raise the cap before the next run hits the hard ceiling.
    """
    total = cortex.total_tokens
    cap = cortex.budget_max
    threshold = cortex.warn_utilisation

    if cap <= 0:
        return AssetCheckResult(
            passed=True,
            description=f"Cortex spend {total} tokens (no cap configured)",
            metadata={"total_tokens": total, "budget": cap, "utilisation_pct": 0.0},
        )

    utilisation = total / cap
    passed = utilisation < threshold
    description = (
        f"Cortex spend {total}/{cap} tokens "
        f"({utilisation * 100:.1f}% of cap; "
        f"warn threshold {threshold * 100:.0f}%)"
    )
    return AssetCheckResult(
        passed=passed,
        description=description,
        metadata={
            "total_tokens": total,
            "budget": cap,
            "utilisation_pct": utilisation * 100,
            "warn_threshold_pct": threshold * 100,
        },
    )
