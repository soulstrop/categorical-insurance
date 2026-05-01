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
    con.close()
    assert rows == [
        ("individual", "Alice", 100.0, "10001", 30),
        ("individual", "Bob", 250.0, "94102", 45),
    ]
