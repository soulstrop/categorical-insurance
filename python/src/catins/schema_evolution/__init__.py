"""Schema evolution package: version registry and dispatch (ADR 008).

Production callers consume :data:`DEFAULT_REGISTRY`, which is
populated at import time with every schema version this codebase
knows about (currently just v1 = ``CanonicalProposal``). Tests
construct their own ``SchemaRegistry`` for isolation.
"""

from catins.models import SCHEMA_V1_EFFECTIVE_DATE, CanonicalProposal
from catins.schema_evolution.dispatch import QuarantineRow, parse_proposal
from catins.schema_evolution.versions import SchemaRegistry, SchemaVersion

DEFAULT_REGISTRY = SchemaRegistry()
DEFAULT_REGISTRY.register(
    SchemaVersion(version=1, effective_date=SCHEMA_V1_EFFECTIVE_DATE),
    CanonicalProposal,
)


__all__ = [
    "DEFAULT_REGISTRY",
    "QuarantineRow",
    "SchemaRegistry",
    "SchemaVersion",
    "parse_proposal",
]
