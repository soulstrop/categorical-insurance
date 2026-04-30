"""Dagster resources for shared infrastructure access.

# math: math.tex §VII (operational substrate)

Two resources are exposed: a ``CortexResource`` wrapping a
``BudgetedCortex`` client, and a ``WarehouseResource`` wrapping a
``WarehouseSession``. The same instance is shared across all assets
and asset checks in a single Dagster materialisation — critical for
the P3.2 token-spend check, which must read the same
``BudgetedCortex.total_tokens`` accumulator that the rejection-letter
asset wrote to.

The sandbox-time switch from ``MockCortex`` to a real Cortex client,
and from ``DuckDBSession`` to a Snowpark ``Session``, is a resource
swap on the ``Definitions`` object; the asset graph is unchanged.
"""

from dagster import ConfigurableResource, InitResourceContext
from pydantic import PrivateAttr

from catins.cortex import BudgetedCortex, Completion, Extracted, MockCortex
from catins.warehouse import DuckDBSession, WarehouseSession


class CortexResource(ConfigurableResource):  # type: ignore[type-arg]
    """Dagster resource wrapping a ``BudgetedCortex`` client.

    Implements the ``CortexClient`` Protocol structurally so it can be
    passed wherever a ``CortexClient`` is expected. ``total_tokens`` is
    exposed for the P3.2 budget asset check.

    Two thresholds are tracked:

    * ``max_tokens`` — the *hard cap*. ``BudgetedCortex`` raises
      ``BudgetExceededError`` if a call would push spend past this; the
      raise fails the asset itself, not just the check.
    * ``warn_utilisation`` — a *soft threshold* in [0, 1]. The
      ``check_cortex_budget`` asset check fails when realised
      utilisation exceeds this fraction of ``max_tokens``, even though
      the run has not (yet) overrun. The intent is early operational
      warning before the hard cap is hit.
    """

    max_tokens: int = 5_000
    warn_utilisation: float = 0.9

    _client: BudgetedCortex = PrivateAttr()

    def setup_for_execution(self, _context: InitResourceContext) -> None:
        self._client = BudgetedCortex(MockCortex(), max_tokens=self.max_tokens)

    def extract_answer(self, text: str, fields: list[str]) -> Extracted:
        return self._client.extract_answer(text, fields)

    def complete(self, prompt: str, max_tokens: int = 256) -> Completion:
        return self._client.complete(prompt, max_tokens=max_tokens)

    @property
    def total_tokens(self) -> int:
        return self._client.total_tokens

    @property
    def budget_max(self) -> int:
        return self._client.max_tokens


class WarehouseResource(ConfigurableResource):  # type: ignore[type-arg]
    """Dagster resource wrapping a ``WarehouseSession``.

    Defaults to in-memory DuckDB; the sandbox-time Snowpark-backed
    implementation lives behind the same ``WarehouseSession`` Protocol
    and is selected by configuring this resource at the
    ``Definitions`` level.
    """

    database: str = ":memory:"

    _session: DuckDBSession = PrivateAttr()

    def setup_for_execution(self, _context: InitResourceContext) -> None:
        self._session = DuckDBSession(database=self.database)

    @property
    def session(self) -> WarehouseSession:
        return self._session

    def teardown_after_execution(self, _context: InitResourceContext) -> None:
        # Best-effort cleanup; idempotent.
        self._session.close()
