"""Categorical insurance: production-target framework.

This package implements the categorical decision-system framework
described in ``../docs/math.tex`` and reflected in the Haskell sketch
under ``../haskell/``.
"""

from catins.dbt import generate_dbt_source_contract
from catins.decision import Decision, DecisionSystem, evaluate
from catins.learner import Learner
from catins.models import Contract, Proposal, Violation
from catins.monoid import ListMonoid, Monoid
from catins.snowpark import vectorize_validator
from catins.validation import Governed, validate

__all__ = [
    "Proposal",
    "Violation",
    "Contract",
    "Decision",
    "DecisionSystem",
    "evaluate",
    "Governed",
    "validate",
    "Monoid",
    "ListMonoid",
    "Learner",
    "vectorize_validator",
    "generate_dbt_source_contract",
]

__version__ = "0.1.0"
