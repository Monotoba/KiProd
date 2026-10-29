from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import Request

import pytest

from kiprod.net.http import HttpClient, HttpError, HttpResponse, _SameOriginRedirectHandler
from kiprod.plugins.host import load_plugin
from kiprod.plugins.suppliers.recorded_catalog import RecordedCatalogAdapter


def test_http_client_enforces_https_host_allowlist() -> None:
    client = HttpClient({"parts.example.test"})
    with pytest.raises(HttpError, match="not permitted"):
        client.get("https://other.example.test/parts")
    with pytest.raises(HttpError, match="not permitted"):
        client.get("http://parts.example.test/parts")


def test_http_client_can_allow_explicit_loopback_http_for_local_models() -> None:
    local_url = "http://127.0.0.1:11434/v1/chat/completions"
    response = HttpResponse(200, {}, b"{}")
    client = HttpClient(
        {"127.0.0.1"},
        allow_local_http=True,
        fixtures={("GET", local_url): response},
    )

    assert client.get(local_url).status == 200
    with pytest.raises(HttpError, match="not permitted"):
        client.get("http://192.0.2.1/v1/chat/completions")


def test_http_client_rejects_cross_origin_redirects() -> None:
    request = Request("https://parts.example.test/v1/search")
    handler = _SameOriginRedirectHandler()

    with pytest.raises(HTTPError, match="cross-origin redirect"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://other.example.test/v1/search",
        )


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
