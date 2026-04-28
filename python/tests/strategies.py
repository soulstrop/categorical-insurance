"""Centralised Hypothesis strategies for the catins test suite.

This module provides named generators for proposals, learners, and
monoid elements, used for property-based testing.
"""

from hypothesis import strategies as st

from catins.models import Proposal, Violation


def violations() -> st.SearchStrategy[Violation]:
    """Strategy for generating a single Violation."""
    return st.builds(Violation)


def violation_lists() -> st.SearchStrategy[list[Violation]]:
    """Strategy for generating lists of violations."""
    return st.lists(violations())


def floats() -> st.SearchStrategy[float]:
    """Strategy for generating finite floats."""
    return st.floats(allow_nan=False, allow_infinity=False)


def proposals[P: Proposal](proposal_cls: type[P]) -> st.SearchStrategy[P]:
    """Strategy for generating a specific Proposal type."""
    return st.builds(proposal_cls)
