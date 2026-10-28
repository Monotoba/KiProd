"""Apply configured attribute policies to normalized BOM lines."""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel

from kiprod.core.defaults import Rule, resolve
from kiprod.core.models import NormalizedBOM


class UnderConstrained(BaseModel):
    references: list[str]
    category: str
    attribute: str
    detail: str


def _category(references: list[str]) -> str:
    return "ic" if any(reference.upper().startswith("U") for reference in references) else "other"


def check(
    bom: NormalizedBOM, rules: dict[str, dict[str, Rule]], interactive: bool
) -> list[UnderConstrained]:
    findings: list[UnderConstrained] = []
    for line in bom.lines:
        category = _category(line.references)
        for attribute, rule in rules.get(category, {}).items():
            current = getattr(line, attribute, None)
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
