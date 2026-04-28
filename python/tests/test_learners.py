"""Tests for categorical learners."""

import pytest

from catins.learners.credibility import BuhlmannCredibility
from catins.learners.linear import Lin


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


def test_linear_regression_convergence() -> None:
    """The linear regression learner converges on a simple dataset."""
    # y = 2x + 1
    # For simplicity in Phase 1, we'll implement Lin as y = w*x (no bias yet, or bias included in x)
    # If we want y = 2x + 1, we can use x' = [x, 1] and w = [2, 1]
    learner = Lin(eta=0.01, dim=2)

    # Train on some points
    for _ in range(500):
        # point x=1.0, y=3.0
        learner.update([1.0, 1.0], 3.0)
        # point x=2.0, y=5.0
        learner.update([2.0, 1.0], 5.0)

    # Predicted for x=3.0, 1.0 should be ~7.0
    assert learner.implement([3.0, 1.0]) == pytest.approx(7.0, abs=0.1)
