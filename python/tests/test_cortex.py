"""Tests for the Cortex client protocol, mock, and budget decorator."""

import pytest

from catins.cortex import (
    BudgetedCortex,
    BudgetExceededError,
    CortexClient,
    MockCortex,
    explain_rejection,
)
from catins.models import Violation


def test_mock_implements_protocol() -> None:
    assert isinstance(MockCortex(), CortexClient)


def test_extract_answer_recognises_fixture_text() -> None:
    client = MockCortex()
    text = "Holder: Alice. Premium: $250. The risk lives at 94102, age: 42."
    result = client.extract_answer(text, fields=["holder", "premium", "zip_code", "age"])
    assert result.fields["holder"] == "Alice"
    assert result.fields["premium"] == 250.0
    assert result.fields["zip_code"] == "94102"
    assert result.fields["age"] == 42
    assert result.tokens_used > 0


def test_extract_answer_missing_fields_become_none() -> None:
    client = MockCortex()
    result = client.extract_answer("Just some unrelated noise.", fields=["holder", "premium"])
    assert result.fields == {"holder": None, "premium": None}


def _spend_until_overrun(cortex: BudgetedCortex) -> None:
    for _ in range(50):
        cortex.complete("write a long prompt " * 10, max_tokens=512)


def test_budget_enforces_cap() -> None:
    inner = MockCortex()
    cortex = BudgetedCortex(inner, max_tokens=20)
    cortex.extract_answer("Holder: Bob.", fields=["holder"])
    assert cortex.total_tokens > 0
    with pytest.raises(BudgetExceededError):
        _spend_until_overrun(cortex)


def test_budget_exposes_total_for_asset_check() -> None:
    cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
    cortex.extract_answer("Holder: Carol. Age: 30.", fields=["holder", "age"])
    cortex.complete("Hello world.", max_tokens=64)
    assert cortex.total_tokens > 0
    assert cortex.max_tokens == 10_000


def test_explain_rejection_uses_client() -> None:
    cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
    letter = explain_rejection(
        cortex,
        [Violation(rule_name="premium", message="Negative premium")],
        guardrail_payload=0.0,
    )
    assert "premium" in letter.lower()
    assert cortex.total_tokens > 0


def test_explain_rejection_empty_returns_no_violations_message() -> None:
    cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
    msg = explain_rejection(cortex, [], guardrail_payload=0.0)
    assert msg == "No violations found."
    assert cortex.total_tokens == 0
