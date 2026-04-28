"""Categorical learners.

This module provides the Learner protocol, mapping to the optic-like
quadruple (s, implement, update, request), and its algebra.
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


class IdentityLearner[A]:
    """The identity learner.

    # math: math.tex Example 2
    """

    def __init__(self) -> None:
        self.state = None

    def implement(self, a: A) -> A:
        return a

    def update(self, _a: A, _b: A) -> None:
        return

    def request(self, _a: A, b: A) -> A:
        return b


def id_learner[A]() -> Learner[None, A, A]:
    """Return an identity learner for type A."""
    return IdentityLearner[A]()  # type: ignore


class CompositeLearner[S1, S2, A, B, C]:
    """Sequential composition of two learners.

    # math: math.tex Definition 4
    """

    def __init__(self, g: Learner[S2, B, C], f: Learner[S1, A, B]):
        self.g = g
        self.f = f
        self.state = (f.state, g.state)

    def implement(self, a: A) -> C:
        return self.g.implement(self.f.implement(a))

    def update(self, a: A, c: C) -> tuple[S1, S2]:
        b_pred = self.f.implement(a)
        b_star = self.g.request(b_pred, c)
        s1 = self.f.update(a, b_star)
        s2 = self.g.update(b_pred, c)
        self.state = (s1, s2)
        return self.state

    def request(self, a: A, c: C) -> A:
        b_pred = self.f.implement(a)
        b_star = self.g.request(b_pred, c)
        return self.f.request(a, b_star)


def compose[S1, S2, A, B, C](
    g: Learner[S2, B, C], f: Learner[S1, A, B]
) -> Learner[tuple[S1, S2], A, C]:
    """Sequentially compose two learners: g . f."""
    return CompositeLearner(g, f)


class ParallelLearner[S1, S2, A, B, C, D]:
    """Parallel product of two learners.

    # math: math.tex Definition 5
    """

    def __init__(self, f: Learner[S1, A, B], g: Learner[S2, C, D]):
        self.f = f
        self.g = g
        self.state = (f.state, g.state)

    def implement(self, ac: tuple[A, C]) -> tuple[B, D]:
        a, c = ac
        return (self.f.implement(a), self.g.implement(c))

    def update(self, ac: tuple[A, C], bd: tuple[B, D]) -> tuple[S1, S2]:
        a, c = ac
        b, d = bd
        s1 = self.f.update(a, b)
        s2 = self.g.update(c, d)
        self.state = (s1, s2)
        return self.state

    def request(self, ac: tuple[A, C], bd: tuple[B, D]) -> tuple[A, C]:
        a, c = ac
        b, d = bd
        return (self.f.request(a, b), self.g.request(c, d))


def parallel[S1, S2, A, B, C, D](
    f: Learner[S1, A, B], g: Learner[S2, C, D]
) -> Learner[tuple[S1, S2], tuple[A, C], tuple[B, D]]:
    """Parallel product of two learners: f ⊗ g."""
    return ParallelLearner(f, g)
