"""Classify integration coverage without adding pytest to stdlib-only suites."""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.stem.endswith("_integration") or item.name.startswith("test_integration_"):
            item.add_marker(pytest.mark.integration)
