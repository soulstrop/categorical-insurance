"""dbt integration: source-contract generation and drift detection.

# math: math.tex §VII.B

Single source of truth: the Pydantic ``CanonicalProposal``. This module
generates the corresponding dbt ``schema.yml`` snippet and checks the
committed file for drift.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import BaseModel

# Mapping from Python/Pydantic types to standard SQL/Snowflake data types.
TYPE_MAPPING = {
    "str": "VARCHAR",
    "float": "DOUBLE",
    "int": "INTEGER",
    "bool": "BOOLEAN",
    "date": "DATE",
}


def _columns_for(model_cls: type[BaseModel]) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for field_name, field_info in model_cls.model_fields.items():
        annotation = field_info.annotation
        # Unwrap Literal[v1, v2, ...] to its underlying scalar type. The
        # warehouse stores a Literal column as the literal values' type
        # (typically str / VARCHAR for discriminator fields).
        if get_origin(annotation) is Literal:
            literal_values = get_args(annotation)
            annotation = type(literal_values[0])
        if annotation is str:
            type_str = "str"
        elif annotation is float:
            type_str = "float"
        elif annotation is int:
            type_str = "int"
        elif annotation is bool:
            type_str = "bool"
        elif annotation is date:
            type_str = "date"
        else:
            type_str = getattr(annotation, "__name__", str(annotation))

        sql_type = TYPE_MAPPING.get(type_str, "VARIANT")

        columns.append(
            {
                "name": field_name,
                "data_type": sql_type,
                "description": field_info.description or f"Mapped from {type_str}",
            }
        )
    return columns


def generate_dbt_source_contract(
    model_cls: type[BaseModel], source_name: str, table_name: str
) -> str:
    """Generate a dbt schema.yml snippet for a Pydantic model."""
    schema = {
        "version": 2,
        "sources": [
            {
                "name": source_name,
                "tables": [
                    {
                        "name": table_name,
                        "columns": _columns_for(model_cls),
                    }
                ],
            }
        ],
    }
    return str(yaml.dump(schema, sort_keys=False))


def expected_columns(model_cls: type[BaseModel]) -> dict[str, str]:
    """Return the expected ``{column_name: sql_type}`` mapping."""
    return {col["name"]: col["data_type"] for col in _columns_for(model_cls)}


def parse_source_columns(yaml_path: Path, source_name: str, table_name: str) -> dict[str, str]:
    """Parse a committed dbt sources YAML file and return its column map."""
    with yaml_path.open() as fh:
        data = yaml.safe_load(fh)
    for src in data.get("sources", []):
        if src.get("name") != source_name:
            continue
        for table in src.get("tables", []):
            if table.get("name") != table_name:
                continue
            return {col["name"]: col["data_type"] for col in table.get("columns", [])}
    msg = f"source '{source_name}'.'{table_name}' not found in {yaml_path}"
    raise KeyError(msg)


def check_dbt_source_drift(
    model_cls: type[BaseModel], yaml_path: Path, source_name: str, table_name: str
) -> tuple[bool, dict[str, Any]]:
    """Compare the model's expected columns to the committed dbt YAML.

    Returns ``(passed, details)``. ``details`` enumerates missing and
    extra columns as well as type mismatches, suitable for surfacing in
    a CI failure or a Dagster asset-check description.
    """
    expected = expected_columns(model_cls)
    actual = parse_source_columns(yaml_path, source_name, table_name)

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    type_mismatches = {
        name: {"expected": expected[name], "actual": actual[name]}
        for name in sorted(set(expected) & set(actual))
        if expected[name] != actual[name]
    }
    passed = not missing and not extra and not type_mismatches
    return passed, {
        "missing": missing,
        "extra": extra,
        "type_mismatches": type_mismatches,
    }


def _main() -> int:
    """CLI: ``python -m catins.dbt`` runs the drift check on the canonical model."""
    from catins.models import CanonicalProposal  # noqa: PLC0415  (avoid circular import)

    repo_root = Path(__file__).resolve().parents[2]
    yaml_path = repo_root / "dbt" / "models" / "staging" / "_sources.yml"
    passed, details = check_dbt_source_drift(
        CanonicalProposal, yaml_path, source_name="raw", table_name="proposals"
    )
    if passed:
        print(f"OK: {yaml_path} matches CanonicalProposal")
        return 0
    print(f"DRIFT: {yaml_path} disagrees with CanonicalProposal", file=sys.stderr)
    for kind, payload in details.items():
        if payload:
            print(f"  {kind}: {payload}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
