"""Tests for Snowpark vectorized validation.

This module ensures that the validate function can be lifted to operate
efficiently over Pandas DataFrames/Series, representing the Phase 2
warehouse-native execution model.
"""

import pandas as pd

from catins.models import Proposal, Violation
from catins.snowpark import vectorize_validator


class MockSnowparkProposal(Proposal):
    holder: str
    premium: float
    age: int


def rule_positive_premium(p: MockSnowparkProposal) -> list[Violation]:
    if p.premium <= 0:
        return [
            Violation(
                rule_name="premium_check",
                message="Negative premium",
                context={"p": p.premium},
            )
        ]
    return []


def rule_adult(p: MockSnowparkProposal) -> list[Violation]:
    if p.age < 18:
        return [
            Violation(
                rule_name="age_check",
                message="Must be an adult",
                context={"age": p.age},
            )
        ]
    return []


def test_vectorize_validator_pandas() -> None:
    """A vectorized validator correctly processes a Pandas DataFrame."""
    # 1. Setup sample data
    data = [
        {"holder": "Alice", "premium": 100.0, "age": 30},
        {"holder": "Bob", "premium": -50.0, "age": 25},
        {"holder": "Charlie", "premium": 250.0, "age": 16},
    ]
    df = pd.DataFrame(data)

    # 2. Create the vectorized UDF
    decisions = [rule_positive_premium, rule_adult]
    validator_udf = vectorize_validator(
        proposal_cls=MockSnowparkProposal,
        decisions=decisions,
        adm=lambda m: len(m) == 0,
    )

    # 3. Apply the UDF
    # The UDF should take the fields (as kwargs or Series) and return a Series of tuples
    # (admitted: bool, payload: list[dict])
    results = validator_udf(df["holder"], df["premium"], df["age"])

    # 4. Assert correctness
    assert len(results) == 3

    # Alice: clean
    assert results[0][0] is True
    assert len(results[0][1]) == 0

    # Bob: premium violation
    assert results[1][0] is False
    assert len(results[1][1]) == 1
    assert results[1][1][0]["rule_name"] == "premium_check"

    # Charlie: age violation
    assert results[2][0] is False
    assert len(results[2][1]) == 1
    assert results[2][1][0]["rule_name"] == "age_check"
