from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.net.http import HttpError

_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"


def _price(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("price is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("price must be a finite non-negative amount")
    return amount


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class DigiKeyAdapter:
    """Read-only DigiKey Product Information V4 search adapter."""

    supplier_id = "com.kiprod.supplier.digikey"

    def __init__(self, http: object) -> None:
        self.http = http

    def health_check(self) -> str:
        return "DigiKey Product Information V4 adapter available; an OAuth application is required."

    def search(
        self,
        mpn: str,
        *,
        client_id: str,
        client_secret: str,
        site: str = "US",
        language: str = "en",
        currency: str = "USD",
    ) -> list[Offer]:
        if not mpn.strip():
            raise ValueError("manufacturer part number must not be empty")
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("DigiKey OAuth client ID and secret must not be empty")
        if not site.strip() or not language.strip() or len(currency.strip()) != 3:
            raise ValueError("DigiKey site, language, or currency setting is invalid")

        token_response = self.http.post(  # type: ignore[attr-defined]
            _TOKEN_URL,
            urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                }
            ).encode("utf-8"),
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        if token_response.status != 200:
            raise HttpError(f"DigiKey OAuth returned HTTP {token_response.status}")
        try:
            token_payload = token_response.json()
            access_token = token_payload["access_token"]
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("access token must be a non-empty string")
        except (KeyError, TypeError, ValueError) as exc:
            raise HttpError("invalid DigiKey OAuth response") from exc

        search_body = json.dumps({"Keywords": mpn, "Limit": 50, "Offset": 0}).encode("utf-8")
        search_response = self.http.post(  # type: ignore[attr-defined]
            _SEARCH_URL,
            search_body,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "Authorization": f"Bearer {access_token}",
                "X-DIGIKEY-Client-Id": client_id,
                "X-DIGIKEY-Locale-Site": site,
                "X-DIGIKEY-Locale-Language": language,
                "X-DIGIKEY-Locale-Currency": currency.upper(),
            },
        )
        if search_response.status != 200:
            raise HttpError(f"DigiKey Product Search returned HTTP {search_response.status}")
        try:
            payload = search_response.json()
            products = payload.get("ExactMatches", [])
            if not isinstance(products, list):
                raise ValueError("ExactMatches must be an array")
            search_locale = payload.get("SearchLocaleUsed", {})
            result_currency = str(search_locale.get("Currency", currency)).upper()
            if len(result_currency) != 3 or not result_currency.isalpha():
                raise ValueError("invalid currency in response")
        except (AttributeError, TypeError, ValueError) as exc:
            raise HttpError("invalid DigiKey Product Search response") from exc

        offers: list[Offer] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            manufacturer_part_number = str(product.get("ManufacturerProductNumber") or "").strip()
            if manufacturer_part_number.casefold() != mpn.strip().casefold():
                continue
            variations = product.get("ProductVariations")
            if not isinstance(variations, list):
                continue
            for variation in variations:
                if not isinstance(variation, dict):
                    continue
                supplier_part_number = str(variation.get("DigiKeyProductNumber") or "").strip()
                raw_prices = variation.get("StandardPricing")
                if not supplier_part_number or not isinstance(raw_prices, list):
                    continue
                price_breaks: list[PriceBreak] = []
                for raw_price in raw_prices:
                    if not isinstance(raw_price, dict):
                        continue
                    quantity = _integer(raw_price.get("BreakQuantity"))
                    if quantity is None or quantity < 1:
                        continue
                    try:
                        unit_price = float(_price(raw_price.get("UnitPrice")))
                    except ValueError:
                        continue
                    price_breaks.append(
                        PriceBreak(
                            quantity=quantity, unit_price=unit_price, currency=result_currency
                        )
                    )
                price_breaks.sort(key=lambda price: price.quantity)
                if not price_breaks or len({price.quantity for price in price_breaks}) != len(
                    price_breaks
                ):
                    continue
                offers.append(
                    Offer(
                        supplier_id=self.supplier_id,
                        supplier_part_number=supplier_part_number,
                        manufacturer_part_number=manufacturer_part_number,
                        price_breaks=price_breaks,
                        stock=_integer(variation.get("QuantityAvailableforPackageType")),
                        source_ref=SourceRef(path=_SEARCH_URL, reference=mpn.strip()),
                    )
                )
        return offers
