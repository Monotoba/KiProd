import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from kiprod.net.http import HttpError
from kiprod.plugins.suppliers.lcsc.adapter import LCSCAdapter, _signature


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
    path = Path(__file__).parent / "fixtures" / "lcsc_search_response.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_lcsc_signature_matches_published_sha1_scheme() -> None:
    assert (
        _signature(
            "7dc6035da7874b5b9bc245bd28017290",
            "eiru73y343r36fdi",
            "63yeike7dy6c2kjd",
            "1524662065",
        )
        == hashlib.sha1(
            b"key=7dc6035da7874b5b9bc245bd28017290&nonce=63yeike7dy6c2kjd&"
            b"secret=eiru73y343r36fdi&timestamp=1524662065"
        ).hexdigest()
    )


def test_search_maps_only_exact_mpn_and_signs_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kiprod.plugins.suppliers.lcsc.adapter.secrets.token_hex", lambda _: "a" * 16
    )
    monkeypatch.setattr("kiprod.plugins.suppliers.lcsc.adapter.time.time", lambda: 1_700_000_000)
    http = FakeHttp(FakeResponse(200, _fixture()))
    offers = LCSCAdapter(http).search(
        "RC0603FR-074K7L", api_key="fixture-key", api_secret="fixture-secret"
    )

    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_id == "com.kiprod.supplier.lcsc"
    assert offer.supplier_part_number == "C25804"
    assert offer.manufacturer_part_number == "RC0603FR-074K7L"
    assert [item.quantity for item in offer.price_breaks] == [1, 100]
    assert offer.price_breaks[0].unit_price == pytest.approx(0.012)
    assert offer.stock == 12500
    assert offer.source_ref.path == "https://ips.lcsc.com/rest/wmsc2agent/search/product"
    params = parse_qs(urlsplit(http.url).query)
    assert params["keyword"] == ["RC0603FR-074K7L"]
    assert params["match_type"] == ["exact"]
    assert params["page_size"] == ["30"]
    assert params["signature"] == [
        _signature("fixture-key", "fixture-secret", "a" * 16, "1700000000")
    ]
    assert "fixture-secret" not in offer.model_dump_json()


def test_search_validates_credentials_currency_and_api_errors() -> None:
    adapter = LCSCAdapter(FakeHttp(FakeResponse(401, {})))
    with pytest.raises(ValueError, match="key and secret"):
        adapter.search("MPN", api_key="key", api_secret=" ")
    with pytest.raises(ValueError, match="currency"):
        adapter.search("MPN", api_key="key", api_secret="secret", currency="CAD")
    with pytest.raises(HttpError, match="HTTP 401"):
        adapter.search("MPN", api_key="fixture-key", api_secret="fixture-secret")


def test_search_rejects_malformed_response() -> None:
    adapter = LCSCAdapter(FakeHttp(FakeResponse(200, {"success": True, "result": {}})))
    with pytest.raises(HttpError, match="invalid LCSC"):
        adapter.search("MPN", api_key="key", api_secret="secret")
