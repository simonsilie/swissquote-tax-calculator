"""Keep integration inputs independent of personal configuration."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_integration_directory(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration") is None:
        return
    directory: Path = request.getfixturevalue("tmp_path")
    monkeypatch: pytest.MonkeyPatch = request.getfixturevalue("monkeypatch")
    monkeypatch.chdir(directory)
