"""Dagster ``Definitions`` for the catins pipeline.

# math: math.tex §VII (asset graph as object of orchestration)

Exposes assets, asset checks, jobs, and resources so that
``dagster dev`` can render and serve the catins pipeline. The
sandbox-time switch from ``MockCortex`` to a real Cortex client (and
from ``DuckDBSession`` to a Snowpark ``Session``) is a resource swap
on this object; nothing in the asset graph itself changes.
"""

from dagster import Definitions, define_asset_job

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
from catins.orchestration.resources import CortexResource, WarehouseResource

CATINS_VALIDATION_JOB_NAME = "catins_validation_job"

catins_job = define_asset_job(name=CATINS_VALIDATION_JOB_NAME, selection="*")


defs = Definitions(
    assets=[
        raw_proposals,
        validated_outcomes,
        partitioned_outcomes,
        rejection_letters,
    ],
    asset_checks=[check_schema_drift, check_guardrail_stability, check_cortex_budget],
    jobs=[catins_job],
    resources={
        "cortex": CortexResource(max_tokens=5_000),
        "warehouse": WarehouseResource(database=":memory:"),
    },
)


__all__ = ["CATINS_VALIDATION_JOB_NAME", "catins_job", "defs"]
