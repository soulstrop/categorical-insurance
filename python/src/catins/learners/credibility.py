"""Bühlmann credibility learner.

This module provides a Bayesian credibility model as a Learner,
mirroring Examples.Credibility in the Haskell sketch.
"""

from dataclasses import dataclass

from catins.learner import Learner


@dataclass(frozen=True)
class CredState:
    """State for the credibility learner: (mean, precision)."""

    mean: float
    precision: float


class BuhlmannCredibility(Learner[CredState, None, float]):
    """Normal-Normal conjugate credibility model.

    # math: math.tex worked example §IV
    """

    def __init__(self, mu0: float, kappa0: float, sigma2: float):
        """Initialise with prior mean, prior precision, and observation variance.

        Args:
            mu0: Prior mean (μ₀).
            kappa0: Prior precision on the mean (κ₀ = 1/τ₀²).
            sigma2: Observation noise variance (σ²).
        """
        self.state = CredState(mu0, kappa0)
        self.sigma2 = sigma2

    def implement(self, _a: None) -> float:
        """Prediction is the current posterior mean."""
        return self.state.mean

    def update(self, _a: None, b: float) -> CredState:
        """Precision-weighted mean update.

        mu' = (kappa * mu + pObs * x) / (kappa + pObs)
        """
        p_obs = 1.0 / self.sigma2
        kappa_new = self.state.precision + p_obs
        mu_new = (self.state.precision * self.state.mean + p_obs * b) / kappa_new

        self.state = CredState(mu_new, kappa_new)
        return self.state

    def request(self, _a: None, _b: float) -> None:
        """Credibility is a terminal learner (empty request map)."""
        return
