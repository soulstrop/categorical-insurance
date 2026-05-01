"""Phase 2 pipeline harness.

# math: math.tex §VII

End-to-end orchestrator for the warehouse-native validation pipeline.
The harness is the categorical bridge between four cooperating layers:

1. **dbt** — feature engineering over the raw landing zone.
2. **Cortex** — structured extraction from unstructured proposal text.
3. **WarehouseSession** — registration of the validator UDF.
4. **SQL** — materialisation of contracts, rejections, summary view.

Phase 3 promotes each step to a Dagster SDA. The harness remains
useful as a one-shot CLI for manual runs and for tests that exercise
the full categorical pipeline without the orchestrator overhead.
"""

import json
import os
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from catins.cortex import BudgetedCortex
from catins.decision import DecisionSystem
from catins.models import CanonicalProposal, Proposal, extraction_fields
from catins.monoid import ListMonoid, Monoid
from catins.snowpark import register_validator, run_validation_pipeline
from catins.warehouse import WarehouseSession


@dataclass
class PipelineResult:
    """Counts and accounting from a single pipeline run."""

    contracts: int
    rejections: int
    extracted: int
    cortex_tokens: int
    cortex_budget: int
    rule_breakdown: dict[str, int] = field(default_factory=dict)


def run_dbt_build(project_dir: Path, profiles_dir: Path | None = None) -> None:
    """Invoke ``dbt build`` against the project directory."""
    profiles = profiles_dir or project_dir
    result = subprocess.run(
        [
            "dbt",
            "build",
            "--project-dir",
            str(project_dir),
            "--profiles-dir",
            str(profiles),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    if result.returncode != 0:
        msg = f"dbt build failed:\n{result.stdout}\n{result.stderr}"
        raise RuntimeError(msg)


def extract_proposals(
    cortex: BudgetedCortex,
    raw_texts: Iterable[str],
    fields: list[str],
) -> list[dict[str, Any]]:
    """Lift unstructured text into structured proposal dicts via Cortex.

    Drops entries that the extractor could not fully populate; returns
    only fully-structured records ready for validation.
    """
    extracted: list[dict[str, Any]] = []
    for text in raw_texts:
        result = cortex.extract_answer(text, fields)
        if any(value is None for value in result.fields.values()):
            continue
        extracted.append(dict(result.fields))
    return extracted


def run_pipeline[P: Proposal, M](
    *,
    session_factory: Callable[[], WarehouseSession],
    cortex: BudgetedCortex,
    proposal_cls: type[P],
    decisions: DecisionSystem[P, M],
    adm: Callable[[M], bool],
    monoid: type[Monoid[M]] = ListMonoid,  # type: ignore[assignment]
    raw_texts: Iterable[str] | None = None,
    dbt_project_dir: Path | None = None,
    udf_name: str = "validate_proposal",
    source_table: str = "stg_proposals",
) -> PipelineResult:
    """Run the full Phase 2 pipeline.

    The harness:

    1. Invokes ``dbt build`` if ``dbt_project_dir`` is given. Because
       file-backed DuckDB only allows a single writer, the harness
       does *not* hold a session during this step; ``session_factory``
       is called afterwards.
    2. Lifts ``raw_texts`` through Cortex extraction and writes the
       resulting structured rows to ``source_table`` if extraction is
       part of the run.
    3. Registers the validator UDF on the session.
    4. Materialises ``contracts`` / ``rejections`` / ``rejection_summary``
       via ``run_validation_pipeline``.
    """
    if dbt_project_dir is not None:
        run_dbt_build(dbt_project_dir)

    session = session_factory()

    extracted_count = 0
    if raw_texts is not None:
        # Cortex extracts the *required* domain fields (no defaults);
        # Pydantic supplies the discriminator (holder_kind defaults to
        # "individual") and the inherited metadata fields below.
        records = extract_proposals(cortex, raw_texts, fields=extraction_fields(proposal_cls))
        extracted_count = len(records)
        if records:
            # Cortex extracts only domain fields; validate through Pydantic
            # so the metadata fields (schema_version, schema_effective_date,
            # erased) get their defaults before the row lands in the
            # warehouse with the canonical column set.
            full_records = [proposal_cls(**r).model_dump() for r in records]
            session.write_table(pd.DataFrame(full_records), source_table)

    register_validator(
        session,
        name=udf_name,
        proposal_cls=proposal_cls,
        decisions=decisions,
        adm=adm,
        monoid=monoid,
    )
    counts = run_validation_pipeline(
        session, udf_name=udf_name, proposal_cls=proposal_cls, source_table=source_table
    )

    summary = session.sql("SELECT rule_name, n FROM rejection_summary")
    rule_breakdown = dict(
        zip(summary["rule_name"].tolist(), [int(n) for n in summary["n"].tolist()], strict=True)
    )

    return PipelineResult(
        contracts=counts["contracts"],
        rejections=counts["rejections"],
        extracted=extracted_count,
        cortex_tokens=cortex.total_tokens,
        cortex_budget=cortex.max_tokens,
        rule_breakdown=rule_breakdown,
    )


def _result_to_json(result: PipelineResult) -> str:
    return json.dumps(
        {
            "contracts": result.contracts,
            "rejections": result.rejections,
            "extracted": result.extracted,
            "cortex_tokens": result.cortex_tokens,
            "cortex_budget": result.cortex_budget,
            "rule_breakdown": result.rule_breakdown,
        },
        indent=2,
    )


__all__ = [
    "CanonicalProposal",
    "PipelineResult",
    "_result_to_json",
    "extract_proposals",
    "run_dbt_build",
    "run_pipeline",
]
