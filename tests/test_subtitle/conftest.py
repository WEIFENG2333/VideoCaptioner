"""Test configuration for subtitle tests."""

import sys

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for testing Qt components."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Don't quit - causes issues with pytest


@pytest.fixture(autouse=True)
def use_qapp(qapp):
    """Automatically use QApplication for all tests in this module."""
    return qapp
