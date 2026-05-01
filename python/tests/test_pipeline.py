"""End-to-end Phase 2 pipeline test against DuckDB + MockCortex."""

import os
import tempfile
from pathlib import Path

import pandas as pd

from catins.cortex import BudgetedCortex, MockCortex
from catins.models import SCHEMA_V1_EFFECTIVE_DATE, CanonicalProposal, Violation
from catins.monoid import ListMonoid, RiskScoreMonoid, product_monoid
from catins.pipeline import run_pipeline
from catins.warehouse import DuckDBSession

_METADATA_DEFAULTS = {
    "schema_version": 1,
    "schema_effective_date": pd.Timestamp(SCHEMA_V1_EFFECTIVE_DATE),
    "erased": False,
}

JointMonoid = product_monoid(ListMonoid, RiskScoreMonoid)
RISK_CAP = 1.0
YOUNG_DRIVER = 25
DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"


def rule_positive_premium(p: CanonicalProposal) -> tuple[list[Violation], float]:
    if p.premium <= 0:
        return ([Violation(rule_name="premium", message="Negative premium")], 0.0)
    return ([], 0.0)


def risk_zip(p: CanonicalProposal) -> tuple[list[Violation], float]:
    return ([], 0.5 if p.zip_code.startswith("9") else 0.0)


def risk_age(p: CanonicalProposal) -> tuple[list[Violation], float]:
    return ([], 0.6 if p.age < YOUNG_DRIVER else 0.0)


def is_admissible(m: tuple[list[Violation], float]) -> bool:
    violations, score = m
    return len(violations) == 0 and score < RISK_CAP


def test_pipeline_with_seeded_staging_table() -> None:
    """No dbt, no extraction: caller seeds stg_proposals directly."""
    seed_session = DuckDBSession()
    seed_session.write_table(
        pd.DataFrame(
            [
                {
                    "holder": "Alice",
                    "premium": 100.0,
                    "zip_code": "10001",
                    "age": 30,
                    **_METADATA_DEFAULTS,
                },
                {
                    "holder": "Bob",
                    "premium": -50.0,
                    "zip_code": "94102",
                    "age": 25,
                    **_METADATA_DEFAULTS,
                },
            ]
        ),
        "stg_proposals",
    )
    # Reuse the same in-memory session for the pipeline run.
    cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
    result = run_pipeline(
        session_factory=lambda: seed_session,
        cortex=cortex,
        proposal_cls=CanonicalProposal,
        decisions=[rule_positive_premium, risk_zip, risk_age],
        adm=is_admissible,
        monoid=JointMonoid,
    )
    assert result.contracts == 1
    assert result.rejections == 1
    assert result.cortex_tokens == 0


def test_pipeline_with_cortex_extraction() -> None:
    session = DuckDBSession()
    cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
    raw = [
        "Holder: Alice. Premium: $100. ZIP 10001. Age: 30.",
        "Holder: Bob. Premium: $-50. ZIP 94102. Age: 25.",
        "Holder: Charlie. Premium: $250. ZIP 94102. Age: 20.",
        "Garbled noise without any structure.",
    ]
    result = run_pipeline(
        session_factory=lambda: session,
        cortex=cortex,
        proposal_cls=CanonicalProposal,
        decisions=[rule_positive_premium, risk_zip, risk_age],
        adm=is_admissible,
        monoid=JointMonoid,
        raw_texts=raw,
    )
    assert result.extracted == 3
    assert result.contracts == 1
    assert result.rejections == 2
    assert result.cortex_tokens > 0
    assert "premium" in result.rule_breakdown


def _seed_raw_proposals_file(duckdb_path: Path) -> None:
    session = DuckDBSession(database=str(duckdb_path))
    session.sql("CREATE SCHEMA IF NOT EXISTS raw")
    session.write_table(
        pd.DataFrame(
            [
                {
                    "holder": "Alice",
                    "premium": 100.0,
                    "zip_code": "10001",
                    "age": 30,
                    **_METADATA_DEFAULTS,
                },
                {
                    "holder": "Bob",
                    "premium": 250.0,
                    "zip_code": "10001",
                    "age": 45,
                    **_METADATA_DEFAULTS,
                },
            ]
        ),
        "raw.proposals",
    )
    session.close()


def test_pipeline_runs_dbt_build() -> None:
    """When given a dbt project dir, run_pipeline invokes dbt build."""
    with tempfile.TemporaryDirectory() as tmp:
        duckdb_path = Path(tmp) / "warehouse.duckdb"
        _seed_raw_proposals_file(duckdb_path)

        cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
        env_overrides = {
            "DBT_PROFILES_DIR": str(DBT_DIR),
            "CATINS_DUCKDB_PATH": str(duckdb_path),
        }
        prior = {k: os.environ.get(k) for k in env_overrides}
        os.environ.update(env_overrides)
        try:
            result = run_pipeline(
                session_factory=lambda: DuckDBSession(database=str(duckdb_path)),
                cortex=cortex,
                proposal_cls=CanonicalProposal,
                decisions=[rule_positive_premium, risk_zip, risk_age],
                adm=is_admissible,
                monoid=JointMonoid,
                dbt_project_dir=DBT_DIR,
            )
        finally:
            for k, v in prior.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        assert result.contracts == 2
        assert result.rejections == 0
