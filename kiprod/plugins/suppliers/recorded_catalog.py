from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel

from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.net.http import HttpClient, HttpError


class CatalogItem(BaseModel):
    supplier_part_number: str
    manufacturer_part_number: str
    currency: str
    stock: int | None = None
    lead_time_days: int | None = None
    price_breaks: list[PriceBreak]


class RecordedCatalogAdapter:
    """Fixture-driven catalog adapter demonstrating the enforced HTTP boundary."""

    supplier_id = "com.example.fixture"

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def search(self, mpn: str) -> list[Offer]:
        url = f"https://parts.example.test/v1/search?mpn={quote(mpn, safe='')}"
        response = self.http.get(url, headers={"accept": "application/json"})
        if response.status != 200:
            raise HttpError(f"catalog returned HTTP {response.status}")
        try:
            payload = response.json()
            items = [CatalogItem.model_validate(item) for item in payload["items"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise HttpError(f"invalid catalog response for {mpn}") from exc
        return [
            Offer(
                supplier_id=self.supplier_id,
                supplier_part_number=item.supplier_part_number,
                manufacturer_part_number=item.manufacturer_part_number,
                price_breaks=item.price_breaks,
                stock=item.stock,
                lead_time_days=item.lead_time_days,
                source_ref=SourceRef(path="https://parts.example.test/v1/search", reference=mpn),
            )
            for item in items
        ]
