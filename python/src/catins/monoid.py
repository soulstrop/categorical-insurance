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


class RiskScoreMonoid:
    """The additive monoid on non-negative reals for risk scoring."""

    @staticmethod
    def empty() -> float:
        return 0.0

    @staticmethod
    def combine(x: float, y: float) -> float:
        return x + y


def product_monoid[M1, M2](
    m1: type[Monoid[M1]], m2: type[Monoid[M2]]
) -> type[Monoid[tuple[M1, M2]]]:
    """Return the product monoid of two monoids.

    # math: math.tex §VI.C
    """

    class Product:
        @staticmethod
        def empty() -> tuple[M1, M2]:
            return (m1.empty(), m2.empty())

        @staticmethod
        def combine(x: tuple[M1, M2], y: tuple[M1, M2]) -> tuple[M1, M2]:
            return (m1.combine(x[0], y[0]), m2.combine(x[1], y[1]))

    return Product  # type: ignore[return-value]
