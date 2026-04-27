"""Phase 0 smoke test ensuring the test runner is wired up.

Removed once real tests land.
"""

import catins


def test_package_imports() -> None:
    """The catins package imports and exposes a version."""
    assert catins.__version__ == "0.1.0"
    assert catins.__all__ == []
