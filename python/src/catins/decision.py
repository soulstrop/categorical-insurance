"""Decision systems parameterised by a monoid.

This module provides the Decision and DecisionSystem abstractions,
mirroring math.tex Section VI and ADR 004.
"""

from collections.abc import Callable
from typing import TypeVar

from catins.models import Proposal
from catins.monoid import Monoid

M = TypeVar("M")
P = TypeVar("P", bound=Proposal)

# A Decision is a function from a proposal to a monoid element.
# math: math.tex Definition 10
Decision = Callable[[P], M]

# A DecisionSystem is a list of decisions.
# In production, this can be combined into a single co-Kleisli arrow.
DecisionSystem = list[Decision[P, M]]


def evaluate[P: Proposal, M](
    system: DecisionSystem[P, M], proposal: P, monoid: type[Monoid[M]]
) -> M:
    """Aggregate a decision system over a proposal.

    # math: math.tex Definition 11
    """
    out = monoid.empty()
    for decision in system:
        out = monoid.combine(out, decision(proposal))
    return out
