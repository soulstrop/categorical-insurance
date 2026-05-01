"""Schema version registry per ADR 008.

# math: math.tex §VII.B (Schema as a versioned object in the pipeline category)

A ``SchemaVersion`` is the dual identifier (integer + effective date)
that tags every row from P2R.1 onward. The registry maps integer
version → ``(SchemaVersion, model_cls)`` so the multi-version
dispatcher (``catins.schema_evolution.dispatch.parse_proposal``) can
route an inbound row to the right Pydantic model.

Production callers use :data:`DEFAULT_REGISTRY` (populated in
``catins.schema_evolution.__init__``); tests construct their own
``SchemaRegistry`` to exercise dispatch in isolation.
"""

from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel


@dataclass(frozen=True)
class SchemaVersion:
    """Dual identifier (per ADR 008): integer version + adoption date.

    The integer drives discriminator dispatch; the date is the
    operational record of when the version became authoritative
    (referenced by the runbook and the audit trail).
    """

    version: int
    effective_date: date


class SchemaRegistry:
    """Maps integer schema versions to their ``(SchemaVersion, model)`` pair."""

    def __init__(self) -> None:
        self._versions: dict[int, tuple[SchemaVersion, type[BaseModel]]] = {}

    def register(self, schema_version: SchemaVersion, model_cls: type[BaseModel]) -> None:
        """Register a schema version with its corresponding model class."""
        self._versions[schema_version.version] = (schema_version, model_cls)

    def get(self, version: int) -> tuple[SchemaVersion, type[BaseModel]] | None:
        """Return ``(SchemaVersion, model_cls)`` or ``None`` if unknown."""
        return self._versions.get(version)

    def current(self) -> SchemaVersion:
        """The highest-numbered registered version."""
        if not self._versions:
            msg = "registry is empty"
            raise LookupError(msg)
        return max(self._versions.values(), key=lambda entry: entry[0].version)[0]

    def known_versions(self) -> list[int]:
        """Sorted list of registered version numbers."""
        return sorted(self._versions.keys())
