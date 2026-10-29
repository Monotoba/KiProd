from __future__ import annotations

from decimal import Decimal

from kiprod.analysis.comparison import ComparisonWeights, compare
from kiprod.analysis.landed import calculate
from kiprod.core.models import Offer, PriceBreak, SourceRef


def _offer(supplier: str, unit: float, lead_time_days: int | None = None) -> Offer:
    return Offer(
        supplier_id=supplier,
        supplier_part_number=f"{supplier}-PN",
        manufacturer_part_number="MPN-A",
        lead_time_days=lead_time_days,
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
    expensive = calculate(
        [_offer("z-expensive", 0.2)],
        {"MPN-A": 10},
        10,
        shipping=Decimal("1.25"),
        nre=Decimal("2"),
        duty=Decimal("0.75"),
        fees=Decimal("0.50"),
    )
    cheaper = calculate([_offer("a-cheaper", 0.1)], {"MPN-A": 10}, 10)
    comparison = compare([expensive, cheaper], {"MPN-A", "MPN-B"})
    assert [row.supplier_id for row in comparison.rows] == ["a-cheaper", "z-expensive"]
    assert [row.rank for row in comparison.rows] == [1, 2]
    assert comparison.coverage_gaps == ["MPN-B"]
    expensive_row = next(row for row in comparison.rows if row.supplier_id == "z-expensive")
    assert expensive_row.parts_total == "2.0"
    assert expensive_row.shipping == "1.25"
    assert expensive_row.nre == "2"
    assert expensive_row.duty == "0.75"
    assert expensive_row.fees == "0.50"


def test_comparison_weights_can_prioritize_lead_time_and_keep_price_ties() -> None:
    slow_cheap = calculate([_offer("slow-cheap", 1.0, 40)], {"MPN-A": 10}, 10)
    fast_expensive = calculate([_offer("fast-expensive", 2.0, 5)], {"MPN-A": 10}, 10)
    comparison = compare(
        [slow_cheap, fast_expensive],
        weights=ComparisonWeights(price=0.2, lead_time=0.8),
    )
    assert [row.supplier_id for row in comparison.rows] == ["fast-expensive", "slow-cheap"]
    assert comparison.rows[0].lead_time_days == 5
    assert comparison.rows[0].ranking_score < comparison.rows[1].ranking_score
