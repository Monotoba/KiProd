import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from kiprod.net.http import HttpClient, HttpError, HttpResponse
from kiprod.plugins.host import load_plugin
from kiprod.plugins.suppliers.newark.adapter import NewarkAdapter


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    def json(self) -> object:
        return self._payload


class FakeHttp:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.url = ""

    def get(self, url: str, *, headers: dict[str, str]) -> FakeResponse:
        self.url = url
        assert headers == {"accept": "application/json"}
        return self.response


def _fixture() -> object:
    path = Path(__file__).parent / "fixtures" / "newark_search_response.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_newark_search_maps_only_exact_mpn_and_keeps_api_key_out_of_source() -> None:
    http = FakeHttp(FakeResponse(200, _fixture()))
    offers = NewarkAdapter(http).search(
        "RC0603FR-074K7L", api_key="fixture-api-key", store_id="www.newark.com"
    )

    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_id == "com.kiprod.supplier.newark"
    assert offer.supplier_part_number == "58K5022"
    assert offer.manufacturer_part_number == "RC0603FR-074K7L"
    assert [price.quantity for price in offer.price_breaks] == [1, 100]
    assert offer.price_breaks[0].unit_price == pytest.approx(0.012)
    assert offer.price_breaks[1].currency == "USD"
    assert offer.stock == 12500
    assert offer.lead_time_days is None
    params = parse_qs(urlsplit(http.url).query)
    assert params["term"] == ["manuPartNum:RC0603FR-074K7L"]
    assert params["storeInfo.id"] == ["www.newark.com"]
    assert params["resultsSettings.responseGroup"] == ["prices"]
    assert "fixture-api-key" not in offer.model_dump_json()


def test_newark_search_rejects_invalid_credentials_store_and_http_error() -> None:
    adapter = NewarkAdapter(FakeHttp(FakeResponse(401, {})))
    with pytest.raises(ValueError, match="API key"):
        adapter.search("MPN", api_key=" ")
    with pytest.raises(ValueError, match="currency"):
        adapter.search("MPN", api_key="fixture-key", currency="CAD")
    with pytest.raises(ValueError, match="regional store"):
        adapter.search("MPN", api_key="fixture-key", store_id="unknown.example")
    with pytest.raises(HttpError, match="HTTP 401") as error:
        adapter.search("MPN", api_key="fixture-key")
    assert "fixture-key" not in str(error.value)


def test_newark_search_runs_through_brokered_worker_fixture() -> None:
    from urllib.parse import urlencode

    params = {
        "term": "manuPartNum:RC0603FR-074K7L",
        "storeInfo.id": "www.newark.com",
        "callInfo.apiKey": "fixture-api-key",
        "callInfo.responseDataFormat": "JSON",
        "resultsSettings.offset": "0",
        "resultsSettings.numberOfResults": "20",
        "resultsSettings.responseGroup": "prices",
    }
    url = f"https://api.element14.com/catalog/products?{urlencode(params)}"
    response = HttpResponse(
        200, {"content-type": "application/json"}, json.dumps(_fixture()).encode()
    )
    http = HttpClient({"api.element14.com"}, fixtures={("GET", url): response})
    plugin_dir = Path(__file__).parents[1] / "kiprod" / "plugins" / "suppliers" / "newark"
    plugin = load_plugin(plugin_dir)

    offers = plugin.call("search", "RC0603FR-074K7L", http=http, api_key="fixture-api-key")

    assert offers[0]["supplier_part_number"] == "58K5022"
    assert offers[0]["stock"] == 12500
    assert "fixture-api-key" not in json.dumps(offers)
