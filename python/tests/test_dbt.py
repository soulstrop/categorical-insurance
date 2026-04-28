"""Tests for dbt integration.

This module ensures Pydantic models can be correctly mapped to dbt source
contracts to prevent schema drift between Python and SQL.
"""

import yaml

from catins.dbt import generate_dbt_source_contract
from catins.models import Proposal


class MockDbtProposal(Proposal):
    holder: str
    premium: float
    age: int
    is_active: bool


def test_generate_dbt_source_contract() -> None:
    """A Pydantic Proposal generates a valid dbt schema.yml representation."""
    yaml_output = generate_dbt_source_contract(
        MockDbtProposal, source_name="raw_features", table_name="proposals"
    )

    # Parse back the YAML to verify structure
    parsed = yaml.safe_load(yaml_output)

    assert "sources" in parsed
    source = parsed["sources"][0]
    assert source["name"] == "raw_features"

    table = source["tables"][0]
    assert table["name"] == "proposals"

    columns = {col["name"]: col["data_type"] for col in table["columns"]}

    assert columns["holder"] == "VARCHAR"
    assert columns["premium"] == "DOUBLE"
    assert columns["age"] == "INTEGER"
    assert columns["is_active"] == "BOOLEAN"
