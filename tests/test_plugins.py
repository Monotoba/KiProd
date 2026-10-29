from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kiprod.cli import app
from kiprod.plugins.host import PluginError, check_network_permission, load_plugin

FIXTURE = Path(__file__).parent / "plugins" / "fixture"


def test_loads_manifest_and_adapter() -> None:
    plugin = load_plugin(FIXTURE)
    assert plugin.manifest.id == "com.example.fixture"
    assert plugin.manifest.resource_types == ["components"]
    assert plugin.call("health_check") == {"ok": True}


def test_enforces_declared_network_allowlist() -> None:
    plugin = load_plugin(FIXTURE)
    check_network_permission(plugin, "parts.example.test")
    with pytest.raises(PluginError, match="did not declare"):
        check_network_permission(plugin, "other.example.test")


def test_rejects_invalid_manifest(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"name": "incomplete"}))
    with pytest.raises(PluginError, match="invalid plugin manifest"):
        load_plugin(tmp_path)


def test_manifest_field_declarations_are_validated(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "id": "test.invalid-fields",
                "name": "Invalid fields",
                "version": "1",
                "fields": [{"key": "token", "type": "magic"}],
            }
        )
    )
    with pytest.raises(PluginError, match="unsupported plugin field type"):
        load_plugin(tmp_path)


def test_recorded_fixture_is_present_and_traceable() -> None:
    fixture = json.loads((FIXTURE / "fixtures" / "search.json").read_text())
    offer = fixture["offers"][0]
    assert fixture["query"] == offer["manufacturer_part_number"]
    assert offer["supplier_part_number"] == "C14663"


def test_adapter_search_runs_in_worker_from_recorded_fixture() -> None:
    plugin = load_plugin(FIXTURE)
    offers = plugin.call("search", "RC0603FR-074K7L")
    assert offers[0]["manufacturer_part_number"] == "RC0603FR-074K7L"
    assert plugin.call("search", "UNKNOWN") == []


def test_adapter_worker_rejects_unknown_method() -> None:
    plugin = load_plugin(FIXTURE)
    with pytest.raises(PluginError, match="AttributeError"):
        plugin.call("delete_everything")


def test_plugin_cli_lists_project_plugins(tmp_path: Path) -> None:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    supplier_dir = tmp_path / "docs/production/quotes/config/suppliers/fixture"
    supplier_dir.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(FIXTURE, supplier_dir)
    result = CliRunner().invoke(app, ["plugins", "list", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "com.example.fixture" in result.output


def test_plugin_cli_runs_health_check(tmp_path: Path) -> None:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    supplier_dir = tmp_path / "docs/production/quotes/config/suppliers/fixture"
    supplier_dir.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(FIXTURE, supplier_dir)
    result = CliRunner().invoke(
        app,
        ["plugins", "test", "com.example.fixture", "--project", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "com.example.fixture" in result.output
