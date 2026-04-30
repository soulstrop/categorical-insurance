"""End-to-end test of the warehouse-native validation pipeline.

Seeds a staging table, registers the joint validator as a SQL UDF on a
DuckDB session, and asserts that the resulting ``contracts``,
``rejections``, and ``rejection_summary`` artefacts match expectations.
"""

import pandas as pd

from catins.models import CanonicalProposal, Violation
from catins.monoid import ListMonoid, RiskScoreMonoid, product_monoid
from catins.snowpark import register_validator, run_validation_pipeline
from catins.warehouse import DuckDBSession

JointMonoid = product_monoid(ListMonoid, RiskScoreMonoid)
RISK_CAP = 1.0
YOUNG_DRIVER_AGE = 25


def rule_positive_premium(p: CanonicalProposal) -> tuple[list[Violation], float]:
    if p.premium <= 0:
        return ([Violation(rule_name="premium", message="Negative premium")], 0.0)
    return ([], 0.0)


def risk_score_zip(p: CanonicalProposal) -> tuple[list[Violation], float]:
    if p.zip_code.startswith("9"):
        return ([], 0.5)
    return ([], 0.0)


def risk_score_age(p: CanonicalProposal) -> tuple[list[Violation], float]:
    if p.age < YOUNG_DRIVER_AGE:
        return ([], 0.6)
    return ([], 0.0)


def is_admissible(m: tuple[list[Violation], float]) -> bool:
    violations, score = m
    return len(violations) == 0 and score < RISK_CAP


def test_pipeline_materialises_contracts_and_rejections() -> None:
    session = DuckDBSession()
    session.write_table(
        pd.DataFrame(
            [
                {"holder": "Alice", "premium": 100.0, "zip_code": "10001", "age": 30},
                {"holder": "Bob", "premium": -50.0, "zip_code": "94102", "age": 25},
                {"holder": "Charlie", "premium": 250.0, "zip_code": "94102", "age": 20},
                {"holder": "Dee", "premium": 200.0, "zip_code": "10001", "age": 60},
            ]
        ),
        "stg_proposals",
    )

    register_validator(
        session,
        name="validate_proposal",
        proposal_cls=CanonicalProposal,
        decisions=[rule_positive_premium, risk_score_zip, risk_score_age],
        adm=is_admissible,
        monoid=JointMonoid,
    )

    counts = run_validation_pipeline(
        session, udf_name="validate_proposal", proposal_cls=CanonicalProposal
    )

    # Alice: clean, score 0.0           -> contract
    # Bob:   negative premium           -> rejection (governance)
    # Charlie: zip 94102 + young (0.5+0.6=1.1 >= 1.0) -> rejection (guardrail)
    # Dee:   clean, score 0.0           -> contract
    assert counts == {"contracts": 2, "rejections": 2}

    contracts = session.read_table("contracts")
    assert sorted(contracts["holder"].tolist()) == ["Alice", "Dee"]

    rejections = session.read_table("rejections")
    assert sorted(rejections["holder"].tolist()) == ["Bob", "Charlie"]

    summary = session.sql("SELECT rule_name, n FROM rejection_summary ORDER BY rule_name")
    assert summary["rule_name"].tolist() == ["premium"]
    assert summary["n"].tolist() == [1]


def test_pipeline_admits_all_clean_baseline() -> None:
    session = DuckDBSession()
    session.write_table(
        pd.DataFrame(
            [
                {"holder": "Alice", "premium": 100.0, "zip_code": "10001", "age": 30},
                {"holder": "Dee", "premium": 200.0, "zip_code": "10001", "age": 60},
            ]
        ),
        "stg_proposals",
    )

    register_validator(
        session,
        name="validate_proposal",
        proposal_cls=CanonicalProposal,
        decisions=[rule_positive_premium, risk_score_zip, risk_score_age],
        adm=is_admissible,
        monoid=JointMonoid,
    )
    counts = run_validation_pipeline(
        session, udf_name="validate_proposal", proposal_cls=CanonicalProposal
    )
    assert counts == {"contracts": 2, "rejections": 0}
