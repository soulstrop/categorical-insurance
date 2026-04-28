"""Tests for Parquet persistence and data integration.

Tests DuckDB integration as a local feature engine, mapping rows to
Pydantic Proposals, validating them, and exporting to Parquet.
"""

import os
import tempfile

import duckdb

from catins.models import Contract, Proposal, Violation
from catins.persistence import serialize_contracts_to_parquet
from catins.validation import Governed, validate


class MockProposal(Proposal):
    """A test proposal schema matching our mocked database."""

    holder: str
    premium: float


def test_duckdb_to_parquet_pipeline() -> None:
    """Extract features via DuckDB, validate, and serialize to Parquet."""
    # 1. Setup DuckDB memory database and mock some feature data
    con = duckdb.connect(database=":memory:")
    con.execute("CREATE TABLE features (holder VARCHAR, premium DOUBLE)")
    con.execute("INSERT INTO features VALUES ('Alice', 100.0), ('Bob', -50.0), ('Charlie', 250.0)")

    # 2. Extract into Pydantic models (Local feature engineering)
    rows = con.execute("SELECT holder, premium FROM features").fetchall()
    proposals = [MockProposal(holder=row[0], premium=row[1]) for row in rows]

    assert len(proposals) == 3

    # 3. Simple governance: premium must be positive
    def rule_positive_premium(p: MockProposal) -> list:
        if p.premium <= 0:
            return [
                Violation(
                    rule_name="premium_check",
                    message="Negative premium",
                    context={"p": p.premium},
                )
            ]
        return []

    # 4. Validate all
    contracts: list[Contract[list]] = []
    rejections = []

    for p in proposals:
        gov = Governed(proposal=p, decisions=[rule_positive_premium])
        res = validate(gov, adm=lambda m: len(m) == 0)

        if isinstance(res, Contract):
            contracts.append(res)
        else:
            rejections.append(res)

    assert len(contracts) == 2
    assert len(rejections) == 1

    # 5. Export to Parquet
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "contracts.parquet")
        serialize_contracts_to_parquet(contracts, out_path)

        assert os.path.exists(out_path)

        # Read it back using DuckDB to verify structure
        rows = con.execute(f"SELECT holder, payload FROM read_parquet('{out_path}')").fetchall()
        assert len(rows) == 2
        assert rows[0][0] in ("Alice", "Charlie")
