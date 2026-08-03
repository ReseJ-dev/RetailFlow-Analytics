"""Smoke tests for the project scaffold."""

import retailflow


def test_package_can_be_imported() -> None:
    """The installed source package should be importable."""
    assert retailflow.__version__ == "0.1.0"
