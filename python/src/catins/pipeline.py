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
from catins.privacy.erasure import init_audit_table
from catins.privacy.tokenisation import TokenisationClient, tokenise_model
from catins.schema_evolution import (
    DEFAULT_REGISTRY,
    QuarantineRow,
    SchemaRegistry,
    init_quarantine_table,
    parse_proposal,
    write_quarantine_rows,
)
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
    quarantined: int = 0
    rule_breakdown: dict[str, int] = field(default_factory=dict)


_PRE_VALIDATION_EXCLUDES = ("marts", "raw", "audit")
_POST_VALIDATION_SELECTS = ("marts", "raw", "audit")


def run_dbt_build(project_dir: Path, profiles_dir: Path | None = None) -> None:
    """Invoke ``dbt build`` against the staging tier only.

    All non-staging tiers are excluded because their source tables are
    populated at later lifecycle points:

    * ``marts`` — depends on ``contracts`` produced by the validation
      pipeline.
    * ``audit`` — depends on ``_audit_erasures`` produced by
      ``catins.privacy.erasure``.
    * ``raw`` (the dbt model tier, not the source schema) — depends
      on ``raw_quarantine`` populated by the ingest dispatcher when
      ``parse_proposal`` rejects rows.

    The end-to-end harness invokes :func:`run_dbt_build_post` after
    validation to close the loop.
    """
    profiles = profiles_dir or project_dir
    cmd = [
        "dbt",
        "build",
        "--project-dir",
        str(project_dir),
        "--profiles-dir",
        str(profiles),
        "--exclude",
        *_PRE_VALIDATION_EXCLUDES,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy(), check=False)
    if result.returncode != 0:
        msg = f"dbt build failed:\n{result.stdout}\n{result.stderr}"
        raise RuntimeError(msg)


def run_dbt_build_post(project_dir: Path, profiles_dir: Path | None = None) -> None:
    """Build marts / raw / audit tiers after validation has run.

    Closes the loop opened by :func:`run_dbt_build`: ``contracts``,
    ``raw_quarantine``, and ``_audit_erasures`` exist in the warehouse
    by this point (the harness initialises the latter two as empty if
    nothing wrote to them, so dbt always has a source to read).
    """
    profiles = profiles_dir or project_dir
    cmd = [
        "dbt",
        "build",
        "--project-dir",
        str(project_dir),
        "--profiles-dir",
        str(profiles),
        "--select",
        *_POST_VALIDATION_SELECTS,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy(), check=False)
    if result.returncode != 0:
        msg = f"dbt build (post-validation) failed:\n{result.stdout}\n{result.stderr}"
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


def _dispatch_records[P: Proposal](
    records: list[dict[str, Any]],
    proposal_cls: type[P],
    registry: SchemaRegistry,
) -> tuple[list[P], list[QuarantineRow]]:
    """Route extracted records through ``parse_proposal``.

    Records without a ``schema_version`` field default to v1 (the only
    version the registry knows about today) — Cortex extracts only the
    domain fields, so the dispatcher would always quarantine them
    otherwise. The default is harmless for known-good upstreams; for
    untrusted external feeds, callers should pre-stamp ``schema_version``
    on every record.
    """
    valid: list[P] = []
    quarantined: list[QuarantineRow] = []
    for record in records:
        record_with_version = {"schema_version": 1, **record}
        result = parse_proposal(record_with_version, registry)
        if isinstance(result, QuarantineRow):
            quarantined.append(result)
        else:
            # The registry maps v1 → ``proposal_cls``; ``isinstance``
            # confirms the cast statically and at runtime.
            assert isinstance(result, proposal_cls)
            valid.append(result)
    return valid, quarantined


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
    tokenisation_client: TokenisationClient | None = None,
    registry: SchemaRegistry | None = None,
) -> PipelineResult:
    """Run the full Phase 2 / Phase-2-revisit pipeline.

    The harness:

    1. Invokes ``dbt build`` (staging tier only) if ``dbt_project_dir``
       is given. Because file-backed DuckDB only allows a single
       writer, the harness does *not* hold a session during this step;
       ``session_factory`` is called afterwards.
    2. Lifts ``raw_texts`` through Cortex extraction.
    3. Routes each extracted record through ``parse_proposal`` against
       ``registry`` (defaulting to ``DEFAULT_REGISTRY``):
       successes are kept, ``QuarantineRow``\\ s are written to
       ``raw_quarantine``.
    4. Tokenises direct-PII string fields on the survivors via
       ``tokenisation_client`` (when provided) and writes them to
       ``source_table``.
    5. Registers the validator UDF on the session.
    6. Materialises ``contracts`` / ``rejections`` / ``rejection_summary``
       via ``run_validation_pipeline``.
    7. If ``dbt_project_dir`` is given, closes the session and runs a
       second dbt build for ``marts`` / ``raw`` / ``audit`` so the
       consumer-facing views (and the audit view) reflect the run's
       output. ``raw_quarantine`` and ``_audit_erasures`` are
       initialised empty before the build so dbt always has a source
       to read, even if nothing was quarantined or erased.
    """
    if dbt_project_dir is not None:
        run_dbt_build(dbt_project_dir)

    active_registry = registry if registry is not None else DEFAULT_REGISTRY
    session = session_factory()

    extracted_count = 0
    quarantined_count = 0
    if raw_texts is not None:
        # Cortex extracts the *required* domain fields (no defaults);
        # _dispatch_records stamps schema_version=1 and routes through
        # parse_proposal so failures (e.g., unknown version after future
        # registry pruning, validation regressions) land in quarantine
        # rather than crashing the run.
        records = extract_proposals(cortex, raw_texts, fields=extraction_fields(proposal_cls))
        extracted_count = len(records)

        valid, quarantined = _dispatch_records(records, proposal_cls, active_registry)
        quarantined_count = len(quarantined)

        if quarantined:
            init_quarantine_table(session)
            write_quarantine_rows(session, quarantined)

        if valid:
            if tokenisation_client is not None:
                # Direct-PII string fields → tokens. Quasi-PII (zip,
                # age) is left in plaintext; masking handles those at
                # read time per ADR 006 §3.
                valid = [tokenise_model(m, tokenisation_client) for m in valid]
            full_records = [m.model_dump() for m in valid]
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

    if dbt_project_dir is not None:
        # Make sure the audit + quarantine tables exist before the
        # second dbt build runs — both are idempotent CREATE-IF-NOT-
        # EXISTS, so re-init is safe regardless of whether they were
        # populated above.
        init_quarantine_table(session)
        init_audit_table(session)
        # File-backed DuckDB is single-writer; release before dbt opens.
        if hasattr(session, "close"):
            session.close()
        run_dbt_build_post(dbt_project_dir)

    return PipelineResult(
        contracts=counts["contracts"],
        rejections=counts["rejections"],
        extracted=extracted_count,
        cortex_tokens=cortex.total_tokens,
        cortex_budget=cortex.max_tokens,
        quarantined=quarantined_count,
        rule_breakdown=rule_breakdown,
    )


def _result_to_json(result: PipelineResult) -> str:
    return json.dumps(
        {
            "contracts": result.contracts,
            "rejections": result.rejections,
            "extracted": result.extracted,
            "quarantined": result.quarantined,
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
    "run_dbt_build_post",
    "run_pipeline",
]
