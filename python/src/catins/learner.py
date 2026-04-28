"""Categorical learners.

This module provides the Learner protocol, mapping to the optic-like
quadruple (s, implement, update, request).
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Learner[S, A, B](Protocol):
    """A categorical learner.

    # math: math.tex Definition 3
    """

    state: S

    def implement(self, a: A) -> B:
        """Forward pass: map input to prediction given current state."""
        ...

    def update(self, a: A, b: B) -> S:
        """Backward pass: update state given input and target/residual."""
        ...

    def request(self, a: A, b: B) -> A:
        """Input gradient/residual to pass upstream."""
        ...
