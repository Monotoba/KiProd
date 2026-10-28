from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.core.config import ConfigError, load, parse_quantities, update_quantities


def test_configuration_layers_project_over_user(tmp_path: Path) -> None:
    user = tmp_path / "user.toml"
    user.write_text("[quantities]\nboards = [2, 10]\n")
    project = tmp_path / "docs/production/quotes/config"
    project.mkdir(parents=True)
    (project / "kiprod.toml").write_text("[quantities]\nboards = [5, 25]\n")
    assert load(tmp_path, user).quantities.boards == [5, 25]


def test_quantities_support_ranges_and_changes() -> None:
    assert parse_quantities("1, 10..30:10") == [1, 10, 20, 30]
    assert update_quantities([1, 5], add=[10], remove=[1]) == [5, 10]


def test_rejects_invalid_quantity_ranges() -> None:
    with pytest.raises(ConfigError):
        parse_quantities("10..1:1")
