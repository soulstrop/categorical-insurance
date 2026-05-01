"""Core data models.

This module provides the Pydantic models for Proposals, Contracts, and
Violations, enforcing the categorical abstraction barriers.
"""

from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from catins.privacy import PII

# v1 schema adoption date: the date ADRs 006/007/008 landed and the
# evolution-tracking machinery began. Default for ``schema_effective_date``
# on rows that do not specify one (which is every row authored before the
# multi-version dispatch in P2R.4 lands). P2R.5's compat-check enforces
# that subsequent versions carry a non-default date paired with a
# non-default ``schema_version``.
SCHEMA_V1_EFFECTIVE_DATE = date(2026, 4, 30)


class Violation(BaseModel):
    """A governance rule violation.

    # math: math.tex Definition 6
    """

    rule_name: str
    message: str
    context: dict[str, Any] = {}


class Proposal(BaseModel):
    """A base class for insurance proposals.

    Carries the evolution and erasure markers (ADRs 007 and 008) so
    every concrete proposal inherits them; the fields are operational
    metadata, not categorical structure, and live on the base class
    rather than threading through every concrete model.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    schema_effective_date: date = SCHEMA_V1_EFFECTIVE_DATE
    erased: bool = False


class CanonicalProposal(Proposal):
    """The canonical Phase 2/3 proposal shape.

    The fields here are the single source of truth for the dbt source
    contract (``dbt/models/staging/_sources.yml``) and for every
    warehouse-side reference to a proposal column. Drift between this
    model and the dbt YAML is enforced as a CI failure (see
    ``catins.dbt.check_dbt_source_drift``).
    """

    holder: Annotated[str, PII("direct", regimes={"GLBA"})]
    premium: float
    zip_code: Annotated[str, PII("quasi", regimes={"GLBA"})]
    age: Annotated[int, PII("quasi", regimes={"GLBA"})]


def proposal_domain_fields(proposal_cls: type["Proposal"]) -> list[str]:
    """Field names defined on a concrete proposal subclass (not inherited).

    The validator UDF and Cortex extraction operate on the *domain*
    fields of a concrete proposal; the metadata fields inherited from
    ``Proposal`` (``schema_version``, ``schema_effective_date``,
    ``erased``) are operational machinery that the warehouse stores but
    those callers ignore. Pydantic supplies the metadata defaults at
    row-construction time, so omitting the fields here does not break
    validation.
    """
    inherited = set(Proposal.model_fields.keys())
    return [f for f in proposal_cls.model_fields if f not in inherited]


class Contract[M](BaseModel):
    """A constructed insurance contract.

    # math: math.tex Definition 8

    The constructor is conventionally private. Use `_from_validated`
    within the framework to construct contracts.
    """

    model_config = ConfigDict(frozen=True)

    proposal: Proposal
    payload: M
    schema_version: int = 1
    schema_effective_date: date = SCHEMA_V1_EFFECTIVE_DATE
    erased: bool = False

    @classmethod
    def _from_validated(cls, proposal: Proposal, payload: M) -> "Contract[M]":
        """Internal constructor for validated contracts."""
        return cls(proposal=proposal, payload=payload)
