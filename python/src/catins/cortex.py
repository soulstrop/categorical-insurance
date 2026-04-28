"""Cortex AI mock integration for explaining rejections.

This module provides a stub for the Cortex `EXTRACT_ANSWER` and `EXPLAIN`
functions, ensuring the pipeline remains runnable locally without API tokens.
"""

from typing import Any

from catins.models import Violation


def explain_rejection(violations: list[Violation], guardrail_payload: Any) -> str:
    """Mock Cortex LLM explanation of a rejected contract.

    In production (Phase 3+), this would call Snowflake Cortex to generate a
    human-readable rejection letter based on the structured violations.

    Args:
        violations: The list of rule violations that triggered the rejection.
        guardrail_payload: The risk score or severity context attached to the decision.

    Returns:
        A mock human-readable explanation string.
    """
    if not violations:
        return "No violations found."

    reasons = "\n".join(f"- {v.message}" for v in violations)
    context_str = f"Risk Context: {guardrail_payload}"

    return (
        "Rejection Notice (Mock)\n"
        "=======================\n"
        "Your proposal was rejected for the following reasons:\n"
        f"{reasons}\n\n"
        f"{context_str}\n"
    )
