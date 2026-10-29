from __future__ import annotations

import pytest

from kiprod.net.http import HttpClient, HttpError, HttpResponse
from kiprod.plugins.host import load_plugin
from kiprod.plugins.suppliers.recorded_catalog import RecordedCatalogAdapter


def test_http_client_enforces_https_host_allowlist() -> None:
    client = HttpClient({"parts.example.test"})
    with pytest.raises(HttpError, match="not permitted"):
        client.get("https://other.example.test/parts")
    with pytest.raises(HttpError, match="not permitted"):
        client.get("http://parts.example.test/parts")


def test_http_client_replays_recorded_fixture_and_caches_get() -> None:
    url = "https://parts.example.test/search?q=abc"
    expected = HttpResponse(200, {"content-type": "application/json"}, b'{"items": []}')
    client = HttpClient({"parts.example.test"}, fixtures={("GET", url): expected})
    first = client.get(url)
    second = client.get(url)
    assert first.json() == {"items": []}
    assert not first.from_cache
    assert second.from_cache


def test_plugin_client_uses_only_declared_hosts() -> None:
    plugin = load_plugin(__import__("pathlib").Path(__file__).parent / "plugins" / "fixture")
    client = plugin.http_client()
    assert client.allowed_hosts == {"parts.example.test"}
    with pytest.raises(HttpError):
        client.get("https://unlisted.example.test/")


def test_recorded_catalog_adapter_returns_source_backed_offer() -> None:
    url = "https://parts.example.test/v1/search?mpn=RC0603FR-074K7L"
    fixture = HttpResponse(
        200,
        {"content-type": "application/json"},
        (
            __import__("pathlib").Path(__file__).parent / "fixtures" / "recorded_catalog.json"
        ).read_bytes(),
    )
    client = HttpClient({"parts.example.test"}, fixtures={("GET", url): fixture})
    offers = RecordedCatalogAdapter(client).search("RC0603FR-074K7L")
    assert len(offers) == 1
    offer = offers[0]
    assert offer.source_ref.reference == "RC0603FR-074K7L"
    assert offer.price_breaks[1].unit_price == 0.004
    assert offer.stock == 12000
