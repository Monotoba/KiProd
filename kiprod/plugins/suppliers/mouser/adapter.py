from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.net.http import HttpError

_SEARCH_URL = "https://api.mouser.com/api/v2/search/keywordandmanufacturer"


def _price(value: object) -> Decimal:
    normalized = re.sub(r"[^0-9eE.+-]", "", str(value)).replace(",", "")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("price is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("price must be a finite non-negative amount")
    return amount


def _nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    normalized = str(value).strip().replace(",", "")
    if not re.fullmatch(r"\d+", normalized):
        return None
    return int(normalized)


def _lead_time_days(value: object) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s+days?\s*", str(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


class MouserAdapter:
    """Read-only adapter for Mouser's documented Search API."""

    supplier_id = "com.kiprod.supplier.mouser"

    def __init__(self, http: object) -> None:
        self.http = http

    def health_check(self) -> str:
        return "Mouser Search API adapter available; an approved API key is required to search."

    def search(self, mpn: str, *, api_key: str) -> list[Offer]:
        if not mpn.strip():
            raise ValueError("manufacturer part number must not be empty")
        if not api_key.strip():
            raise ValueError("Mouser Search API key must not be empty")

        url = f"{_SEARCH_URL}?{urlencode({'apiKey': api_key})}"
        request = {
            "SearchByKeywordMfrNameRequest": {
                "keyword": mpn,
                "records": 50,
                "pageNumber": 1,
                "searchOptions": "None",
            }
        }
        response = self.http.post(  # type: ignore[attr-defined]
            url,
            json.dumps(request).encode("utf-8"),
            headers={"accept": "application/json", "content-type": "application/json"},
        )
        if response.status != 200:
            raise HttpError(f"Mouser Search API returned HTTP {response.status}")
        try:
            payload = response.json()
            if payload.get("Errors"):
                raise HttpError("Mouser Search API reported a search error")
            parts = payload["SearchResults"]["Parts"]
            if not isinstance(parts, list):
                raise ValueError("Parts must be an array")
        except (KeyError, TypeError, ValueError) as exc:
            raise HttpError("invalid Mouser Search API response") from exc

        offers: list[Offer] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            manufacturer_part_number = str(part.get("ManufacturerPartNumber") or "").strip()
            if manufacturer_part_number.casefold() != mpn.strip().casefold():
                continue
            supplier_part_number = str(part.get("MouserPartNumber") or "").strip()
            if not supplier_part_number:
                continue
            breaks = part.get("PriceBreaks")
            if not isinstance(breaks, list):
                continue
            prices: list[PriceBreak] = []
            for item in breaks:
                if not isinstance(item, dict):
                    continue
                quantity = _nonnegative_int(item.get("Quantity"))
                currency = str(item.get("Currency") or "").strip().upper()
                if quantity is None or quantity < 1 or len(currency) != 3 or not currency.isalpha():
                    continue
                try:
                    amount = float(_price(item.get("Price", "")))
                except ValueError:
                    continue
                prices.append(PriceBreak(quantity=quantity, unit_price=amount, currency=currency))
            prices.sort(key=lambda price: price.quantity)
            if not prices or len({price.quantity for price in prices}) != len(prices):
                continue
            offers.append(
                Offer(
                    supplier_id=self.supplier_id,
                    supplier_part_number=supplier_part_number,
                    manufacturer_part_number=manufacturer_part_number,
                    price_breaks=prices,
                    stock=_nonnegative_int(part.get("AvailabilityInStock")),
                    lead_time_days=_lead_time_days(part.get("LeadTime")),
                    source_ref=SourceRef(path=_SEARCH_URL, reference=mpn.strip()),
                )
            )
        return offers
