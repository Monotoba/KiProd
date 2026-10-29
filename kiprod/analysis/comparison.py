from __future__ import annotations

from pydantic import BaseModel, Field

from kiprod.analysis.landed import LandedCost


class ComparisonRow(BaseModel):
    supplier_id: str
    board_quantity: int
    currency: str
    total: str
    per_board: str
    quoted_lines: int
    source_refs: list[str] = Field(default_factory=list)
    rank: int


class Comparison(BaseModel):
    rows: list[ComparisonRow]
    coverage_gaps: list[str] = Field(default_factory=list)


def compare(costs: list[LandedCost], required_mpns: set[str] | None = None) -> Comparison:
    """Rank comparable supplier totals by per-board cost, retaining evidence refs."""
    groups: dict[tuple[int, str], list[LandedCost]] = {}
    for cost in costs:
        groups.setdefault((cost.board_quantity, cost.currency), []).append(cost)
    rows: list[ComparisonRow] = []
    for (_, _), group in sorted(groups.items()):
        ranked = sorted(group, key=lambda cost: (cost.per_board, cost.supplier_id))
        for rank, cost in enumerate(ranked, start=1):
            rows.append(
                ComparisonRow(
                    supplier_id=cost.supplier_id,
                    board_quantity=cost.board_quantity,
                    currency=cost.currency,
                    total=str(cost.total),
                    per_board=str(cost.per_board),
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
    offered = {line.manufacturer_part_number.casefold() for cost in costs for line in cost.lines}
    gaps = sorted(
        (mpn for mpn in (required_mpns or set()) if mpn.casefold() not in offered),
        key=str.casefold,
    )
    return Comparison(rows=rows, coverage_gaps=gaps)
