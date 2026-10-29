from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Manifest


class PluginSettingsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    plugin_id: str
    values: dict[str, Any] = Field(default_factory=dict)


def settings_path(project_root: Path, plugin_id: str) -> Path:
    safe_id = hashlib.sha256(plugin_id.encode("utf-8")).hexdigest()[:24]
    return (
        project_root
        / "docs"
        / "production"
        / "quotes"
        / "config"
        / "plugin-settings"
        / f"{safe_id}.json"
    )


def load_plugin_settings(project_root: Path, plugin_id: str) -> dict[str, Any]:
    path = settings_path(project_root, plugin_id)
    if not path.is_file():
        return {}
    document = PluginSettingsDocument.model_validate_json(path.read_text(encoding="utf-8"))
    if document.plugin_id != plugin_id:
        raise ValueError("plugin settings file belongs to a different plugin")
    return document.values


def validate_plugin_settings(manifest: Manifest, values: dict[str, Any]) -> dict[str, Any]:
    fields = {str(field["key"]): field for field in manifest.fields}
    credential_keys = {credential.key for credential in manifest.credentials}
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in credential_keys:
            raise ValueError(f"credential {key!r} must use the operating system keyring")
        if key not in fields:
            continue
        field = fields[key]
        if field.get("type", "string") == "secret":
            raise ValueError(f"secret field {key!r} must use the operating system keyring")
        if value is None:
            if field.get("required", False):
                raise ValueError(f"{key} is required")
            result[key] = None
            continue
        kind = field.get("type", "string")
        if kind in {"string", "text", "date", "file"}:
            valid = isinstance(value, str)
        elif kind == "bool":
            valid = isinstance(value, bool)
        elif kind == "int":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "float":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            valid = valid and math.isfinite(float(value)) if valid else False
        elif kind == "enum":
            valid = isinstance(value, str)
        elif kind == "multi_enum":
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        else:
            continue
        if not valid:
            raise ValueError(f"{key} must have a value of type {kind}")
        options = field.get("options")
        if isinstance(options, list):
            allowed = {
                str(item.get("value", item.get("label", "")))
                if isinstance(item, dict)
                else str(item)
                for item in options
            }
            candidates = value if isinstance(value, list) else [value]
            if kind in {"enum", "multi_enum"} and any(item not in allowed for item in candidates):
                raise ValueError(f"{key} contains a value outside its manifest options")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum, maximum = field.get("min"), field.get("max")
            if isinstance(minimum, (int, float)) and value < minimum:
                raise ValueError(f"{key} must be at least {minimum}")
            if isinstance(maximum, (int, float)) and value > maximum:
                raise ValueError(f"{key} must be at most {maximum}")
        pattern = field.get("pattern")
        if isinstance(value, str) and isinstance(pattern, str) and not re.search(pattern, value):
            raise ValueError(f"{key} does not match its manifest pattern")
        result[key] = value
    for key, field in fields.items():
        if field.get("required", False) and key not in values:
            raise ValueError(f"{key} is required")
    return result


def save_plugin_settings(project_root: Path, manifest: Manifest, values: dict[str, Any]) -> Path:
    validated = validate_plugin_settings(manifest, values)
    path = settings_path(project_root, manifest.id)
    prior = load_plugin_settings(project_root, manifest.id)
    document = PluginSettingsDocument(
        plugin_id=manifest.id,
        values={**prior, **validated},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(document.model_dump_json(indent=2) + "\n")
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return path
