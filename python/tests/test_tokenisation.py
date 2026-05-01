"""Tests for the tokenisation Protocol + mock client (P2R.7).

Covers:

* MockTokenisationClient: round-trip integrity, alphabet preservation
  (per-position character class survives), determinism, transformation
  isolation, unknown-token handling.
* tokenise_model / detokenise_model: only direct-PII string fields are
  touched (quasi and non-PII left alone), the model identity round-
  trips, and the discriminated-union branches behave per ADR 006 §1
  (IndividualHolder.name tokenises; EntityHolder.name does not).
* TokenisationClient is a Protocol — runtime_checkable so tests can
  isinstance-check.
"""

import pytest

from catins.models import CanonicalProposal, EntityHolder, IndividualHolder
from catins.privacy import (
    MockTokenisationClient,
    TokenisationClient,
    detokenise_model,
    tokenise_model,
)

# --- MockTokenisationClient ---


def test_mock_round_trip_recovers_plaintext() -> None:
    c = MockTokenisationClient()
    token = c.tokenise("Alice")
    assert c.detokenise(token) == "Alice"


def test_mock_is_deterministic() -> None:
    """Same plaintext + transformation → same token across calls."""
    c = MockTokenisationClient()
    assert c.tokenise("Alice") == c.tokenise("Alice")


def test_mock_alphabet_preserves_length() -> None:
    c = MockTokenisationClient()
    for plaintext in ["Alice", "X", "Some longer name", "a"]:
        assert len(c.tokenise(plaintext)) == len(plaintext)


def test_mock_alphabet_preserves_per_position_class() -> None:
    """Per-position case + digit-vs-letter survives the tokenisation."""
    c = MockTokenisationClient()
    plaintext = "Alice123-Bob"
    token = c.tokenise(plaintext)
    assert len(token) == len(plaintext)
    for orig_ch, tok_ch in zip(plaintext, token, strict=True):
        if orig_ch.isupper():
            assert tok_ch.isupper(), f"position {orig_ch!r} → {tok_ch!r}"
        elif orig_ch.islower():
            assert tok_ch.islower(), f"position {orig_ch!r} → {tok_ch!r}"
        elif orig_ch.isdigit():
            assert tok_ch.isdigit(), f"position {orig_ch!r} → {tok_ch!r}"
        else:
            # Non-alphanumeric (whitespace, punctuation) preserved verbatim.
            assert tok_ch == orig_ch, f"position {orig_ch!r} → {tok_ch!r}"


def test_mock_distinct_plaintexts_get_distinct_tokens() -> None:
    """Different inputs yield different tokens (no collisions in practice)."""
    c = MockTokenisationClient()
    tokens = {c.tokenise(name) for name in ["Alice", "Bob", "Charlie", "Dee", "Erin"]}
    assert len(tokens) == 5


def test_mock_transformation_isolates_namespaces() -> None:
    """The same plaintext under different transformations yields different tokens."""
    c = MockTokenisationClient()
    a = c.tokenise("Alice", transformation="names")
    b = c.tokenise("Alice", transformation="ssns")
    assert a != b
    assert c.detokenise(a, transformation="names") == "Alice"
    assert c.detokenise(b, transformation="ssns") == "Alice"


def test_mock_detokenise_unknown_raises() -> None:
    c = MockTokenisationClient()
    with pytest.raises(KeyError, match="unknown token"):
        c.detokenise("Xdiqu")  # never tokenised


def test_mock_detokenise_wrong_transformation_raises() -> None:
    """Detokenising with the wrong transformation namespace fails."""
    c = MockTokenisationClient()
    token = c.tokenise("Alice", transformation="names")
    with pytest.raises(KeyError):
        c.detokenise(token, transformation="ssns")


def test_mock_satisfies_tokenisation_client_protocol() -> None:
    c = MockTokenisationClient()
    assert isinstance(c, TokenisationClient)


# --- tokenise_model / detokenise_model ---


