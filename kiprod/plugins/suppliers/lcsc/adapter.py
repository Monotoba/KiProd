from __future__ import annotations

import hashlib
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.net.http import HttpError

_SEARCH_URL = "https://ips.lcsc.com/rest/wmsc2agent/search/product"


def _signature(key: str, secret: str, nonce: str, timestamp: str) -> str:
    """Create the SHA-1 signature required by LCSC's published partner API."""
    material = f"key={key}&nonce={nonce}&secret={secret}&timestamp={timestamp}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _integer(value: object) -> int | None:
    normalized = re.sub(r"[, ]", "", str(value or ""))
    if not re.fullmatch(r"\d+", normalized):
        return None
    return int(normalized)


def _price(value: object) -> Decimal:
    normalized = re.sub(r"[^0-9eE.+-]", "", str(value))
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("price is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("price must be a finite non-negative amount")
    return amount


def _product_rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise ValueError("response must be an object")
    result = payload.get("result")
    if isinstance(result, list):
        rows: list[object] = result
    elif isinstance(result, dict):
        rows = []
        found = False
        for key in ("list", "productList", "dataList", "products"):
            value = result.get(key)
            if isinstance(value, list):
                rows = value
                found = True
                break
        if not found:
            raise ValueError("result does not contain a product list")
    else:
        raise ValueError("result must be a product list or object")
    return [row for row in rows if isinstance(row, dict)]


class LCSCAdapter:
    """Read-only adapter for LCSC's signed partner keyword-search API."""

    supplier_id = "com.kiprod.supplier.lcsc"

    def __init__(self, http: object) -> None:
        self.http = http

    def health_check(self) -> str:
        return "LCSC partner search adapter available; LCSC-issued API credentials are required."

    def search(
        self,
        mpn: str,
        *,
        api_key: str,
        api_secret: str,
        currency: str = "USD",
    ) -> list[Offer]:
        if not mpn.strip():
            raise ValueError("manufacturer part number must not be empty")
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("LCSC API key and secret must not be empty")
        currency = currency.strip().upper()
        if currency not in {"USD", "CNY", "EUR", "HKD"}:
            raise ValueError("LCSC currency must be USD, CNY, EUR, or HKD")

        nonce = secrets.token_hex(8)
        timestamp = str(int(time.time()))
        params = {
            "keyword": mpn.strip(),
            "match_type": "exact",
            "current_page": "1",
            "page_size": "30",
            "currency": currency,
            "key": api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "signature": _signature(api_key, api_secret, nonce, timestamp),
        }
        response = self.http.get(  # type: ignore[attr-defined]
            f"{_SEARCH_URL}?{urlencode(params)}",
            headers={"accept": "application/json"},
        )
        if response.status != 200:
            raise HttpError(f"LCSC Keyword Search returned HTTP {response.status}")
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("success") is False:
                raise HttpError("LCSC Keyword Search reported a search error")
            products = _product_rows(payload)
        except (TypeError, ValueError) as exc:
            raise HttpError("invalid LCSC Keyword Search response") from exc

        offers: list[Offer] = []
        for product in products:
            manufacturer_part_number = str(
                product.get("product_model") or product.get("mpn") or ""
            ).strip()
            if manufacturer_part_number.casefold() != mpn.strip().casefold():
                continue
            supplier_part_number = str(
                product.get("lcsc_part_number") or product.get("product_number") or ""
            ).strip()
            if not supplier_part_number:
                continue
            raw_breaks = product.get("product_price_list") or product.get("price_breaks")
            if not isinstance(raw_breaks, list):
                continue
            price_breaks: list[PriceBreak] = []
            for raw in raw_breaks:
                if not isinstance(raw, dict):
                    continue
                quantity = _integer(raw.get("ladder") or raw.get("quantity"))
                price_value = raw.get("discount_price", raw.get("usd_price", raw.get("price")))
                if quantity is None or quantity < 1 or price_value is None:
                    continue
                try:
                    unit_price = float(_price(price_value))
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
            offers.append(
                Offer(
                    supplier_id=self.supplier_id,
                    supplier_part_number=supplier_part_number,
                    manufacturer_part_number=manufacturer_part_number,
                    price_breaks=price_breaks,
                    stock=_integer(product.get("stock_number") or product.get("quantity")),
                    source_ref=SourceRef(path=_SEARCH_URL, reference=mpn.strip()),
                )
            )
        return offers
