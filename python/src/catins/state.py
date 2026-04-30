"""State reconstruction from history.

# math: math.tex §VII.C (Append-only observation table; derived state)

For *closed-form* learners (e.g. Bühlmann credibility), current state is
a deterministic SQL aggregation over an append-only observation table.
For *sequential* learners that cannot be expressed as such an aggregation
(e.g. SGD-trained linear regression), we maintain a separate
``learner_state`` table keyed by ``(learner_id, version)`` written by
scheduled Python training jobs.

The two together close Phase 2 done condition #2: given a contract, we
can reconstruct the learner state used to score it.
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from catins.learners.credibility import BuhlmannCredibility, CredState
from catins.warehouse import WarehouseSession

# -- DDL -----------------------------------------------------------------

# Append-only observation log for closed-form learners.
OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS state_observations (
    learner_id  VARCHAR,
    ts          TIMESTAMP,
    observation DOUBLE,
    sigma2      DOUBLE,
    mu0         DOUBLE,
    kappa0      DOUBLE
)
"""

# Snapshot table for sequential learners (e.g. SGD-trained models)
# whose state cannot be derived from a SQL aggregation alone.
LEARNER_STATE_DDL = """
CREATE TABLE IF NOT EXISTS learner_state (
    learner_id  VARCHAR,
    version     BIGINT,
    ts          TIMESTAMP,
    state_json  VARCHAR
)
"""

# Derived view: precision-weighted Bühlmann state per learner_id.
#
#   posterior_precision = kappa0 + n / sigma2
#   posterior_mean      = (kappa0 * mu0 + sum(observation) / sigma2) / posterior_precision
#
# We carry kappa0/mu0/sigma2 on every observation row so a learner that
# is rebooted with a different prior is reconstructed against *its* prior.
# Multiple priors per learner_id is undefined behaviour; the harness
# enforces single-prior writes.
CURRENT_STATE_VIEW_DDL = """
CREATE OR REPLACE VIEW current_state AS
WITH agg AS (
    SELECT
        learner_id,
        ANY_VALUE(mu0)    AS mu0,
        ANY_VALUE(kappa0) AS kappa0,
        ANY_VALUE(sigma2) AS sigma2,
        COUNT(*)          AS n,
        SUM(observation)  AS sum_obs
    FROM state_observations
    GROUP BY learner_id
)
SELECT
    learner_id,
    (kappa0 + n / sigma2) AS posterior_precision,
    ((kappa0 * mu0 + sum_obs / sigma2) / (kappa0 + n / sigma2)) AS posterior_mean,
    n
FROM agg
"""


# -- Python-side helpers -------------------------------------------------


@dataclass(frozen=True)
class ObservationRow:
    learner_id: str
    ts: pd.Timestamp
    observation: float
    sigma2: float
    mu0: float
    kappa0: float


def init_state_tables(session: WarehouseSession) -> None:
    """Create the observation log, snapshot table, and derived view."""
    session.sql(OBSERVATIONS_DDL)
    session.sql(LEARNER_STATE_DDL)
    session.sql(CURRENT_STATE_VIEW_DDL)


def append_observations(session: WarehouseSession, rows: list[ObservationRow]) -> None:
    """Append observations to ``state_observations`` (idempotent w.r.t. ts)."""
    if not rows:
        return
    df = pd.DataFrame([row.__dict__ for row in rows])
    session.write_table(df, "state_observations", mode="append")


def reconstruct_credibility(session: WarehouseSession, learner_id: str) -> CredState:
    """Read the SQL-derived current state for a Bühlmann credibility learner."""
    df = session.sql(
        f"SELECT posterior_mean, posterior_precision FROM current_state "
        f"WHERE learner_id = '{learner_id}'"
    )
    if df.empty:
        msg = f"no observations for learner_id='{learner_id}'"
        raise LookupError(msg)
    row = df.iloc[0]
    return CredState(mean=float(row["posterior_mean"]), precision=float(row["posterior_precision"]))


def snapshot_learner_state(
    session: WarehouseSession,
    learner_id: str,
    version: int,
    state_json: str,
    ts: pd.Timestamp | None = None,
) -> None:
    """Write a state snapshot for a sequential learner."""
    df = pd.DataFrame(
        [
            {
                "learner_id": learner_id,
                "version": version,
                "ts": ts or pd.Timestamp.now(tz="UTC"),
                "state_json": state_json,
            }
        ]
    )
    session.write_table(df, "learner_state", mode="append")


def latest_learner_state(session: WarehouseSession, learner_id: str) -> dict[str, Any]:
    """Read the most recent snapshot for a sequential learner."""
    df = session.sql(
        "SELECT version, state_json FROM learner_state "
        f"WHERE learner_id = '{learner_id}' "
        "ORDER BY version DESC LIMIT 1"
    )
    if df.empty:
        msg = f"no snapshot for learner_id='{learner_id}'"
        raise LookupError(msg)
    import json  # noqa: PLC0415  (defer-importing the stdlib reader)

    row = df.iloc[0]
    return {"version": int(row["version"]), "state": json.loads(row["state_json"])}


def replay_to_python(rows: list[ObservationRow]) -> CredState:
    """Replay an observation list through the in-memory Bühlmann learner.

    Used by tests as the source of truth that the SQL view is computing
    the same precision-weighted aggregation.
    """
    if not rows:
        msg = "empty observation list"
        raise ValueError(msg)
    head = rows[0]
    learner = BuhlmannCredibility(mu0=head.mu0, kappa0=head.kappa0, sigma2=head.sigma2)
    for row in rows:
        learner.update(None, row.observation)
    return learner.state
