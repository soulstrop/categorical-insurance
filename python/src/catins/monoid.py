"""Categorical monoids.

This module provides the Monoid protocol and common implementations,
mirroring the Haskell Monoid class.
"""

from typing import Any, Protocol, TypeVar, runtime_checkable

M = TypeVar("M")


@runtime_checkable
class Monoid(Protocol[M]):
    """A protocol for monoids.

    # math: math.tex Definition 1
    """

    @staticmethod
    def empty() -> M:
        """The identity element of the monoid."""
        ...

    @staticmethod
    def combine(x: M, y: M) -> M:
        """The associative binary operation."""
        ...


class ListMonoid:
    """The free monoid on lists under concatenation."""

    @staticmethod
    def empty() -> list[Any]:
        return []

    @staticmethod
    def combine(x: list[Any], y: list[Any]) -> list[Any]:
        return x + y
