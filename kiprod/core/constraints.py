"""Apply configured attribute policies to normalized BOM lines."""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel

from kiprod.core.defaults import Rule, resolve
from kiprod.core.models import BOMLine, NormalizedBOM, ResolvedField


class UnderConstrained(BaseModel):
    references: list[str]
    category: str
    attribute: str
    detail: str


def _category(references: list[str]) -> str:
    prefix = references[0].upper() if references else ""
    if prefix.startswith("U"):
        return "ic"
    if prefix.startswith("R"):
        return "resistor"
    if prefix.startswith("C"):
        return "capacitor"
    return "other"


def _current(line: BOMLine, attribute: str) -> str | None:
    return line.mpn if attribute == "mpn" else line.fields.get(attribute)


def apply(
    bom: NormalizedBOM, rules: dict[str, dict[str, Rule]], interactive: bool
) -> tuple[NormalizedBOM, list[UnderConstrained]]:
    findings: list[UnderConstrained] = []
    resolved_lines: list[BOMLine] = []
    for line in bom.lines:
        category = _category(line.references)
        resolved = dict(line.resolved_fields)
        for attribute, rule in rules.get(category, {}).items():
            current = _current(line, attribute)
            resolution = resolve(rule, current, interactive=interactive)
            if resolution.error:
                findings.append(
                    UnderConstrained(
                        references=line.references,
                        category=category,
                        attribute=attribute,
                        detail=resolution.error,
                    )
                )
            elif resolution.source != "schematic" and resolution.value is not None:
                resolved[attribute] = ResolvedField(
                    value=str(resolution.value), source=resolution.source
                )
        resolved_lines.append(line.model_copy(update={"resolved_fields": resolved}))
    return bom.model_copy(update={"lines": resolved_lines}), findings


def check(
    bom: NormalizedBOM, rules: dict[str, dict[str, Rule]], interactive: bool
) -> list[UnderConstrained]:
    """Compatibility wrapper for callers that only need violations."""
    _, findings = apply(bom, rules, interactive)
    return findings


def write(findings: list[UnderConstrained], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["references", "category", "attribute", "detail"]
        )
        writer.writeheader()
        for finding in findings:
            writer.writerow(
                {
                    "references": ", ".join(finding.references),
                    "category": finding.category,
                    "attribute": finding.attribute,
                    "detail": finding.detail,
                }
            )
    return path