def _proposal(name: str = "Alice", kind: str = "individual") -> CanonicalProposal:
    return CanonicalProposal(
        holder_kind=kind,  # type: ignore[arg-type]
        holder_name=name,
        premium=100.0,
        zip_code="10001",
        age=30,
    )


def test_tokenise_model_replaces_direct_pii_only() -> None:
    """holder_name (direct PII) is tokenised; quasi/non-PII untouched."""
    c = MockTokenisationClient()
    p = _proposal()
    t = tokenise_model(p, c)
    # Direct-PII fields tokenised:
    assert t.holder_name != "Alice"
    assert len(t.holder_name) == 5
    # Quasi-PII fields unchanged:
    assert t.zip_code == "10001"
    assert t.age == 30
    # Non-PII fields unchanged:
    assert t.premium == 100.0
    assert t.holder_kind == "individual"
    assert t.schema_version == 1


def test_tokenise_detokenise_model_round_trip() -> None:
    c = MockTokenisationClient()
    p = _proposal(name="Charlie")
    t = tokenise_model(p, c)
    recovered = detokenise_model(t, c)
    assert recovered == p


def test_tokenise_individual_holder() -> None:
    """IndividualHolder.name carries direct PII annotation; tokenised."""
    c = MockTokenisationClient()
    h = IndividualHolder(name="Bob")
    t = tokenise_model(h, c)
    assert t.name != "Bob"
    assert len(t.name) == 3
    assert detokenise_model(t, c) == h


def test_tokenise_entity_holder_is_no_op() -> None:
    """Per ADR 006 §1: business records are not PII; tokenise_model
    leaves them unchanged."""
    c = MockTokenisationClient()
    e = EntityHolder(name="Acme Corp")
    t = tokenise_model(e, c)
    assert t == e
    assert t.name == "Acme Corp"


def test_tokenise_canonical_proposal_with_entity_kind_still_tokenises_holder_name() -> None:
    """Over-protection caveat from P2R.3: proposal-level holder_name is
    annotated PII unconditionally, so even an entity-holder proposal
    has its name tokenised at the proposal layer. The EntityHolder
    type itself (consulted via `.holder`) preserves the unprotected
    semantic."""
    c = MockTokenisationClient()
    p = _proposal(name="Acme Corp", kind="entity")
    t = tokenise_model(p, c)
    assert t.holder_name != "Acme Corp"  # over-protection at proposal level
    # The conditional semantic still holds at the union-branch level:
    e = EntityHolder(name="Acme Corp")
    assert tokenise_model(e, c).name == "Acme Corp"  # not tokenised


def test_tokenise_model_uses_per_field_transformation_namespace() -> None:
    """Each PII field gets its own transformation namespace by default,
    matching Vault's convention of one transformation per logical
    field (so leak of one transformation's keys doesn't compromise
    the others)."""
    c = MockTokenisationClient()
    p1 = _proposal(name="Alice")
    p2 = IndividualHolder(name="Alice")  # same plaintext, different field name
    t1 = tokenise_model(p1, c)
    t2 = tokenise_model(p2, c)
    # Same plaintext, different transformation (field name) → different tokens.
    assert t1.holder_name != t2.name


def test_tokenise_model_with_custom_transformation_for() -> None:
    """The transformation_for hook lets callers override per-field naming."""
    c = MockTokenisationClient()
    p = _proposal(name="Alice")
    # Force all fields onto the same transformation namespace.
    t = tokenise_model(p, c, transformation_for=lambda _: "shared")
    assert c.detokenise(t.holder_name, transformation="shared") == "Alice"


def test_tokenise_model_idempotent_on_already_tokenised() -> None:
    """tokenise(tokenise(x)) re-tokenises (the token is itself a string).

    Documents the design: callers must track tokenisation state; the
    helpers don't ward against double-tokenisation."""
    c = MockTokenisationClient()
    p = _proposal()
    once = tokenise_model(p, c)
    twice = tokenise_model(once, c)
    assert twice.holder_name != once.holder_name  # tokenised again
    # And the inverse-twice recovers the once-tokenised form.
    assert detokenise_model(twice, c) == once
