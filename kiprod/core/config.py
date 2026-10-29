"""Layered, validated configuration that never stores secrets."""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

from kiprod.core.defaults import Rule

DEFAULT_CONFIG: dict[str, object] = {
    "paths": {
        "production": "docs/production",
        "config": "docs/production/quotes/config",
        "state": "docs/production/.kiprod",
    },
    "quantities": {"boards": [1, 5, 25, 50, 100, 200, 400, 500, 1000]},
}

DEFAULT_TOML = """# Project-local KiProd settings. Secrets belong in the OS keyring.

[paths]
production = "docs/production"
config = "docs/production/quotes/config"
state = "docs/production/.kiprod"

[quantities]
boards = [1, 5, 25, 50, 100, 200, 400, 500, 1000]
"""


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
    components: dict[str, dict[str, Rule]] = {}


def _reject_secret_keys(value: object, prefix: str = "") -> None:
    secret_names = {
        "api_key",
        "password",
        "secret",
        "credential",
        "private_key",
        "token",
    }
    secret_suffixes = tuple(f"_{name}" for name in secret_names)
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in secret_names or normalized.endswith(secret_suffixes):
                raise ConfigError(
                    f"project setting {prefix + str(key)} resembles a secret; "
                    "store secret values in the OS keyring"
                )
            _reject_secret_keys(nested, f"{prefix}{key}.")
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested, prefix)


def save_project_config_text(project_root: Path, source: str) -> Path:
    """Validate and save project TOML verbatim, retaining comments and unknown keys."""
    try:
        parsed = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid project TOML: {exc}") from exc
    _reject_secret_keys(parsed)
    try:
        Settings.model_validate(_merge(DEFAULT_CONFIG, parsed))
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    destination = project_config_path(project_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = source.rstrip() + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(normalized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    load(project_root)
    return destination


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


def save_project_quantities(project_root: Path, boards: list[int]) -> Path:
    """Update only project board quantities while retaining other TOML settings."""
    normalized = Quantities(boards=boards).boards
    destination = project_config_path(project_root)
    source = destination.read_text(encoding="utf-8") if destination.is_file() else ""
    if source:
        parsed = tomllib.loads(source)
        quantities = parsed.get("quantities", {})
        if not isinstance(quantities, dict):
            raise ConfigError("project [quantities] setting must be a table")
        source = _update_quantities_table(source, normalized)
    else:
        source = f"[quantities]\nboards = {normalized}\n"
    try:
        tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"project config could not be updated safely: {exc}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(source.rstrip() + "\n")
        os.replace(temporary_name, destination)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    load(project_root)
    return destination


def _update_quantities_table(source: str, boards: list[int]) -> str:
    lines = source.splitlines()
    header = re.compile(r"^\s*\[quantities\]\s*(?:#.*)?$")
    start = next((index for index, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return source.rstrip() + f"\n\n[quantities]\nboards = {boards}\n"
    end = next(
        (index for index in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[index])),
        len(lines),
    )
    key_pattern = re.compile(r"^\s*boards\s*=(.*)$")
    key_index = next(
        (index for index in range(start + 1, end) if key_pattern.match(lines[index])), None
    )
    if key_index is None:
        lines.insert(end, f"boards = {boards}")
    else:
        match = key_pattern.match(lines[key_index])
        assert match is not None
        value = match.group(1).split("#", maxsplit=1)[0].strip()
        if value.startswith("[") and "]" not in value:
            raise ConfigError("cannot edit a multiline quantities.boards array from the GUI")
        lines[key_index] = f"boards = {boards}"
    return "\n".join(lines) + "\n"


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
