from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from kiprod.analysis.landed import LandedCost, LandedLine


class ComparisonWeights(BaseModel):
    price: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    lead_time: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    def normalized(self) -> tuple[float, float]:
        total = self.price + self.lead_time
        if total <= 0:
            raise ValueError("at least one comparison weight must be greater than zero")
        return self.price / total, self.lead_time / total


class ComparisonRow(BaseModel):
    supplier_id: str
    board_quantity: int
    currency: str
    total: str
    per_board: str
    parts_total: str = "0"
    shipping: str = "0"
    nre: str = "0"
    duty: str = "0"
    fees: str = "0"
    lead_time_days: int | None = None
    ranking_score: float = 0.0
    quoted_lines: int
    source_refs: list[str] = Field(default_factory=list)
    rank: int


class BestMixLine(BaseModel):
    manufacturer_part_number: str
    supplier_id: str
    supplier_part_number: str
    extended_price: str
    source_ref: str


class BestMix(BaseModel):
    board_quantity: int
    currency: str
    lines: list[BestMixLine] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    suppliers: list[str] = Field(default_factory=list)
    parts_total: str = "0"
    shipping: str = "0"
    nre: str = "0"
    duty: str = "0"
    fees: str = "0"
    total: str = "0"
    per_board: str = "0"


class Comparison(BaseModel):
    rows: list[ComparisonRow]
    coverage_gaps: list[str] = Field(default_factory=list)
    weights: ComparisonWeights = Field(default_factory=ComparisonWeights)
    best_mix: list[BestMix] = Field(default_factory=list)


def compare(
    costs: list[LandedCost],
    required_mpns: set[str] | None = None,
    weights: ComparisonWeights | None = None,
) -> Comparison:
    """Rank supplier costs using normalized price and lead-time weights."""
    weights = weights or ComparisonWeights()
    price_weight, lead_weight = weights.normalized()
    groups: dict[tuple[int, str], list[LandedCost]] = {}
    for cost in costs:
        groups.setdefault((cost.board_quantity, cost.currency), []).append(cost)
    rows: list[ComparisonRow] = []
    best_mixes: list[BestMix] = []
    for (_, _), group in sorted(groups.items()):
        prices = [float(cost.per_board) for cost in group]
        min_price, max_price = min(prices), max(prices)
        lead_values = [cost.lead_time_days for cost in group if cost.lead_time_days is not None]
        min_lead = min(lead_values) if lead_values else None
        max_lead = max(lead_values) if lead_values else None

        def score(cost: LandedCost) -> float:
            price_score = (
                (float(cost.per_board) - min_price) / (max_price - min_price)
                if max_price > min_price
                else 0.0
            )
            if min_lead is None or max_lead is None:
                lead_score = 0.0
            elif cost.lead_time_days is None:
                lead_score = 1.0
            elif max_lead > min_lead:
                lead_score = (cost.lead_time_days - min_lead) / (max_lead - min_lead)
            else:
                lead_score = 0.0
            effective_price_weight = price_weight
            effective_lead_weight = lead_weight if lead_values else 0.0
            denominator = effective_price_weight + effective_lead_weight
            if denominator == 0:
                return price_score
            return (
                price_score * effective_price_weight + lead_score * effective_lead_weight
            ) / denominator

        ranked = sorted(group, key=lambda cost: (score(cost), cost.per_board, cost.supplier_id))
        for rank, cost in enumerate(ranked, start=1):
            rows.append(
                ComparisonRow(
                    supplier_id=cost.supplier_id,
                    board_quantity=cost.board_quantity,
                    currency=cost.currency,
                    total=str(cost.total),
                    per_board=str(cost.per_board),
                    parts_total=str(cost.parts_total),
                    shipping=str(cost.shipping),
                    nre=str(cost.nre),
                    duty=str(cost.duty),
                    fees=str(cost.fees),
                    lead_time_days=cost.lead_time_days,
                    ranking_score=score(cost),
                    quoted_lines=len(cost.lines),
                    source_refs=sorted(
                        {
                            f"{line.source_ref.path}#{line.source_ref.reference or ''}"
                            for line in cost.lines
                        }
                    ),
                    rank=rank,
                )
            )
        requested = {mpn.casefold(): mpn for mpn in (required_mpns or set())}
        selected: dict[str, tuple[LandedCost, LandedLine]] = {}
        for folded, mpn in requested.items():
            candidates = [
                (cost, line)
                for cost in group
                for line in cost.lines
                if line.manufacturer_part_number.casefold() == folded
            ]
            if candidates:
                selected[folded] = min(
                    candidates,
                    key=lambda pair: (pair[1].extended_price, pair[0].supplier_id),
                )
        if selected or requested:
            mix_lines: list[BestMixLine] = []
            suppliers = sorted({cost.supplier_id for cost, _line in selected.values()})
            parts_total = sum(
                (line.extended_price for _cost, line in selected.values()), Decimal("0")
            )
            charges = {
                "shipping": Decimal("0"),
                "nre": Decimal("0"),
                "duty": Decimal("0"),
                "fees": Decimal("0"),
            }
            for folded, (_cost, line) in sorted(selected.items()):
                cost = _cost
                mix_lines.append(
                    BestMixLine(
                        manufacturer_part_number=requested[folded],
                        supplier_id=cost.supplier_id,
                        supplier_part_number=line.supplier_part_number,
                        extended_price=str(line.extended_price),
                        source_ref=f"{line.source_ref.path}#{line.source_ref.reference or ''}",
                    )
                )
            for supplier in suppliers:
                supplier_costs = [
                    cost for cost, _line in selected.values() if cost.supplier_id == supplier
                ]
                charge_source = min(
                    supplier_costs,
                    key=lambda cost: (
                        cost.shipping + cost.nre + cost.duty + cost.fees,
                        cost.total,
                    ),
                )
                for key in charges:
                    charges[key] += getattr(charge_source, key)
            gaps = sorted(
                (requested[folded] for folded in requested.keys() - selected.keys()),
                key=str.casefold,
            )
            total = parts_total + sum(charges.values(), Decimal("0"))
            mix = BestMix(
                board_quantity=group[0].board_quantity,
                currency=group[0].currency,
                lines=mix_lines,
                coverage_gaps=gaps,
                suppliers=suppliers,
                parts_total=str(parts_total),
                shipping=str(charges["shipping"]),
                nre=str(charges["nre"]),
                duty=str(charges["duty"]),
                fees=str(charges["fees"]),
                total=str(total),
                per_board=str(total / group[0].board_quantity),
            )
            best_mixes.append(mix)
    offered = {line.manufacturer_part_number.casefold() for cost in costs for line in cost.lines}
    gaps = sorted(
        (mpn for mpn in (required_mpns or set()) if mpn.casefold() not in offered),
        key=str.casefold,
    )
    return Comparison(rows=rows, coverage_gaps=gaps, weights=weights, best_mix=best_mixes)
