"""Shared fixtures: a synthetic hierarchy built once, and config helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from create_test_fixture import FixtureInfo, create_fixture
from hrm_converter.config import Config, build_config

ConfigFactory = Callable[..., Config]


@pytest.fixture(scope="session")
def hierarchy(tmp_path_factory: pytest.TempPathFactory) -> FixtureInfo:
    """The synthetic folder hierarchy. Tests must treat it as read-only."""
    return create_fixture(tmp_path_factory.mktemp("hrm fixture with spaces"))


@pytest.fixture
def make_config(tmp_path: Path) -> ConfigFactory:
    """Config whose output and logs go to the test's own temporary folder."""

    def factory(**sections: dict[str, Any]) -> Config:
        user: dict[str, Any] = {
            "output": {"directory": str(tmp_path / "out")},
            "logging": {"directory": str(tmp_path / "logs")},
        }
        for name, values in sections.items():
            user[name] = {**user.get(name, {}), **values}
        return build_config(user)

    return factory


@pytest.fixture
def config(make_config: ConfigFactory) -> Config:
    return make_config()
