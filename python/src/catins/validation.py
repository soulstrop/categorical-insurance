"""Validation and the Governed comonad.

This module provides the Governed context and the validate function,
mirroring math.tex Section V and VI.
"""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from catins.decision import DecisionSystem, evaluate
from catins.models import Contract, Proposal
from catins.monoid import ListMonoid, Monoid


class Governed[P: Proposal, M](BaseModel):
    """The Governed comonad (Env comonad analog).

    # math: math.tex Definition 7

    Carries a proposal and the decision system context.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    proposal: P
    decisions: DecisionSystem[P, M]


def validate[P: Proposal, M](
    governed: Governed[P, M],
    adm: Callable[[M], bool],
    monoid: type[Monoid[M]] = ListMonoid,  # type: ignore
) -> M | Contract[M]:
    """Validate a proposal against a decision system.

    # math: math.tex Definition 13

    Returns the aggregate monoid payload M if rejected,
    or a Contract[M] if admitted.
    """
    m = evaluate(governed.decisions, governed.proposal, monoid)
    if adm(m):
        return Contract._from_validated(governed.proposal, m)
    return m
