from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field, ValidationError

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.net.http import HttpError


class _PriceBreak(BaseModel):
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class _CatalogItem(BaseModel):
    supplier_part_number: str
    manufacturer_part_number: str
    currency: str
    price_breaks: list[_PriceBreak]
    stock: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)


class JsonCatalogAdapter:
    """Adapter for supplier JSON catalogs returning the KiProd catalog response shape.

    Search URL: ``<endpoint>?mpn=<URL-encoded MPN>``.
    Response: ``{"items": [{supplier_part_number, manufacturer_part_number,
    currency, price_breaks: [{quantity, unit_price}], stock?, lead_time_days?}]}``.
    The endpoint must be HTTPS and its host must be declared in the plugin manifest.
    """

    def __init__(self, http: object) -> None:
        self.http = http

    def search(
        self,
        mpn: str,
        *,
        endpoint: str,
        supplier_id: str,
        currency: str | None = None,
        bearer_token: str | None = None,
    ) -> list[Offer]:
        if not mpn.strip():
            raise ValueError("manufacturer part number must not be empty")
        if not supplier_id.strip():
            raise ValueError("supplier id must not be empty")
        parts = urlsplit(endpoint)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("catalog endpoint must be an HTTPS URL without embedded credentials")
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["mpn"] = mpn
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        headers = {"accept": "application/json"}
        if bearer_token:
            headers["authorization"] = f"Bearer {bearer_token}"
        response = self.http.get(url, headers=headers)  # type: ignore[attr-defined]
        if response.status != 200:
            raise HttpError(f"catalog returned HTTP {response.status}")
        try:
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ValueError("response must contain an items array")
            items = [_CatalogItem.model_validate(item) for item in payload["items"]]
        except (TypeError, ValueError, ValidationError) as exc:
            raise HttpError("invalid JSON catalog response") from exc
        normalized_currency = currency.upper() if currency else None
        offers: list[Offer] = []
        for item in items:
            if item.manufacturer_part_number.casefold() != mpn.casefold():
                continue
            item_currency = item.currency.upper()
            if normalized_currency and item_currency != normalized_currency:
                raise HttpError(
                    f"catalog currency mismatch for {item.supplier_part_number}: "
                    f"expected {normalized_currency}, received {item_currency}"
                )
            if len(item_currency) != 3 or not item_currency.isalpha():
                raise HttpError(f"invalid currency for {item.supplier_part_number}")
            if not item.price_breaks:
                raise HttpError(f"catalog item has no price breaks: {item.supplier_part_number}")
            if any(price.quantity <= 0 or price.unit_price < 0 for price in item.price_breaks):
                raise HttpError(f"invalid price break: {item.supplier_part_number}")
            if [price.quantity for price in item.price_breaks] != sorted(
                {price.quantity for price in item.price_breaks}
            ):
                raise HttpError(
                    "price breaks must have unique ascending quantities: "
                    f"{item.supplier_part_number}"
                )
            offers.append(
                Offer(
                    supplier_id=supplier_id,
                    supplier_part_number=item.supplier_part_number,
                    manufacturer_part_number=item.manufacturer_part_number,
                    price_breaks=[
                        PriceBreak(
                            quantity=price.quantity,
                            unit_price=price.unit_price,
                            currency=item_currency,
                        )
                        for price in item.price_breaks
                    ],
                    stock=item.stock,
                    lead_time_days=item.lead_time_days,
                    source_ref=SourceRef(path=urlunsplit(parts), reference=mpn),
                )
            )
        return offers
