"""End-to-end dbt project smoke test against DuckDB.

Builds the staging models from a seeded raw table; asserts the
resulting view shape matches the Pydantic ``Proposal``-shaped contract.
"""

import os
import subprocess
from pathlib import Path

import duckdb
import pandas as pd
import pytest

DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"


def _seed_raw_proposals(duckdb_path: Path) -> None:
    con = duckdb.connect(str(duckdb_path))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute(
        """
        CREATE OR REPLACE TABLE raw.proposals (
            holder_kind VARCHAR,
            holder_name VARCHAR,
            premium DOUBLE,
            zip_code VARCHAR,
            age INTEGER,
            schema_version INTEGER,
            schema_effective_date DATE,
            erased BOOLEAN
        )
        """
    )
    schema_v1_date = pd.Timestamp("2026-04-30")
    base = {
        "holder_kind": "individual",
        "schema_version": 1,
        "schema_effective_date": schema_v1_date,
        "erased": False,
    }
    con.register(
        "__seed_buf",
        pd.DataFrame(
            [
                {"holder_name": "Alice", "premium": 100.0, "zip_code": "10001", "age": 30, **base},
                {"holder_name": "Bob", "premium": 250.0, "zip_code": "94102", "age": 45, **base},
            ]
        ),
    )
    con.execute(
        "INSERT INTO raw.proposals "
        "SELECT holder_kind, holder_name, premium, zip_code, age, "
        "       schema_version, schema_effective_date, erased "
        "FROM __seed_buf"
    )
    # Seed `contracts` (normally produced by run_validation_pipeline) so
    # the marts tier's v_contracts view has a source to read; include
    # one tombstoned row to exercise the erasure_filter macro and the
    # view_filters_erased generic test.
    con.execute(
        """
        CREATE OR REPLACE TABLE main.contracts (
            holder_kind VARCHAR,
            holder_name VARCHAR,
            premium DOUBLE,
            zip_code VARCHAR,
            age INTEGER,
            schema_version INTEGER,
            schema_effective_date DATE,
            erased BOOLEAN,
            payload_json VARCHAR
        )
        """
    )
    con.register(
        "__contracts_buf",
        pd.DataFrame(
            [
                {
                    "holder_name": "Alice",
                    "premium": 100.0,
                    "zip_code": "10001",
                    "age": 30,
                    "payload_json": "[[],0.0]",
                    **base,
                },
                {
                    "holder_name": "Carol",
                    "premium": 200.0,
                    "zip_code": "10001",
                    "age": 60,
                    "payload_json": "[[],0.0]",
                    "holder_kind": "individual",
                    "schema_version": 1,
                    "schema_effective_date": schema_v1_date,
                    "erased": True,  # tombstoned: should be filtered out of v_contracts
                },
            ]
        ),
    )
    con.execute(
        "INSERT INTO main.contracts "
        "SELECT holder_kind, holder_name, premium, zip_code, age, "
        "       schema_version, schema_effective_date, erased, payload_json "
        "FROM __contracts_buf"
    )
    con.close()


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_dbt_build_against_duckdb(tmp_path: Path) -> None:
    duckdb_path = tmp_path / "catins.duckdb"
    _seed_raw_proposals(duckdb_path)

    env = {
        **os.environ,
        "DBT_PROFILES_DIR": str(DBT_DIR),
        "CATINS_DUCKDB_PATH": str(duckdb_path),
    }
    result = subprocess.run(
        ["dbt", "build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"dbt build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    con = duckdb.connect(str(duckdb_path))
    rows = con.execute(
        "SELECT holder_kind, holder_name, premium, zip_code, age "
        "FROM main.stg_proposals ORDER BY holder_name"
    ).fetchall()
    # v_proposals: a marts view filtered by the erasure_filter macro.
    # All seeded raw.proposals rows have erased=false, so v_proposals
    # mirrors stg_proposals.
    v_proposals_rows = con.execute(
        "SELECT holder_kind, holder_name, premium, zip_code, age "
        "FROM main.v_proposals ORDER BY holder_name"
    ).fetchall()
    # v_contracts: filters out the tombstoned Carol row (erased=true);
    # the dbt generic test_view_filters_erased asserts the same.
    v_contracts_rows = con.execute(
        "SELECT holder_name FROM main.v_contracts ORDER BY holder_name"
    ).fetchall()
    con.close()
    assert rows == [
        ("individual", "Alice", 100.0, "10001", 30),
        ("individual", "Bob", 250.0, "94102", 45),
    ]
    assert v_proposals_rows == rows  # all non-tombstoned rows visible
    assert v_contracts_rows == [("Alice",)]  # Carol filtered out
