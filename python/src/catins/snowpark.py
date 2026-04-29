"""Snowpark vectorized UDF adaptation.

This module provides a factory to lift row-level categorical validation
into vectorized functions compatible with Snowpark and Pandas.
"""

from collections.abc import Callable
from typing import Any, TypeVar

import pandas as pd
from pydantic import TypeAdapter

from catins.decision import DecisionSystem, evaluate
from catins.models import Proposal
from catins.monoid import ListMonoid, Monoid

M = TypeVar("M")
P = TypeVar("P", bound=Proposal)


def serialize_payload(payload: Any) -> Any:
    """Serialize a monoid payload into JSON-compatible primitives."""
    if isinstance(payload, tuple):
        return tuple(serialize_payload(x) for x in payload)
    if isinstance(payload, list):
        return [serialize_payload(v) for v in payload]
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload


def vectorize_validator[P: Proposal, M](
    proposal_cls: type[P],
    decisions: DecisionSystem[P, M],
    adm: Callable[[M], bool],
    monoid: type[Monoid[M]] = ListMonoid,  # type: ignore
) -> Callable[..., pd.Series]:
    """Lift a decision system into a Pandas-vectorized UDF.

    Args:
        proposal_cls: The Pydantic Proposal type to deserialize rows into.
        decisions: The decision system to evaluate.
        adm: The admission predicate.
        monoid: The monoid carrier.

    Returns:
        A callable taking Pandas Series as arguments (matching the
        fields of the Proposal) and returning a Series of
        (admitted: bool, payload: serialized_M) tuples.
    """
    # Create a TypeAdapter for bulk parsing: list[dict] -> list[Proposal]
    adapter = TypeAdapter(list[proposal_cls])  # type: ignore[valid-type]

    def udf(*args: pd.Series) -> pd.Series:
        if not args:
            return pd.Series([])

        # Assume args are passed in order of the model's fields.
        # Construct a DataFrame from the Series arguments to easily convert to dicts.
        fields = list(proposal_cls.model_fields.keys())
        df = pd.DataFrame(dict(zip(fields, args, strict=True)))

        # Convert to list of dicts for bulk instantiation
        records = df.to_dict(orient="records")
        proposals = adapter.validate_python(records)

        results = []
        for p in proposals:
            m = evaluate(decisions, p, monoid)
            admitted = adm(m)
            payload = serialize_payload(m)
            results.append((admitted, payload))

        return pd.Series(results)

    return udf
