"""Dagster Asset Checks for the insurance pipeline."""

import pandas as pd
from dagster import AssetCheckResult, asset_check

from catins.orchestration.assets import JointProposal

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
