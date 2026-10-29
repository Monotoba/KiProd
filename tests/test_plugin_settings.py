from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiprod.plugins.models import Manifest
from kiprod.plugins.settings import (
    load_plugin_settings,
    save_plugin_settings,
    settings_path,
)


def _manifest() -> Manifest:
    return Manifest.model_validate(
        {
            "id": "com.example.parts",
            "name": "Example Parts",
            "version": "1.0",
            "credentials": [{"key": "token", "label": "API token"}],
            "fields": [
                {"key": "region", "type": "enum", "options": ["US", "EU"]},
                {"key": "page_size", "type": "int", "min": 1, "max": 100},
                {"key": "enabled", "type": "bool"},
            ],
        }
    )


def test_plugin_settings_validate_and_keep_unknown_values(tmp_path: Path) -> None:
    manifest = _manifest()
    path = save_plugin_settings(
        tmp_path,
        manifest,
        {"region": "EU", "page_size": 25, "enabled": True},
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"]["future_plugin_key"] = "keep me"
    path.write_text(json.dumps(document), encoding="utf-8")

    save_plugin_settings(tmp_path, manifest, {"page_size": 50})

    values = load_plugin_settings(tmp_path, manifest.id)
    assert values == {
        "region": "EU",
        "page_size": 50,
        "enabled": True,
        "future_plugin_key": "keep me",
    }


def test_plugin_settings_reject_invalid_values_and_credentials(tmp_path: Path) -> None:
    manifest = _manifest()
    with pytest.raises(ValueError, match="outside its manifest options"):
        save_plugin_settings(tmp_path, manifest, {"region": "APAC"})
    with pytest.raises(ValueError, match="at most 100"):
        save_plugin_settings(tmp_path, manifest, {"page_size": 200})
    with pytest.raises(ValueError, match="operating system keyring"):
        save_plugin_settings(tmp_path, manifest, {"token": "never persist this"})
    assert not settings_path(tmp_path, manifest.id).exists()
