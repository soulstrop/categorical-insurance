"""Test smoke tests and examples."""

from catins.examples import insurance


def test_insurance_demo() -> None:
    """The insurance demo runs without error."""
    # This will currently fail on import of catins.examples.insurance
    # because it tries to import non-existent catins modules.
    insurance.demo()
