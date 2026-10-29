from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.net.http import HttpError

_SEARCH_URL = "https://api.element14.com/catalog/products"
_STORE_CURRENCIES = {
    "www.newark.com": "USD",
    "canada.newark.com": "CAD",
    "mexico.newark.com": "MXN",
}


def _integer(value: object) -> int | None:
    normalized = str(value or "").replace(",", "").strip()
    return int(normalized) if re.fullmatch(r"\d+", normalized) else None


def _price(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("price is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("price must be a finite non-negative amount")
    return amount


class NewarkAdapter:
    """Read-only Newark/element14 Product Search API adapter."""

    supplier_id = "com.kiprod.supplier.newark"

    def __init__(self, http: object) -> None:
        self.http = http

    def health_check(self) -> str:
        return "Newark Product Search adapter available; an approved API key is required."

    def search(
        self,
        mpn: str,
        *,
        api_key: str,
        store_id: str = "www.newark.com",
        currency: str = "USD",
    ) -> list[Offer]:
        if not mpn.strip():
            raise ValueError("manufacturer part number must not be empty")
        if not api_key.strip():
            raise ValueError("Newark API key must not be empty")
        if store_id not in _STORE_CURRENCIES:
            raise ValueError("unsupported Newark regional store")
        currency = currency.strip().upper()
        if currency != _STORE_CURRENCIES[store_id]:
            raise ValueError("currency does not match the selected Newark store")

        params = {
            "term": f"manuPartNum:{mpn.strip()}",
            "storeInfo.id": store_id,
            "callInfo.apiKey": api_key,
            "callInfo.responseDataFormat": "JSON",
            "resultsSettings.offset": "0",
            "resultsSettings.numberOfResults": "20",
            "resultsSettings.responseGroup": "prices",
        }
        response = self.http.get(  # type: ignore[attr-defined]
            f"{_SEARCH_URL}?{urlencode(params)}",
            headers={"accept": "application/json"},
        )
        if response.status != 200:
            raise HttpError(f"Newark Product Search returned HTTP {response.status}")
        try:
            payload = response.json()
            result = payload["keywordSearchReturn"]
            products = result.get("products", [])
            if not isinstance(products, list):
                raise ValueError("products must be an array")
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise HttpError("invalid Newark Product Search response") from exc

        offers: list[Offer] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            manufacturer_part_number = str(
                product.get("translatedManufacturerPartNumber") or ""
            ).strip()
            if manufacturer_part_number.casefold() != mpn.strip().casefold():
                continue
            supplier_part_number = str(product.get("sku") or "").strip()
            raw_prices = product.get("prices")
            if not supplier_part_number or not isinstance(raw_prices, list):
                continue
            price_breaks: list[PriceBreak] = []
            for raw_price in raw_prices:
                if not isinstance(raw_price, dict):
                    continue
                quantity = _integer(raw_price.get("from"))
                if quantity is None or quantity < 1 or raw_price.get("cost") is None:
                    continue
                try:
                    unit_price = float(_price(raw_price["cost"]))
                except ValueError:
                    continue
                price_breaks.append(
                    PriceBreak(quantity=quantity, unit_price=unit_price, currency=currency)
                )
            price_breaks.sort(key=lambda item: item.quantity)
            if not price_breaks or len({item.quantity for item in price_breaks}) != len(
                price_breaks
            ):
                continue
            stock = product.get("inv")
            if stock is None and isinstance(product.get("stock"), dict):
                stock = product["stock"].get("level")
            offers.append(
                Offer(
                    supplier_id=self.supplier_id,
                    supplier_part_number=supplier_part_number,
                    manufacturer_part_number=manufacturer_part_number,
                    price_breaks=price_breaks,
                    stock=_integer(stock),
                    source_ref=SourceRef(path=_SEARCH_URL, reference=mpn.strip()),
                )
            )
        return offers
