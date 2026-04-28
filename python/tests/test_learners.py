"""Tests for categorical learners."""

import pytest

from catins.learners.credibility import BuhlmannCredibility


def test_buhlmann_credibility_update() -> None:
    """The credibility learner updates its mean correctly."""
    # Prior: mean=100, precision=0.01 (tau0^2 = 100)
    # Observation noise: sigma2=25
    learner = BuhlmannCredibility(mu0=100.0, kappa0=0.01, sigma2=25.0)

    assert learner.implement(None) == 100.0

    # Observe x=110
    # pObs = 1/25 = 0.04
    # kappa' = 0.01 + 0.04 = 0.05
    # mu' = (0.01 * 100 + 0.04 * 110) / 0.05 = (1 + 4.4) / 0.05 = 5.4 / 0.05 = 108
    new_state = learner.update(None, 110.0)

    assert new_state.mean == pytest.approx(108.0)
    assert new_state.precision == pytest.approx(0.05)
    assert learner.implement(None) == pytest.approx(108.0)
