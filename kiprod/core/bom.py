from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

from kiprod.core.models import BOMLine, NormalizedBOM, Part, Project, SourceRef
from kiprod.kicad.sexpr import SExpr, atom, children, head, load, walk


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"yes", "true", "1"}


def _fields(symbol: list[SExpr]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for prop in children(symbol, "property"):
        key, value = atom(prop, 1), atom(prop, 2)
        if key is not None and value is not None:
            fields[key] = value
    return fields


def _part(symbol: list[SExpr], source_path: Path, root: Path) -> Part | None:
    fields = _fields(symbol)
    reference = fields.get("Reference")
    if not reference or reference.startswith("#"):
        return None
    in_bom_nodes = children(symbol, "in_bom")
    in_bom = atom(in_bom_nodes[0], 1) if in_bom_nodes else "yes"
    dnp = fields.get("DNP") or fields.get("dnp")
    if not _truthy(in_bom) or _truthy(dnp):
        return None
    mpn = fields.get("MPN") or fields.get("Manufacturer Part Number") or None
    return Part(
        reference=reference,
        value=fields.get("Value", ""),
        footprint=fields.get("Footprint", ""),
        mpn=mpn,
        fields=fields,
        source=SourceRef(path=str(source_path.relative_to(root)), reference=reference),
    )


def _references(value: str) -> list[str]:
    candidates = value.replace(";", ",").split(",")
    return [reference.strip() for reference in candidates if reference.strip()]


def _imported_fields(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Read common KiCad CSV headings into a reference-indexed field mapping."""
    parts: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            normalized = {
                (key or "").strip().casefold(): (value or "").strip() for key, value in row.items()
            }
            references = (
                normalized.get("reference")
                or normalized.get("references")
                or normalized.get("refs")
            )
            if not references:
                continue
            for reference in _references(references):
                parts[reference] = normalized
    return parts, set(parts)


def _merge_imported(part: Part, fields: dict[str, str]) -> Part:
    mpn = part.mpn or fields.get("mpn") or fields.get("manufacturer part number") or None
    merged = dict(part.fields)
    for key, value in fields.items():
        if value and key not in {"reference", "references", "refs", "quantity", "qty"}:
            merged.setdefault(key, value)
    return part.model_copy(update={"mpn": mpn, "fields": merged, "source": part.source})


def read_parts(project: Project, existing_bom: Path | None = None) -> list[Part]:
    parts: list[Part] = []
    for schematic in project.schematics:
        for node in walk(load(schematic)):
            if head(node) == "symbol" and children(node, "lib_id"):
                part = _part(node, schematic, project.root)
                if part is not None:
                    parts.append(part)
    if existing_bom is None:
        return sorted(parts, key=lambda item: item.reference)
    imported, _ = _imported_fields(existing_bom)
    return sorted(
        (
            _merge_imported(part, imported[part.reference]) if part.reference in imported else part
            for part in parts
        ),
        key=lambda item: item.reference,
    )


def _group_key(part: Part) -> tuple[str, ...]:
    if part.mpn:
        return ("mpn", part.mpn.casefold())
    return ("design", part.value, part.footprint)


def build(project: Project, existing_bom: Path | None = None) -> NormalizedBOM:
    groups: dict[tuple[str, ...], list[Part]] = defaultdict(list)
    for part in read_parts(project, existing_bom):
        groups[_group_key(part)].append(part)
    lines: list[BOMLine] = []
    for key, parts in sorted(groups.items()):
        exemplar = parts[0]
        token = "|".join(key).encode()
        lines.append(
            BOMLine(
                line_id=hashlib.sha256(token).hexdigest()[:12],
                references=[part.reference for part in parts],
                quantity=len(parts),
                value=exemplar.value,
                footprint=exemplar.footprint,
                mpn=exemplar.mpn,
                fields=exemplar.fields,
                sources=[part.source for part in parts],
            )
        )
    return NormalizedBOM(
        project=project.pro_file.stem,
        input_hashes=project.input_hashes,
        lines=lines,
        imported_bom=str(existing_bom) if existing_bom else None,
    )
