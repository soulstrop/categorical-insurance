"""Persistence and serialization.

This module provides utilities to persist validation outputs and contracts
to Parquet using PyArrow, as required by Phase 1.
"""

from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from catins.models import Contract


def serialize_contracts_to_parquet[M](contracts: list[Contract[M]], filepath: str) -> None:
    """Serialize a list of contracts to a Parquet file.

    This flattens the proposal and payload into a single record per contract.

    By convention established in Phase 1, the monoid payload `M` must either
    be a primitive, a Pydantic model, or a list thereof. This ensures trivial
    persistence into Snowflake `VARIANT` columns or Parquet files.
    """
    if not contracts:
        return

    records = []
    for c in contracts:
        # Extract the proposal fields
        record: dict[str, Any] = c.proposal.model_dump()

        # Determine payload type and serialize
        payload = c.payload
        if isinstance(payload, list):
            # E.g. list[Violation] -> list of dicts
            record["payload"] = [v.model_dump() if hasattr(v, "model_dump") else v for v in payload]
        elif hasattr(payload, "model_dump"):
            record["payload"] = payload.model_dump()
        else:
            record["payload"] = payload

        records.append(record)

    table = pa.Table.from_pylist(records)
    pq.write_table(table, filepath)  # type: ignore[no-untyped-call]
