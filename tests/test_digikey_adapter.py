from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kiprod.net.http import HttpClient, HttpResponse
from kiprod.plugins.host import load_plugin
from kiprod.plugins.suppliers.digikey.adapter import DigiKeyAdapter


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeHttp:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, bytes, dict[str, str]]] = []

    def post(self, url: str, body: bytes, *, headers: dict[str, str]) -> FakeResponse:
        self.requests.append((url, body, headers))
        return self.responses.pop(0)


def _fixture(name: str) -> Any:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_digikey_search_maps_exact_standard_pricing_and_stock() -> None:
    http = FakeHttp(
        [
            FakeResponse(200, _fixture("digikey_oauth_response.json")),
            FakeResponse(200, _fixture("digikey_search_response.json")),
        ]
    )
    offers = DigiKeyAdapter(http).search(
        "RC0603FR-074K7L",
        client_id="fixture-client-id",
        client_secret="fixture-client-secret",
        site="CA",
        language="fr",
        currency="CAD",
    )

    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_part_number == "13-RC0603FR-074K7LCT-ND"
    assert [price.quantity for price in offer.price_breaks] == [1, 100]
    assert offer.price_breaks[0].unit_price == 0.012
    assert offer.price_breaks[0].currency == "USD"
    assert offer.stock == 25000
    assert offer.lead_time_days is None
    token_url, token_body, _token_headers = http.requests[0]
    assert token_url == "https://api.digikey.com/v1/oauth2/token"
    assert b"client_secret=fixture-client-secret" in token_body
    _search_url, _search_body, search_headers = http.requests[1]
    assert search_headers["Authorization"] == "Bearer fixture-access-token"
    assert search_headers["X-DIGIKEY-Locale-Site"] == "CA"
    assert search_headers["X-DIGIKEY-Locale-Language"] == "fr"
    assert search_headers["X-DIGIKEY-Locale-Currency"] == "CAD"
    assert "fixture-access-token" not in offer.source_ref.model_dump_json()
    assert "fixture-client-secret" not in offer.source_ref.model_dump_json()


def test_digikey_search_runs_through_brokered_worker_with_fixtures() -> None:
    token_url = "https://api.digikey.com/v1/oauth2/token"
    search_url = "https://api.digikey.com/products/v4/search/keyword"
    token_response = HttpResponse(
        200,
        {"content-type": "application/json"},
        json.dumps(_fixture("digikey_oauth_response.json")).encode("utf-8"),
    )
    search_response = HttpResponse(
        200,
        {"content-type": "application/json"},
        json.dumps(_fixture("digikey_search_response.json")).encode("utf-8"),
    )
    http = HttpClient(
        {"api.digikey.com"},
        fixtures={
            ("POST", token_url): token_response,
            ("POST", search_url): search_response,
        },
    )
    plugin_dir = Path(__file__).parents[1] / "kiprod" / "plugins" / "suppliers" / "digikey"
    plugin = load_plugin(plugin_dir)

    offers = plugin.call(
        "search",
        "RC0603FR-074K7L",
        http=http,
        client_id="fixture-client-id",
        client_secret="fixture-client-secret",
    )

    assert offers[0]["supplier_part_number"] == "13-RC0603FR-074K7LCT-ND"
    assert "fixture-client-secret" not in json.dumps(offers)
    assert "fixture-access-token" not in json.dumps(offers)
