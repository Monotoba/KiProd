import json
from pathlib import Path
from typing import Any

import pytest

from kiprod.net.http import HttpClient, HttpError, HttpResponse
from kiprod.plugins.host import load_plugin
from kiprod.plugins.suppliers.mouser.adapter import MouserAdapter


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeHttp:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.url = ""
        self.body = b""

    def post(self, url: str, body: bytes, *, headers: dict[str, str]) -> FakeResponse:
        self.url = url
        self.body = body
        assert headers["accept"] == "application/json"
        assert headers["content-type"] == "application/json"
        return self.response


def test_mouser_search_maps_only_exact_mpn_and_redacts_key_from_source() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "mouser_search_response.json").read_text(
            encoding="utf-8"
        )
    )
    http = FakeHttp(FakeResponse(200, fixture))
    adapter = MouserAdapter(http)

    offers = adapter.search("RC0603FR-074K7L", api_key="fixture-secret")

    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_id == "com.kiprod.supplier.mouser"
    assert offer.supplier_part_number == "603-RC0603FR-074K7L"
    assert offer.manufacturer_part_number == "RC0603FR-074K7L"
    assert [item.quantity for item in offer.price_breaks] == [1, 100]
    assert offer.price_breaks[0].unit_price == pytest.approx(0.012)
    assert offer.price_breaks[0].currency == "USD"
    assert offer.stock == 12500
    assert offer.lead_time_days == 21
    assert "apiKey=fixture-secret" in http.url
    assert json.loads(http.body)["SearchByKeywordMfrNameRequest"]["keyword"] == (
        "RC0603FR-074K7L"
    )
    assert offer.source_ref.path == "https://api.mouser.com/api/v2/search/keywordandmanufacturer"
    assert "fixture-secret" not in offer.source_ref.model_dump_json()


def test_mouser_search_rejects_empty_key_and_sanitizes_http_errors() -> None:
    http = FakeHttp(FakeResponse(401, {}))
    adapter = MouserAdapter(http)

    with pytest.raises(ValueError, match="API key"):
        adapter.search("MPN-1", api_key=" ")
    with pytest.raises(HttpError, match="HTTP 401") as error:
        adapter.search("MPN-1", api_key="fixture-secret")
    assert "fixture-secret" not in str(error.value)


def test_mouser_search_runs_through_brokered_worker_with_recorded_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "mouser_search_response.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    api_url = (
        "https://api.mouser.com/api/v2/search/keywordandmanufacturer"
        "?apiKey=fixture-secret"
    )
    response = HttpResponse(200, {"content-type": "application/json"}, json.dumps(fixture).encode())
    http = HttpClient({"api.mouser.com"}, fixtures={("POST", api_url): response})
    plugin_dir = Path(__file__).parents[1] / "kiprod" / "plugins" / "suppliers" / "mouser"
    plugin = load_plugin(plugin_dir)

    offers = plugin.call("search", "RC0603FR-074K7L", http=http, api_key="fixture-secret")

    assert offers[0]["supplier_part_number"] == "603-RC0603FR-074K7L"
    assert offers[0]["price_breaks"][1]["quantity"] == 100
    assert offers[0]["source_ref"]["path"] == (
        "https://api.mouser.com/api/v2/search/keywordandmanufacturer"
    )
    assert "fixture-secret" not in json.dumps(offers)
