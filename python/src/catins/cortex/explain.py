"""Cortex-backed rejection explanation.

Generates a human-readable rejection letter from a structured
``Violation`` list and the joint guardrail payload, via a
``CortexClient``. The Phase 2 mock client fills in a deterministic
template; the sandbox-time real client calls Snowflake Cortex.
"""

from typing import Any

from catins.cortex.client import CortexClient
from catins.models import Violation


def explain_rejection(
    client: CortexClient,
    violations: list[Violation],
    guardrail_payload: Any,
    *,
    max_tokens: int = 256,
) -> str:
    """Produce a draft rejection letter."""
    if not violations:
        return "No violations found."

    reasons = "; ".join(f"{v.rule_name}: {v.message}" for v in violations)
    prompt = (
        f"Draft a polite rejection letter. Reasons: {reasons}. Risk context: {guardrail_payload}."
    )
    completion = client.complete(prompt, max_tokens=max_tokens)
    return completion.text
