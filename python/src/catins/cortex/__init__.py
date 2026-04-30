"""Cortex AI integration package.

Public surface:

* ``CortexClient`` — Protocol for the slice of Cortex the pipeline uses.
* ``MockCortex`` — Deterministic in-process stub.
* ``BudgetedCortex`` — Per-run token cap decorator.
* ``BudgetExceededError`` — Raised when the cap would be breached.
* ``explain_rejection`` — Generates a draft rejection letter via a client.

The Phase 2-sandbox real implementation lives in ``catins.cortex.real``
(not yet created) and wraps ``snowflake.cortex``.
"""

from catins.cortex.budget import BudgetedCortex, BudgetExceededError
from catins.cortex.client import Completion, CortexClient, Extracted
from catins.cortex.explain import explain_rejection
from catins.cortex.extract import MockCortex

__all__ = [
    "BudgetExceededError",
    "BudgetedCortex",
    "Completion",
    "CortexClient",
    "Extracted",
    "MockCortex",
    "explain_rejection",
]
