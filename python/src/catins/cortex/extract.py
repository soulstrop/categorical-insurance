"""Mock extract-answer implementation.

A deterministic stub that recognises a small fixture vocabulary so the
Phase 2 pipeline can run end-to-end without a Cortex account. Anything
the stub does not recognise is reported as ``None`` for that field.
"""

import re

from catins.cortex.client import Completion, CortexClient, Extracted


class MockCortex:
    """Deterministic CortexClient stub for tests and CI.

    Each call accumulates a fake but realistic token count; the
    ``BudgetedCortex`` decorator (in ``cortex.budget``) reads it.
    """

    # Compiled patterns for the small vocabulary the harness needs.
    _PATTERNS = {
        "holder": re.compile(r"holder\s*(?:is|:)\s*([A-Za-z][A-Za-z\- ]*?)(?:[.,;]|$)", re.I),
        "premium": re.compile(r"premium\s*(?:is|:)\s*\$?(-?\d+(?:\.\d+)?)", re.I),
        "zip_code": re.compile(r"\b(\d{5})\b"),
        "age": re.compile(r"\bage\s*(?:is|:)\s*(\d{1,3})\b", re.I),
    }

    def __init__(self) -> None:
        self.calls = 0

    def extract_answer(self, text: str, fields: list[str]) -> Extracted:
        out: dict[str, str | float | int | None] = {}
        for field in fields:
            pattern = self._PATTERNS.get(field)
            if not pattern:
                out[field] = None
                continue
            match = pattern.search(text)
            if not match:
                out[field] = None
                continue
            raw = match.group(1).strip()
            if field == "premium":
                out[field] = float(raw)
            elif field == "age":
                out[field] = int(raw)
            else:
                out[field] = raw
        self.calls += 1
        # Token estimate: 1 token per ~4 chars of input plus 5 per field.
        tokens = max(1, len(text) // 4 + 5 * len(fields))
        return Extracted(fields=out, tokens_used=tokens)

    def complete(self, prompt: str, max_tokens: int = 256) -> Completion:
        # Trivial echo with budget-shaped accounting.
        text = f"[mock-completion] {prompt[:60]}"
        self.calls += 1
        tokens = min(max_tokens, max(1, len(prompt) // 4))
        return Completion(text=text, tokens_used=tokens)


# Re-export so callers can `from catins.cortex.extract import CortexClient`
# without a second import line.
__all__ = ["CortexClient", "Completion", "Extracted", "MockCortex"]
