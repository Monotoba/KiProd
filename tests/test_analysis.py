from __future__ import annotations

from decimal import Decimal

from kiprod.analysis.comparison import ComparisonWeights, compare
from kiprod.analysis.landed import calculate
from kiprod.core.models import Offer, PriceBreak, SourceRef


def _offer(
    supplier: str,
    unit: float,
    lead_time_days: int | None = None,
    mpn: str = "MPN-A",
) -> Offer:
    return Offer(
        supplier_id=supplier,
        supplier_part_number=f"{supplier}-PN",
        manufacturer_part_number=mpn,
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
    best_mix = comparison.best_mix[0]
    assert best_mix.lines[0].supplier_id == "a-cheaper"
    assert best_mix.coverage_gaps == ["MPN-B"]


def test_best_mix_selects_lowest_source_per_mpn_and_counts_supplier_charges_once() -> None:
    supplier_a = calculate(
        [_offer("supplier-a", 1.0), _offer("supplier-a", 10.0, mpn="MPN-B")],
        {"MPN-A": 1, "MPN-B": 1},
        1,
        shipping=Decimal("2"),
    )
    supplier_b_first = _offer("supplier-b", 9.0, mpn="MPN-A")
    supplier_b_second = _offer("supplier-b", 1.0, mpn="MPN-B")
    supplier_b = calculate(
        [supplier_b_first, supplier_b_second],
        {"MPN-A": 1, "MPN-B": 1},
        1,
        shipping=Decimal("3"),
    )
    comparison = compare([supplier_a, supplier_b], {"MPN-A", "MPN-B"})
    mix = comparison.best_mix[0]
    assert [(line.manufacturer_part_number, line.supplier_id) for line in mix.lines] == [
        ("MPN-A", "supplier-a"),
        ("MPN-B", "supplier-b"),
    ]
    assert mix.parts_total == "2.0"
    assert mix.shipping == "5"
    assert mix.total == "7.0"
    assert mix.suppliers == ["supplier-a", "supplier-b"]


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
