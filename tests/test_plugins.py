from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kiprod.cli import app
from kiprod.net.http import HttpClient, HttpError, HttpResponse
from kiprod.plugins.host import PluginError, check_network_permission, load_plugin
from kiprod.plugins.suppliers.json_catalog import JsonCatalogAdapter

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


def test_generic_json_catalog_protocol_maps_recorded_response() -> None:
    endpoint = "https://parts.example.test/v1/offers"
    url = endpoint + "?mpn=RC0603FR-074K7L"
    fixture = HttpResponse(
        200,
        {"content-type": "application/json"},
        json.dumps(
            {
                "items": [
                    {
                        "supplier_part_number": "C14663",
                        "manufacturer_part_number": "RC0603FR-074K7L",
                        "currency": "USD",
                        "stock": 12000,
                        "lead_time_days": 3,
                        "price_breaks": [
                            {"quantity": 1, "unit_price": "0.01"},
                            {"quantity": 1000, "unit_price": "0.004"},
                        ],
                    },
                    {
                        "supplier_part_number": "OTHER",
                        "manufacturer_part_number": "OTHER-MPN",
                        "currency": "USD",
                        "price_breaks": [{"quantity": 1, "unit_price": "1.00"}],
                    },
                ]
            }
        ).encode(),
    )
    client = HttpClient({"parts.example.test"}, fixtures={("GET", url): fixture})

    offers = JsonCatalogAdapter(client).search(
        "RC0603FR-074K7L",
        endpoint=endpoint,
        supplier_id="supplier-a",
        currency="USD",
        bearer_token="fixture-token",
    )

    assert len(offers) == 1
    assert offers[0].supplier_part_number == "C14663"
    assert offers[0].price_breaks[1].unit_price == 0.004
    assert offers[0].source_ref.path == endpoint
    assert offers[0].source_ref.reference == "RC0603FR-074K7L"


def test_generic_json_catalog_protocol_rejects_http_and_currency_mismatch() -> None:
    adapter = JsonCatalogAdapter(HttpClient({"parts.example.test"}))
    with pytest.raises(ValueError, match="HTTPS"):
        adapter.search("X1", endpoint="http://parts.example.test/search", supplier_id="a")

    endpoint = "https://parts.example.test/search"
    url = endpoint + "?mpn=X1"
    payload = {
        "items": [
            {
                "supplier_part_number": "P1",
                "manufacturer_part_number": "X1",
                "currency": "EUR",
                "price_breaks": [{"quantity": 1, "unit_price": 1}],
            }
        ]
    }
    client = HttpClient(
        {"parts.example.test"},
        fixtures={
            ("GET", url): HttpResponse(200, {}, json.dumps(payload).encode())
        },
    )
    with pytest.raises(HttpError, match="currency mismatch"):
        JsonCatalogAdapter(client).search(
            "X1", endpoint=endpoint, supplier_id="a", currency="USD"
        )


def test_adapter_search_runs_in_worker_from_recorded_fixture() -> None:
    plugin = load_plugin(FIXTURE)
    url = "https://parts.example.test/v1/search?mpn=RC0603FR-074K7L"
    fixture = HttpResponse(
        200,
        {"content-type": "application/json"},
        (FIXTURE / "fixtures" / "search.json").read_bytes(),
    )
    http = HttpClient({"parts.example.test"}, fixtures={("GET", url): fixture})
    offers = plugin.call("search", "RC0603FR-074K7L", http=http)
    assert offers[0]["manufacturer_part_number"] == "RC0603FR-074K7L"
    unknown_url = "https://parts.example.test/v1/search?mpn=UNKNOWN"
    unknown_fixture = HttpResponse(
        200,
        {"content-type": "application/json"},
        b'{"query":"UNKNOWN","offers":[]}',
    )
    unknown_http = HttpClient(
        {"parts.example.test"}, fixtures={("GET", unknown_url): unknown_fixture}
    )
    assert plugin.call("search", "UNKNOWN", http=unknown_http) == []


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
