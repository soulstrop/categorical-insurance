"""Cortex token-budget decorator.

Wraps any ``CortexClient`` to enforce a per-run token cap and exposes
the running total via ``total_tokens``. The Phase 3 asset check
``check_cortex_budget`` reads the same accumulator.
"""

from catins.cortex.client import Completion, CortexClient, Extracted


class BudgetExceededError(RuntimeError):
    """Raised when a Cortex call would push spend past the cap."""


class BudgetedCortex:
    """A budget-enforcing wrapper around a ``CortexClient``.

    The wrapper is itself a ``CortexClient`` (structural Protocol), so
    callers can substitute it transparently.
    """

    def __init__(self, inner: CortexClient, *, max_tokens: int) -> None:
        self._inner = inner
        self._max = max_tokens
        self._total = 0

    @property
    def total_tokens(self) -> int:
        return self._total

    @property
    def max_tokens(self) -> int:
        return self._max

    def _charge(self, tokens: int) -> None:
        if self._total + tokens > self._max:
            msg = (
                f"Cortex budget exceeded: would spend {self._total + tokens} tokens "
                f"of cap {self._max}"
            )
            raise BudgetExceededError(msg)
        self._total += tokens

    def extract_answer(self, text: str, fields: list[str]) -> Extracted:
        result = self._inner.extract_answer(text, fields)
        self._charge(result.tokens_used)
        return result

    def complete(self, prompt: str, max_tokens: int = 256) -> Completion:
        result = self._inner.complete(prompt, max_tokens=max_tokens)
        self._charge(result.tokens_used)
        return result
