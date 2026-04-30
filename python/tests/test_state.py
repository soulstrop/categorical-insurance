"""Tests for state reconstruction from history (Phase 2 done condition #2)."""

import json
import math

import pandas as pd
import pytest

from catins.state import (
    ObservationRow,
    append_observations,
    init_state_tables,
    latest_learner_state,
    reconstruct_credibility,
    replay_to_python,
    snapshot_learner_state,
)
from catins.warehouse import DuckDBSession


def _fixture_rows() -> list[ObservationRow]:
    base = pd.Timestamp("2026-01-01")
    observations = [105.0, 95.0, 110.0, 100.0, 102.0]
    return [
        ObservationRow(
            learner_id="auto-CA",
            ts=base + pd.Timedelta(days=i),
            observation=obs,
            sigma2=25.0,
            mu0=100.0,
            kappa0=0.5,
        )
        for i, obs in enumerate(observations)
    ]


def test_sql_state_matches_python_replay() -> None:
    """The current_state view computes the same posterior as the in-memory learner."""
    session = DuckDBSession()
    init_state_tables(session)

    rows = _fixture_rows()
    append_observations(session, rows)

    sql_state = reconstruct_credibility(session, learner_id="auto-CA")
    py_state = replay_to_python(rows)

    assert math.isclose(sql_state.mean, py_state.mean, rel_tol=1e-9)
    assert math.isclose(sql_state.precision, py_state.precision, rel_tol=1e-9)


def test_reconstruct_unknown_learner_raises() -> None:
    session = DuckDBSession()
    init_state_tables(session)

    with pytest.raises(LookupError):
        reconstruct_credibility(session, learner_id="missing")


def test_sequential_learner_snapshot_roundtrip() -> None:
    """A sequential learner's state can be snapshotted and read back."""
    session = DuckDBSession()
    init_state_tables(session)

    payload = {"weights": [0.1, 0.2, 0.3], "bias": 0.05}
    snapshot_learner_state(session, "lin-v1", version=1, state_json=json.dumps(payload))
    snapshot_learner_state(session, "lin-v1", version=2, state_json=json.dumps(payload))

    latest = latest_learner_state(session, "lin-v1")
    assert latest["version"] == 2
    assert latest["state"]["weights"] == [0.1, 0.2, 0.3]


def test_replay_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        replay_to_python([])
