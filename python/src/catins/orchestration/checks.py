"""Dagster Asset Checks for the insurance pipeline."""

from typing import Any

import pandas as pd
from dagster import AssetCheckResult, asset_check

from catins.dbt import expected_columns
from catins.models import CanonicalProposal
from catins.orchestration.resources import CortexResource

MAX_PORTFOLIO_RISK_SCORE = 0.6

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
