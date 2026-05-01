"""Vectorised UDF adaptation for warehouse execution.

# math: math.tex §VII.B (Vectorised UDF lifting of validate)

Provides three interrelated capabilities:

* ``vectorize_validator`` — the row-batch Pandas-callable factory used
  by Phase 1 tests and by the orchestration UDF.
* ``register_validator`` — registers the validator as a struct-returning
  UDF on a ``WarehouseSession``, where it can be invoked from SQL.
* ``run_validation_pipeline`` — end-to-end SQL orchestration that reads
  the staging table, applies the registered UDF, and writes
  ``contracts`` / ``rejections`` tables plus a ``rejection_summary`` view.
"""

import json
from collections.abc import Callable
from typing import Any, Literal, TypeVar, get_args, get_origin

import pandas as pd
import pyarrow as pa
from pydantic import TypeAdapter

from catins.decision import DecisionSystem, evaluate
from catins.models import Proposal, proposal_domain_fields
from catins.monoid import ListMonoid, Monoid
from catins.warehouse import WarehouseSession

M = TypeVar("M")
P = TypeVar("P", bound=Proposal)

# A row-level validation result, JSON-serialised for warehouse portability.
DECISION_STRUCT = pa.struct(
    [
        pa.field("admitted", pa.bool_()),
        pa.field("payload_json", pa.string()),
    ]
)


def serialize_payload(payload: Any) -> Any:
    """Serialise a monoid payload into JSON-compatible primitives."""
    if isinstance(payload, tuple):
        return tuple(serialize_payload(x) for x in payload)
    if isinstance(payload, list):
        return [serialize_payload(v) for v in payload]
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload


def vectorize_validator[P: Proposal, M](
    proposal_cls: type[P],
    decisions: DecisionSystem[P, M],
    adm: Callable[[M], bool],
    monoid: type[Monoid[M]] = ListMonoid,  # type: ignore
) -> Callable[..., pd.Series]:
    """Lift a decision system into a Pandas-vectorised UDF.

    The returned callable accepts the proposal model's fields as
    positional Pandas Series arguments and returns a Series of
    ``(admitted: bool, payload: serialised_M)`` tuples.
    """
    adapter = TypeAdapter(list[proposal_cls])  # type: ignore[valid-type]

    def udf(*args: pd.Series) -> pd.Series:
        if not args:
            return pd.Series([])
        fields = proposal_domain_fields(proposal_cls)
        df = pd.DataFrame(dict(zip(fields, args, strict=True)))
        records = df.to_dict(orient="records")
        proposals = adapter.validate_python(records)
        results = []
        for p in proposals:
            m = evaluate(decisions, p, monoid)
            results.append((adm(m), serialize_payload(m)))
        return pd.Series(results)

    return udf


def _arrow_udf_factory[P: Proposal, M](
    proposal_cls: type[P],
    decisions: DecisionSystem[P, M],
    adm: Callable[[M], bool],
    monoid: type[Monoid[M]],
) -> Callable[..., pa.Array]:
    """Lift the row-batch validator into an Arrow-typed UDF for DuckDB.

    DuckDB inspects the function's signature to determine arity; a
    variadic ``*cols`` is read as a single-parameter UDF. We therefore
    synthesise a fixed-arity wrapper whose parameter names match the
    proposal model's fields.
    """
    adapter = TypeAdapter(list[proposal_cls])  # type: ignore[valid-type]
    fields = proposal_domain_fields(proposal_cls)

    def _impl(*cols: pa.ChunkedArray) -> pa.Array:
        df = pd.DataFrame({fields[i]: cols[i].to_pandas() for i in range(len(cols))})
        records = df.to_dict(orient="records")
        proposals = adapter.validate_python(records)
        admitted: list[bool] = []
        payloads: list[str] = []
        for p in proposals:
            m = evaluate(decisions, p, monoid)
            admitted.append(adm(m))
            payloads.append(json.dumps(serialize_payload(m), default=str))
        return pa.StructArray.from_arrays(
            [pa.array(admitted, type=pa.bool_()), pa.array(payloads, type=pa.string())],
            fields=DECISION_STRUCT,
        )

    arg_list = ", ".join(fields)
    src = f"def udf({arg_list}):\n    return _impl({arg_list})\n"
    ns: dict[str, Any] = {"_impl": _impl}
    exec(src, ns)  # noqa: S102 (controlled synthesis from model field names)
    return ns["udf"]  # type: ignore[no-any-return]


