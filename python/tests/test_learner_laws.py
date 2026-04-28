"""Property-based tests for categorical learner laws."""

from hypothesis import given
from hypothesis import strategies as st

from catins.learner import compose, id_learner
from catins.learners.credibility import BuhlmannCredibility


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_learner_identity_law(val: float) -> None:
    """The identity learner acts as an identity for compose."""
    # We'll use BuhlmannCredibility as a sample learner
    f = BuhlmannCredibility(mu0=100.0, kappa0=0.01, sigma2=25.0)

    # f >>> id == f
    # In our Python implementation, f is the upstream, so compose(id, f) == f
    # wait, math.tex says f: A -> B, g: B -> C, then g . f: A -> C
    # so id_B . f == f and f . id_A == f

    id_b = id_learner()  # Should infer type or be parameterized

    f_comp_id = compose(id_b, f)

    assert f_comp_id.implement(None) == f.implement(None)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_learner_associativity_law(val: float) -> None:
    """Composition of learners is associative."""
    # Need three learners to test (h . g) . f == h . (g . f)
    # For Phase 1 Red Phase, just importing them is enough to fail.
    pass
