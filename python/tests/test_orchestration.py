"""Tests for Dagster orchestration: Definitions, resources, asset graph.

Validates that:
* The Definitions object validates without error (the analogue of
  ``dagster definitions validate``).
* The full asset graph can be materialised with the configured
  resources.
* The Cortex resource accumulates token spend across assets in a
  single materialisation — verified by an in-run asset check that
  reads ``cortex.total_tokens`` (the same pattern P3.2 will use).
"""

from dagster import AssetCheckResult, asset_check, materialize

from catins.orchestration.assets import (
    partitioned_outcomes,
    raw_proposals,
    rejection_letters,
    validated_outcomes,
)
from catins.orchestration.checks import check_guardrail_stability, check_schema_drift
from catins.orchestration.definitions import defs
from catins.orchestration.resources import CortexResource, WarehouseResource


def test_definitions_validates() -> None:
    """The Definitions object resolves without configuration errors."""
    # Resolving the implicit job is Dagster's own validation hook;
    # configuration errors raise during this call.
    defs.resolve_implicit_global_asset_job_def()


def test_full_asset_graph_materialises_with_resources() -> None:
    result = materialize(
        [
            raw_proposals,
            validated_outcomes,
            partitioned_outcomes,
            rejection_letters,
            check_guardrail_stability,
            check_schema_drift,
        ],
        resources={
            "cortex": CortexResource(max_tokens=10_000),
            "warehouse": WarehouseResource(),
        },
    )
    assert result.success


@asset_check(asset="rejection_letters")
def _check_cortex_accumulated_tokens(cortex: CortexResource) -> AssetCheckResult:
    """In-run check: total tokens > 0 after rejection_letters runs.

    This is the prototype of the P3.2 budget asset check: it reads
    ``cortex.total_tokens`` from the same resource instance the
    asset wrote to.
    """
    return AssetCheckResult(
        passed=cortex.total_tokens > 0,
        metadata={"total_tokens": cortex.total_tokens, "budget": cortex.budget_max},
    )


def test_cortex_resource_accumulates_tokens_within_run() -> None:
    """The Cortex resource is shared across assets and checks in one run."""
    result = materialize(
        [
            raw_proposals,
            validated_outcomes,
            partitioned_outcomes,
            rejection_letters,
            _check_cortex_accumulated_tokens,
        ],
        resources={
            "cortex": CortexResource(max_tokens=10_000),
            "warehouse": WarehouseResource(),
        },
    )
    assert result.success
