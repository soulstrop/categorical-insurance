"""Dagster Asset Checks for the insurance pipeline."""

import pandas as pd
from dagster import AssetCheckResult, asset_check

from catins.orchestration.assets import JointProposal
from catins.orchestration.resources import CortexResource

MAX_PORTFOLIO_RISK_SCORE = 0.6


@asset_check(asset="raw_proposals")
def check_schema_drift(raw_proposals: pd.DataFrame) -> AssetCheckResult:
    """Ensure the DataFrame columns match the Pydantic Proposal fields."""
    expected_fields = set(JointProposal.model_fields.keys())
    actual_columns = set(raw_proposals.columns)

    missing = expected_fields - actual_columns
    extra = actual_columns - expected_fields

    passed = len(missing) == 0
    description = "Schema matches Pydantic Proposal."

    if not passed:
        description = f"Schema drift detected. Missing: {missing}, Extra: {extra}"

    return AssetCheckResult(
        passed=passed,
        description=description,
        metadata={
            "missing_columns": list(missing),
            "extra_columns": list(extra),
        },
    )


@asset_check(asset="validated_outcomes")
def check_guardrail_stability(validated_outcomes: pd.DataFrame) -> AssetCheckResult:
    """Ensure the mean risk score is within a learned boundary."""
    # Payload is (violations, risk_score)
    scores = [payload[1] for payload in validated_outcomes["payload"]]

    if not scores:
        return AssetCheckResult(passed=True, description="No scores to evaluate.")

    mean_score = sum(scores) / len(scores)

    passed = mean_score < MAX_PORTFOLIO_RISK_SCORE

    return AssetCheckResult(
        passed=passed,
        description=f"Mean risk score is {mean_score:.2f}",
        metadata={"mean_score": mean_score},
    )


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
