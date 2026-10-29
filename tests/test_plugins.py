from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiprod.plugins.host import PluginError, check_network_permission, load_plugin

FIXTURE = Path(__file__).parent / "plugins" / "fixture"


def test_loads_manifest_and_adapter() -> None:
    plugin = load_plugin(FIXTURE)
    assert plugin.manifest.id == "com.example.fixture"
    assert plugin.manifest.resource_types == ["components"]
    assert plugin.adapter_class is not None
    assert plugin.adapter_class().health_check() == {"ok": True}


def test_enforces_declared_network_allowlist() -> None:
    plugin = load_plugin(FIXTURE)
    check_network_permission(plugin, "parts.example.test")
    with pytest.raises(PluginError, match="did not declare"):
        check_network_permission(plugin, "other.example.test")


def test_rejects_invalid_manifest(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"name": "incomplete"}))
    with pytest.raises(PluginError, match="invalid plugin manifest"):
        load_plugin(tmp_path)
