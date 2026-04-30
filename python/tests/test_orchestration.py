"""Tests for Dagster orchestration: Definitions, resources, asset graph,
and asset checks (including the P3.2 Cortex budget check).
"""

from dagster import materialize

from catins.orchestration.assets import (
    partitioned_outcomes,
    raw_proposals,
    rejection_letters,
    validated_outcomes,
)
from catins.orchestration.checks import (
    check_cortex_budget,
    check_guardrail_stability,
    check_schema_drift,
)
from catins.orchestration.definitions import defs
from catins.orchestration.resources import CortexResource, WarehouseResource


def test_definitions_validates() -> None:
    """The Definitions object resolves without configuration errors."""
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
            check_cortex_budget,
        ],
        resources={
            "cortex": CortexResource(max_tokens=10_000),
            "warehouse": WarehouseResource(),
        },
    )
    assert result.success


def _materialize_with_cortex(cortex: CortexResource) -> object:
    return materialize(
        [
            raw_proposals,
            validated_outcomes,
            partitioned_outcomes,
            rejection_letters,
            check_cortex_budget,
        ],
        resources={"cortex": cortex, "warehouse": WarehouseResource()},
    )


def _budget_check_passed(result: object) -> bool:
    """Return whether the check_cortex_budget evaluation passed."""
    evals = result.get_asset_check_evaluations()  # type: ignore[attr-defined]
    budget_evals = [e for e in evals if e.check_name == "check_cortex_budget"]
    assert len(budget_evals) == 1, f"expected 1 check_cortex_budget eval, got {len(budget_evals)}"
    return bool(budget_evals[0].passed)


def test_cortex_budget_check_passes_under_threshold() -> None:
    """A generously-budgeted run keeps utilisation below the warn threshold."""
    cortex = CortexResource(max_tokens=10_000, warn_utilisation=0.9)
    result = _materialize_with_cortex(cortex)
    assert result.success  # type: ignore[attr-defined]
    assert _budget_check_passed(result)


def test_cortex_budget_check_fails_on_planted_overrun() -> None:
    """A tight cap pushes utilisation past the warn threshold; check fails.

    Hard cap (33) is generous enough that the asset completes; soft
    threshold (50%) is tight enough that realised utilisation (~64%)
    crosses it. The materialisation succeeds; the *check evaluation*
    reports passed=False, which is what ops sees as the early-warning
    signal in the Dagster UI.
    """
    cortex = CortexResource(max_tokens=33, warn_utilisation=0.5)
    result = _materialize_with_cortex(cortex)
    assert result.success  # type: ignore[attr-defined]
    assert not _budget_check_passed(result)
