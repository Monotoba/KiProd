from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kiprod.core.models import Project


class ProjectNotFoundError(ValueError):
    pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _variants(pro_file: Path) -> list[str]:
    """Read the named assembly variants stored by KiCad 10 in the project JSON."""
    try:
        data = json.loads(pro_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectNotFoundError(f"invalid KiCad project JSON: {pro_file}") from exc
    schematic = data.get("schematic", {})
    variants = schematic.get("variants", []) if isinstance(schematic, dict) else []
    if not isinstance(variants, list):
        return []
    return sorted(
        item["name"]
        for item in variants
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]
    )


def discover(project_path: Path) -> Project:
    """Find exactly one KiCad project below a supplied directory or project file."""
    candidate = project_path.resolve()
    if candidate.suffix == ".kicad_pro":
        pro_file = candidate
        root = candidate.parent
    else:
        root = candidate
        pro_files = sorted(root.glob("*.kicad_pro"))
        if len(pro_files) != 1:
            hint = "none" if not pro_files else f"{len(pro_files)}"
            raise ProjectNotFoundError(f"expected exactly one .kicad_pro in {root}, found {hint}")
        pro_file = pro_files[0]
    if not pro_file.is_file():
        raise ProjectNotFoundError(f"KiCad project not found: {pro_file}")
    schematics = sorted(root.rglob("*.kicad_sch"))
    boards = sorted(root.rglob("*.kicad_pcb"))
    main_schematic = root / f"{pro_file.stem}.kicad_sch"
    if not main_schematic.is_file():
        if len(schematics) != 1:
            raise ProjectNotFoundError(
                f"could not identify root schematic for {pro_file}; expected {main_schematic.name}"
            )
        main_schematic = schematics[0]
    files = [pro_file, *schematics, *boards]
    return Project(
        root=root,
        pro_file=pro_file,
        main_schematic=main_schematic,
        schematics=schematics,
        boards=boards,
        variants=_variants(pro_file),
        input_hashes={str(path.relative_to(root)): _digest(path) for path in files},
    )
