"""Dagster ``Definitions`` for the catins pipeline.

# math: math.tex §VII (asset graph as object of orchestration)

Exposes assets, asset checks, jobs, and resources so that
``dagster dev`` can render and serve the catins pipeline. The
sandbox-time switch from ``MockCortex`` to a real Cortex client (and
from ``DuckDBSession`` to a Snowpark ``Session``) is a resource swap
on this object; nothing in the asset graph itself changes.
"""

from dagster import Definitions, ScheduleDefinition, define_asset_job

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
    check_view_filter_compliance,
)
from catins.orchestration.resources import CortexResource, WarehouseResource

CATINS_VALIDATION_JOB_NAME = "catins_validation_job"
CATINS_DAILY_SCHEDULE_NAME = "catins_daily_schedule"

# Daily schedule cron: 06:00 UTC every day. Aligns with the 24-hour
# FreshnessPolicy on terminal assets (P3.3) — a successful daily run
# resets the freshness clock with 18+ hours of headroom before the
# warn threshold (12h) and fail threshold (24h) for any overnight
# delays.
CATINS_DAILY_CRON = "0 6 * * *"

catins_job = define_asset_job(name=CATINS_VALIDATION_JOB_NAME, selection="*")

catins_daily_schedule = ScheduleDefinition(
    name=CATINS_DAILY_SCHEDULE_NAME,
    job=catins_job,
    cron_schedule=CATINS_DAILY_CRON,
    execution_timezone="UTC",
)


defs = Definitions(
    assets=[
        raw_proposals,
        validated_outcomes,
        partitioned_outcomes,
        rejection_letters,
    ],
    asset_checks=[
        check_schema_drift,
        check_guardrail_stability,
        check_cortex_budget,
        check_view_filter_compliance,
    ],
    jobs=[catins_job],
    schedules=[catins_daily_schedule],
    resources={
        "cortex": CortexResource(max_tokens=5_000),
        "warehouse": WarehouseResource(database=":memory:"),
    },
)


__all__ = [
    "CATINS_DAILY_CRON",
    "CATINS_DAILY_SCHEDULE_NAME",
    "CATINS_VALIDATION_JOB_NAME",
    "catins_daily_schedule",
    "catins_job",
    "defs",
]
