from __future__ import annotations

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


def read_parts(project: Project) -> list[Part]:
    parts: list[Part] = []
    for schematic in project.schematics:
        for node in walk(load(schematic)):
            if head(node) == "symbol" and children(node, "lib_id"):
                part = _part(node, schematic, project.root)
                if part is not None:
                    parts.append(part)
    return sorted(parts, key=lambda item: item.reference)


def _group_key(part: Part) -> tuple[str, ...]:
    if part.mpn:
        return ("mpn", part.mpn.casefold())
    return ("design", part.value, part.footprint)


def build(project: Project) -> NormalizedBOM:
    groups: dict[tuple[str, ...], list[Part]] = defaultdict(list)
    for part in read_parts(project):
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
    return NormalizedBOM(project=project.pro_file.stem, input_hashes=project.input_hashes, lines=lines)
