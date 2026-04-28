"""dbt integration and contract generation.

This module provides generators that map Pydantic domain models
into dbt source contracts (schema.yml) to ensure alignment between
the Python runtime and the SQL warehouse.
"""

import yaml
from pydantic import BaseModel

# Mapping from Python/Pydantic types to standard SQL/Snowflake data types.
TYPE_MAPPING = {
    "str": "VARCHAR",
    "float": "DOUBLE",
    "int": "INTEGER",
    "bool": "BOOLEAN",
}


def generate_dbt_source_contract(
    model_cls: type[BaseModel], source_name: str, table_name: str
) -> str:
    """Generate a dbt schema.yml snippet for a Pydantic model.

    This ensures that the `Proposal` shape expected by the Python validation
    layer matches the data types produced by the dbt feature engineering pipeline.

    Args:
        model_cls: The Pydantic model class to inspect.
        source_name: The name of the dbt source.
        table_name: The name of the table within the source.

    Returns:
        A YAML string representing the dbt source configuration.
    """
    columns = []

    for field_name, field_info in model_cls.model_fields.items():
        # Get the underlying Python type as a string
        # For simple fields, field_info.annotation is the type (e.g. <class 'str'>)
        annotation = field_info.annotation

        # Naive type to string extraction for standard types
        type_str = ""
        if annotation is str:
            type_str = "str"
        elif annotation is float:
            type_str = "float"
        elif annotation is int:
            type_str = "int"
        elif annotation is bool:
            type_str = "bool"
        else:
            # Fallback for complex/unknown types
            type_str = getattr(annotation, "__name__", str(annotation))

        sql_type = TYPE_MAPPING.get(type_str, "VARIANT")

        col_def = {
            "name": field_name,
            "data_type": sql_type,
            "description": field_info.description or f"Mapped from {type_str}",
        }
        columns.append(col_def)

    schema = {
        "version": 2,
        "sources": [
            {
                "name": source_name,
                "tables": [
                    {
                        "name": table_name,
                        "columns": columns,
                    }
                ],
            }
        ],
    }

    return str(yaml.dump(schema, sort_keys=False))
