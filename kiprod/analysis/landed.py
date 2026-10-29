from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from pydantic import BaseModel, Field

from kiprod.core.models import Offer, PriceBreak, SourceRef


class LandedLine(BaseModel):
    manufacturer_part_number: str
    supplier_part_number: str
    required_quantity: int
    buy_quantity: int
    unit_price: Decimal
    extended_price: Decimal
    currency: str
    source_ref: SourceRef


class LandedCost(BaseModel):
    supplier_id: str
    board_quantity: int
    currency: str
    parts_total: Decimal
    shipping: Decimal = Decimal("0")
    nre: Decimal = Decimal("0")
    duty: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    total: Decimal
    per_board: Decimal
    lines: list[LandedLine] = Field(default_factory=list)


def _buy_quantity(required: int, moq: int, multiple: int) -> int:
    if required <= 0 or moq <= 0 or multiple <= 0:
        raise ValueError("required quantity, MOQ, and order multiple must be positive")
    minimum = max(required, moq)
    return (
        int((Decimal(minimum) / Decimal(multiple)).to_integral_value(rounding=ROUND_CEILING))
        * multiple
    )


def _price_break(breaks: list[PriceBreak], quantity: int) -> PriceBreak:
    if not breaks:
        raise ValueError("offer has no price breaks")
    eligible = [price_break for price_break in breaks if price_break.quantity <= quantity]
    if not eligible:
        raise ValueError("offer has no price break at or below the buy quantity")
    return max(eligible, key=lambda price_break: price_break.quantity)


def calculate(
    offers: list[Offer],
    required_quantities: dict[str, int],
    board_quantity: int,
    *,
    attrition: Decimal = Decimal("0"),
    moqs: dict[str, int] | None = None,
    multiples: dict[str, int] | None = None,
    shipping: Decimal = Decimal("0"),
    nre: Decimal = Decimal("0"),
    duty: Decimal = Decimal("0"),
    fees: Decimal = Decimal("0"),
) -> LandedCost:
    if board_quantity <= 0 or attrition < 0:
        raise ValueError("board quantity must be positive and attrition cannot be negative")
    if not offers:
        raise ValueError("at least one source-backed offer is required")
    currencies = {price.currency for offer in offers for price in offer.price_breaks}
    if len(currencies) != 1:
        raise ValueError("all offers must use one currency; convert currencies before analysis")
    lines: list[LandedLine] = []
    for offer in offers:
        required = required_quantities.get(offer.manufacturer_part_number)
        if required is None:
            continue
        needed = int(
            (Decimal(required) * (Decimal("1") + attrition)).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        buy = _buy_quantity(
            needed,
            (moqs or {}).get(offer.supplier_part_number, 1),
            (multiples or {}).get(offer.supplier_part_number, 1),
        )
        price = _price_break(offer.price_breaks, buy)
        unit = Decimal(str(price.unit_price))
        lines.append(
            LandedLine(
                manufacturer_part_number=offer.manufacturer_part_number,
                supplier_part_number=offer.supplier_part_number,
                required_quantity=needed,
                buy_quantity=buy,
                unit_price=unit,
                extended_price=unit * buy,
                currency=price.currency,
                source_ref=offer.source_ref,
            )
        )
    if not lines:
        raise ValueError("no offers matched the requested manufacturer part numbers")
    parts_total = sum((line.extended_price for line in lines), Decimal("0"))
    total = parts_total + shipping + nre + duty + fees
    currency = next(iter(currencies))
    return LandedCost(
        supplier_id=offers[0].supplier_id,
        board_quantity=board_quantity,
        currency=currency,
        parts_total=parts_total,
        shipping=shipping,
        nre=nre,
        duty=duty,
        fees=fees,
        total=total,
        per_board=total / board_quantity,
        lines=lines,
    )
