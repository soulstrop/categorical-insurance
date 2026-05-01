"""Tokenisation Protocol + mock client per ADR 006 §2.

# math: math.tex §VII.B (boundary-preserving lift through tokenisation)

ADR 006 distinguishes how PII categories are protected:

* **Direct identifiers** (name, SSN, account numbers) — tokenised at
  the staging boundary via Vault Transform; the warehouse only ever
  sees the token. This module covers that path.
* **Quasi identifiers** (DOB, ZIP, age) — protected at read time via
  DDM masking; the warehouse stores them in plaintext. Out of scope
  here.

The Protocol seam (``TokenisationClient``) is shaped to match
``hvac``'s Vault Transform API so the prod swap is one resource
binding in Dagster ``Definitions``: replace
``MockTokenisationClient`` with a Vault-backed implementation that
delegates to ``client.secrets.transform.encode`` /
``decode``. Asset code calls the same protocol either way.

The mock is deterministic, alphabet-preserving (per-position
character class survives), and fully reversible via an in-process
map. It is *not* cryptographically secure — production data must
not flow through the mock.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from catins.privacy.pii import pii_fields


@runtime_checkable
class TokenisationClient(Protocol):
    """Reversible tokenisation client, Vault-Transform-shaped."""

    def tokenise(self, plaintext: str, transformation: str = "default") -> str:
        """Convert plaintext → token. Same input → same token."""
        ...

    def detokenise(self, token: str, transformation: str = "default") -> str:
        """Convert token → plaintext. Raises ``KeyError`` on unknown token."""
        ...


def _alphabet_preserving_token(plaintext: str, transformation: str) -> str:
    """Produce a same-length, per-position class-matching token.

    Uppercase → uppercase, lowercase → lowercase, digit → digit,
    other characters (whitespace, punctuation) preserved verbatim.
    Deterministic via SHA-256 keyed on ``transformation::plaintext``;
    collisions are not handled (mock-grade).
    """
    seed = f"{transformation}::{plaintext}".encode()
    digest = hashlib.sha256(seed).digest()
    out: list[str] = []
    for i, ch in enumerate(plaintext):
        b = digest[i % len(digest)]
        if ch.isupper():
            out.append(chr(ord("A") + b % 26))
        elif ch.islower():
            out.append(chr(ord("a") + b % 26))
        elif ch.isdigit():
            out.append(str(b % 10))
        else:
            out.append(ch)
    return "".join(out)


class MockTokenisationClient:
    """In-process tokenisation for dev / tests.

    Forward direction is pure (hash-derived); reverse direction
    consults an in-process map populated when the plaintext is
    first tokenised. The map is per-instance; tests should use
    one client across the round-trip.
    """

    def __init__(self) -> None:
        self._reverse: dict[tuple[str, str], str] = {}

    def tokenise(self, plaintext: str, transformation: str = "default") -> str:
        token = _alphabet_preserving_token(plaintext, transformation)
        self._reverse[(token, transformation)] = plaintext
        return token

    def detokenise(self, token: str, transformation: str = "default") -> str:
        key = (token, transformation)
        if key not in self._reverse:
            msg = f"unknown token: {token!r} (transformation={transformation!r})"
            raise KeyError(msg)
        return self._reverse[key]


# --- Pydantic-aware helpers ---


def _direct_pii_string_fields(model_cls: type[BaseModel]) -> list[str]:
    """Field names with PII("direct", …) annotation and a string type."""
    out: list[str] = []
    pii = pii_fields(model_cls)
    for name, marker in pii.items():
        if marker.category != "direct":
            continue
        annotation = model_cls.model_fields[name].annotation
        if annotation is str:
            out.append(name)
    return out


def tokenise_model[M: BaseModel](
    model: M,
    client: TokenisationClient,
    transformation_for: Callable[[str], str] = lambda name: name,
) -> M:
    """Return a copy of ``model`` with direct-PII string fields tokenised.

    Quasi-PII (DOB, ZIP, age) is left in plaintext — masking handles
    that at read time per ADR 006 §3. Non-PII fields are untouched.
    """
    targets = _direct_pii_string_fields(type(model))
    if not targets:
        return model
    updates: dict[str, Any] = {}
    for name in targets:
        plaintext = getattr(model, name)
        updates[name] = client.tokenise(plaintext, transformation=transformation_for(name))
    return model.model_copy(update=updates)


def detokenise_model[M: BaseModel](
    model: M,
    client: TokenisationClient,
    transformation_for: Callable[[str], str] = lambda name: name,
) -> M:
    """Inverse of :func:`tokenise_model`."""
    targets = _direct_pii_string_fields(type(model))
    if not targets:
        return model
    updates: dict[str, Any] = {}
    for name in targets:
        token = getattr(model, name)
        updates[name] = client.detokenise(token, transformation=transformation_for(name))
    return model.model_copy(update=updates)
