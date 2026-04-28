"""Linear regression as a gradient learner.

This module provides a linear regression model as a Learner,
mirroring math.tex §III.B.
"""

import numpy as np

from catins.learner import Learner


class Lin(Learner[np.ndarray, np.ndarray | list[float], float]):
    """Standard linear regression with online SGD.

    # math: math.tex §III.B
    """

    def __init__(self, eta: float, dim: int):
        """Initialise with learning rate and dimension of input space.

        Args:
            eta: Learning rate (η > 0).
            dim: Dimension of the input space A = ℝ^dim.
        """
        self.state = np.zeros(dim)
        self.eta = eta

    def implement(self, a: np.ndarray | list[float]) -> float:
        """Forward pass: I(w, x) = w · x."""
        x = np.asarray(a)
        return float(np.dot(self.state, x))

    def update(self, a: np.ndarray | list[float], b: float) -> np.ndarray:
        """Backward pass: w - η(w · x - y)x."""
        x = np.asarray(a)
        y = b
        prediction = np.dot(self.state, x)
        self.state = self.state - self.eta * (prediction - y) * x
        return self.state

    def request(self, a: np.ndarray | list[float], b: float) -> np.ndarray:
        """Input residual/gradient: x - η(w · x - y)w."""
        x = np.asarray(a)
        y = b
        prediction = np.dot(self.state, x)
        # The request map in math.tex is x - η(w · x - y)w
        res = x - self.eta * (prediction - y) * self.state
        return np.asarray(res)