# Mapping from Python annotations to DuckDB SQL type strings used at
# UDF registration. Mirrors ``catins.dbt.TYPE_MAPPING`` but emits
# DuckDB-native names where they differ.
_DUCKDB_TYPE_MAPPING = {
    str: "VARCHAR",
    float: "DOUBLE",
    int: "BIGINT",
    bool: "BOOLEAN",
}


def _duckdb_param_types(proposal_cls: type[Proposal]) -> list[str]:
    out: list[str] = []
    concrete = proposal_domain_fields(proposal_cls)
    for field_name in concrete:
        annotation = proposal_cls.model_fields[field_name].annotation
        # Unwrap Literal[v1, v2, ...] to its underlying scalar type so
        # the discriminator's Python `Literal[...]` lands as VARCHAR /
        # BIGINT depending on the literal's element type.
        if get_origin(annotation) is Literal:
            literal_values = get_args(annotation)
            annotation = type(literal_values[0])
        sql_type = _DUCKDB_TYPE_MAPPING.get(annotation)  # type: ignore[arg-type]
        if sql_type is None:
            msg = f"unsupported field type for {field_name}: {annotation}"
            raise TypeError(msg)
        out.append(sql_type)
    return out


def register_validator[P: Proposal, M](
    session: WarehouseSession,
    name: str,
    proposal_cls: type[P],
    decisions: DecisionSystem[P, M],
    adm: Callable[[M], bool],
    monoid: type[Monoid[M]] = ListMonoid,  # type: ignore
) -> None:
    """Register the validator as a struct-returning UDF on ``session``."""
    udf = _arrow_udf_factory(proposal_cls, decisions, adm, monoid)
    session.register_udf(
        name,
        udf,
        param_types=_duckdb_param_types(proposal_cls),
        return_type="STRUCT(admitted BOOLEAN, payload_json VARCHAR)",
    )


def run_validation_pipeline(
    session: WarehouseSession,
    udf_name: str,
    proposal_cls: type[Proposal],
    source_table: str = "stg_proposals",
) -> dict[str, int]:
    """Materialise contracts / rejections / rejection_summary via SQL.

    Returns row counts suitable for logging and asset-check metadata.
    """
    # All warehouse columns flow through unchanged; only the *concrete*
    # domain fields are passed into the validator UDF (the inherited
    # metadata fields are irrelevant to validation but still need to
    # land in contracts/rejections).
    all_fields = list(proposal_cls.model_fields.keys())
    udf_fields = proposal_domain_fields(proposal_cls)
    field_list = ", ".join(all_fields)
    field_args = ", ".join(udf_fields)

    session.sql(
        f"""
        CREATE OR REPLACE TABLE __validated AS
        SELECT
            {field_list},
            ({udf_name}({field_args})).admitted AS admitted,
            ({udf_name}({field_args})).payload_json AS payload_json
        FROM {source_table}
        """
    )
    session.sql(
        f"""
        CREATE OR REPLACE TABLE contracts AS
        SELECT {field_list}, payload_json FROM __validated WHERE admitted
        """
    )
    session.sql(
        f"""
        CREATE OR REPLACE TABLE rejections AS
        SELECT {field_list}, payload_json FROM __validated WHERE NOT admitted
        """
    )
    # rejection_summary: count rejections by rule_name. The payload is
    # JSON; for the canonical (list[Violation], float) joint payload it
    # is a 2-element array whose first entry is a list of violations.
    session.sql(
        """
        CREATE OR REPLACE VIEW rejection_summary AS
        SELECT
            json_extract_string(violation.value, '$.rule_name') AS rule_name,
            COUNT(*) AS n
        FROM rejections r,
             json_each(json_extract(r.payload_json, '$[0]')) AS violation
        GROUP BY 1
        ORDER BY n DESC
        """
    )

    counts_df = session.sql(
        "SELECT "
        "(SELECT COUNT(*) FROM contracts)   AS contracts, "
        "(SELECT COUNT(*) FROM rejections)  AS rejections "
    )
    return {
        "contracts": int(counts_df["contracts"].iloc[0]),
        "rejections": int(counts_df["rejections"].iloc[0]),
    }
