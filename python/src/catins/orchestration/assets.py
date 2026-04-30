"""Dagster Software-Defined Assets for the insurance validation pipeline."""

from typing import Any

import pandas as pd
from dagster import AssetOut, asset, multi_asset

from catins.cortex import explain_rejection
from catins.models import CanonicalProposal, Violation
from catins.monoid import ListMonoid, RiskScoreMonoid, product_monoid
from catins.orchestration.resources import CortexResource
from catins.snowpark import vectorize_validator

# JointProposal is an alias for CanonicalProposal: the Phase 2/3 joint
# (Governance × Guardrail) decision system operates over the canonical
# proposal shape that is the single source of truth across Pydantic
# and dbt.
JointProposal = CanonicalProposal


# The product monoid for Joint (Governance x Guardrail) decisions
JointMonoid = product_monoid(ListMonoid, RiskScoreMonoid)  # type: ignore
YOUNG_DRIVER_AGE_THRESHOLD = 25


# 1. Decisions
def rule_positive_premium(p: JointProposal) -> tuple[list[Violation], float]:
    """Governance: Premium must be positive."""
    if p.premium <= 0:
        return ([Violation(rule_name="premium", message="Negative premium")], 0.0)
    return ([], 0.0)


def risk_score_zip(p: JointProposal) -> tuple[list[Violation], float]:
    """Guardrail: Adds 0.5 risk for certain zip codes."""
    if p.zip_code.startswith("9"):
        return ([], 0.5)
    return ([], 0.0)


def risk_score_age(p: JointProposal) -> tuple[list[Violation], float]:
    """Guardrail: Adds 0.3 risk for young drivers."""
    if p.age < YOUNG_DRIVER_AGE_THRESHOLD:
        return ([], 0.3)
    return ([], 0.0)


# Admission predicate: no governance violations AND risk score < 1.0
def is_admissible(m: tuple[list[Any], float]) -> bool:
    violations, score = m
    return len(violations) == 0 and score < 1.0


# The compiled vectorized UDF
joint_udf = vectorize_validator(
    proposal_cls=JointProposal,
    decisions=[rule_positive_premium, risk_score_zip, risk_score_age],
    adm=is_admissible,
    monoid=JointMonoid,
)


@asset
def raw_proposals() -> pd.DataFrame:
    """Mock ingest of unstructured data extracted via Cortex."""
    return pd.DataFrame(
        [
            {"holder": "Alice", "premium": 100.0, "zip_code": "10001", "age": 30},
            {"holder": "Bob", "premium": -50.0, "zip_code": "90210", "age": 25},
            {"holder": "Charlie", "premium": 250.0, "zip_code": "94102", "age": 20},
        ]
    )


@asset
def validated_outcomes(raw_proposals: pd.DataFrame) -> pd.DataFrame:
    """Apply the vectorized joint decision system."""
    # Apply UDF
    results_series = joint_udf(
        raw_proposals["holder"],
        raw_proposals["premium"],
        raw_proposals["zip_code"],
        raw_proposals["age"],
    )

    # The UDF returns a Series of tuples (admitted: bool, payload: M).
    # Expand this into separate columns so it plays nice with Dagster/DataFrames.
    df = raw_proposals.copy()

    # We zip through the series to unpack
    admitted = []
    payload = []
    for adm, pld in results_series:
        admitted.append(adm)
        payload.append(pld)

    df["admitted"] = admitted
    df["payload"] = payload
    return df


@multi_asset(
    outs={
        "contracts": AssetOut(),
        "rejections": AssetOut(),
    }
)
def partitioned_outcomes(validated_outcomes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split validation results into accepted contracts and rejections."""
    is_admitted = validated_outcomes["admitted"].astype(bool)
    contracts_df = validated_outcomes[is_admitted].copy()
    rejections_df = validated_outcomes[~is_admitted].copy()
    return contracts_df, rejections_df


@asset
def rejection_letters(rejections: pd.DataFrame, cortex: CortexResource) -> pd.DataFrame:
    """Generate human-readable rejection letters via the Cortex resource."""
    letters = []
    for _, row in rejections.iterrows():
        # Payload is (list[dict], float) after JSON-friendly serialisation.
        violations_dicts, risk_score = row["payload"]
        violations = [Violation(**v) for v in violations_dicts]
        letter = explain_rejection(cortex, violations, risk_score)
        letters.append(letter)

    df = rejections.copy()
    df["explanation"] = letters
    return df
