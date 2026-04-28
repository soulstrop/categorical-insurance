"""Core data models.

This module provides the Pydantic models for Proposals, Contracts, and
Violations, enforcing the categorical abstraction barriers.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class Violation(BaseModel):
    """A governance rule violation.

    # math: math.tex Definition 6
    """

    rule_name: str
    message: str
    context: dict[str, Any] = {}


class Proposal(BaseModel):
    """A base class for insurance proposals.

    All concrete proposals should inherit from this.
    """

    model_config = ConfigDict(frozen=True)


class Contract[M](BaseModel):
    """A constructed insurance contract.

    # math: math.tex Definition 8

    The constructor is conventionally private. Use `_from_validated`
    within the framework to construct contracts.
    """

    model_config = ConfigDict(frozen=True)

    proposal: Proposal
    payload: M

    @classmethod
    def _from_validated(cls, proposal: Proposal, payload: M) -> "Contract[M]":
        """Internal constructor for validated contracts."""
        return cls(proposal=proposal, payload=payload)
