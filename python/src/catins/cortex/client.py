"""Cortex client protocol.

# math: math.tex §VII.D (Boundary services with token budgets)

Defines the ``CortexClient`` Protocol — the seam between the pipeline
and Snowflake's Cortex AI services. The Phase 2 implementation is a
deterministic mock; the sandbox-time implementation wraps
``snowflake.cortex.complete`` and ``snowflake.cortex.extract_answer``
behind the same Protocol.

Every call returns its result alongside a ``tokens_used`` count so that
budget enforcement and asset checks can reason about spend without
peeking inside the client.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Extracted:
    """Structured output of an extract-answer call."""

    fields: dict[str, Any]
    tokens_used: int


@dataclass(frozen=True)
class Completion:
    """Output of a generic completion call."""

    text: str
    tokens_used: int


@runtime_checkable
class CortexClient(Protocol):
    """The minimal Cortex surface the pipeline depends on."""

    def extract_answer(self, text: str, fields: list[str]) -> Extracted:
        """Extract a structured record from free-form text."""
        ...

    def complete(self, prompt: str, max_tokens: int = 256) -> Completion:
        """Run a completion and return the generated text."""
        ...
