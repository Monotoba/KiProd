from __future__ import annotations

from kiprod.analysis.comparison import Comparison
from kiprod.analysis.landed import LandedCost


def comparison_markdown(comparison: Comparison) -> str:
    lines = [
        "# Supplier comparison",
        "",
        f"Ranked using price weight {comparison.weights.price:g} and lead-time weight "
        f"{comparison.weights.lead_time:g} within each quantity and currency. "
        "Lower score is better.",
        "",
        "| Rank | Supplier | Boards | Currency | Parts | Shipping | NRE | Duty | Fees | Total "
        "| Per board | Lead days | Score | Lines |",
        "|---:|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison.rows:
        lines.append(
            f"| {row.rank} | {row.supplier_id} | {row.board_quantity} | {row.currency} "
            f"| {row.parts_total} | {row.shipping} | {row.nre} | {row.duty} | {row.fees} "
            f"| {row.total} | {row.per_board} "
            f"| {row.lead_time_days if row.lead_time_days is not None else 'unknown'} "
            f"| {row.ranking_score:.3f} | {row.quoted_lines} |"
        )
    lines.extend(["", "## Evidence", ""])
    for row in comparison.rows:
        lines.append(f"### {row.supplier_id} · quantity {row.board_quantity} {row.currency}")
        lines.extend([""] + [f"- `{source}`" for source in row.source_refs] + [""])
    lines.extend(["## Coverage gaps", ""])
    lines.extend([f"- {mpn}" for mpn in comparison.coverage_gaps] or ["None identified."])
    return "\n".join(lines).rstrip() + "\n"


def landed_markdown(cost: LandedCost) -> str:
    lines = [
        f"# Landed cost: {cost.supplier_id}",
        "",
        f"Board quantity: {cost.board_quantity}",
        f"Currency: {cost.currency}",
        "",
        "| MPN | Supplier P/N | Required | Buy | Unit price | Extended | Source |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in cost.lines:
        source = f"{item.source_ref.path}#{item.source_ref.reference or ''}"
        lines.append(
            f"| {item.manufacturer_part_number} | {item.supplier_part_number} "
            f"| {item.required_quantity} | {item.buy_quantity} | {item.unit_price} "
            f"| {item.extended_price} | `{source}` |"
        )
    lines.extend(
        [
            "",
            f"Parts: {cost.parts_total} {cost.currency}",
            f"Shipping: {cost.shipping} {cost.currency}",
            f"NRE: {cost.nre} {cost.currency}",
            f"Duty: {cost.duty} {cost.currency}",
            f"Fees: {cost.fees} {cost.currency}",
            f"Total: {cost.total} {cost.currency}",
            f"Per board: {cost.per_board} {cost.currency}",
            "",
        ]
    )
    return "\n".join(lines)
