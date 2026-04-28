"""Tests for Dagster orchestration and asset checks.

This module validates that the categorical decision system can be correctly
lifted into a Dagster Software-Defined Asset graph, including proper
execution of asset checks.
"""

from dagster import materialize

from catins.orchestration.assets import (
    partitioned_outcomes,
    raw_proposals,
    rejection_letters,
    validated_outcomes,
)
from catins.orchestration.checks import check_guardrail_stability, check_schema_drift


def test_dagster_materialization() -> None:
    """The full asset graph can be materialized in memory."""
    # Materialize the assets and checks
    result = materialize(
        [
            raw_proposals,
            validated_outcomes,
            partitioned_outcomes,
            rejection_letters,
            check_guardrail_stability,
            check_schema_drift,
        ]
    )

    assert result.success
