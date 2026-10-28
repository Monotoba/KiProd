"""Layered, validated configuration that never stores secrets."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

DEFAULT_CONFIG: dict[str, object] = {
    "paths": {
        "production": "docs/production",
        "config": "docs/production/quotes/config",
        "state": "docs/production/.kiprod",
    },
    "quantities": {"boards": [1, 5, 25, 50, 100, 200, 400, 500, 1000]},
}


class ConfigError(ValueError):
    pass


class Paths(BaseModel):
    production: str
    config: str
    state: str


class Quantities(BaseModel):
    boards: list[int]

    @field_validator("boards")
    @classmethod
    def valid_boards(cls, values: list[int]) -> list[int]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("board quantities must be positive integers")
        if len(values) != len(set(values)):
            raise ValueError("board quantities must not contain duplicates")
        return sorted(values)


class Settings(BaseModel):
    paths: Paths
    quantities: Quantities


def _merge(base: dict[str, object], override: Mapping[str, Any]) -> dict[str, object]:
    merged = deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def _read(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return loaded


def project_config_path(project_root: Path) -> Path:
    return project_root / "docs" / "production" / "quotes" / "config" / "kiprod.toml"


def load(project_root: Path, user_config: Path | None = None) -> Settings:
    """Load built-in defaults, optional user config, then project config."""
    data = deepcopy(DEFAULT_CONFIG)
    candidates = [user_config, project_config_path(project_root)]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            data = _merge(data, _read(candidate))
    try:
        return Settings.model_validate(data)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def parse_quantities(value: str) -> list[int]:
    """Parse comma values and inclusive `start..end:step` shorthand."""
    parsed: list[int] = []
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        if ".." in token:
            try:
                boundaries, step_text = token.split(":", maxsplit=1)
                start_text, end_text = boundaries.split("..", maxsplit=1)
                start, end, step = int(start_text), int(end_text), int(step_text)
            except ValueError as exc:
                raise ConfigError(f"invalid quantity range: {token}") from exc
            if start <= 0 or end < start or step <= 0:
                raise ConfigError(f"invalid quantity range: {token}")
            parsed.extend(range(start, end + 1, step))
        else:
            try:
                parsed.append(int(token))
            except ValueError as exc:
                raise ConfigError(f"invalid quantity: {token}") from exc
    try:
        return Quantities(boards=parsed).boards
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def update_quantities(
    current: list[int],
    replacement: str | None = None,
    add: list[int] | None = None,
    remove: list[int] | None = None,
) -> list[int]:
    values = set(parse_quantities(replacement)) if replacement is not None else set(current)
    values.update(add or [])
    values.difference_update(remove or [])
    try:
        return Quantities(boards=list(values)).boards
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
