from __future__ import annotations

from decimal import Decimal

from kiprod.analysis.comparison import compare
from kiprod.analysis.landed import calculate
from kiprod.core.models import Offer, PriceBreak, SourceRef


def _offer(supplier: str, unit: float) -> Offer:
    return Offer(
        supplier_id=supplier,
        supplier_part_number=f"{supplier}-PN",
        manufacturer_part_number="MPN-A",
        price_breaks=[
            PriceBreak(quantity=1, unit_price=unit, currency="USD"),
            PriceBreak(quantity=100, unit_price=unit / 2, currency="USD"),
        ],
        source_ref=SourceRef(path=f"https://{supplier}.test/quote", reference="MPN-A"),
    )


def test_landed_cost_selects_price_break_and_rounds_moq_and_multiple() -> None:
    cost = calculate(
        [_offer("cheap", 0.1)],
        {"MPN-A": 81},
        board_quantity=10,
        attrition=Decimal("0.1"),
        moqs={"cheap-PN": 50},
        multiples={"cheap-PN": 25},
        shipping=Decimal("3"),
    )
    assert cost.lines[0].required_quantity == 90
    assert cost.lines[0].buy_quantity == 100
    assert cost.lines[0].unit_price == Decimal("0.05")
    assert cost.parts_total == Decimal("5.00")
    assert cost.total == Decimal("8.00")
    assert cost.lines[0].source_ref.path == "https://cheap.test/quote"


def test_comparison_ranks_per_board_and_finds_coverage_gaps() -> None:
    expensive = calculate([_offer("z-expensive", 0.2)], {"MPN-A": 10}, 10)
    cheaper = calculate([_offer("a-cheaper", 0.1)], {"MPN-A": 10}, 10)
    comparison = compare([expensive, cheaper], {"MPN-A", "MPN-B"})
    assert [row.supplier_id for row in comparison.rows] == ["a-cheaper", "z-expensive"]
    assert [row.rank for row in comparison.rows] == [1, 2]
    assert comparison.coverage_gaps == ["MPN-B"]
