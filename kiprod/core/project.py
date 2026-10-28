from __future__ import annotations

import hashlib
from pathlib import Path

from kiprod.core.models import Project


class ProjectNotFoundError(ValueError):
    pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    files = [pro_file, *schematics, *boards]
    return Project(
        root=root,
        pro_file=pro_file,
        schematics=schematics,
        boards=boards,
        input_hashes={str(path.relative_to(root)): _digest(path) for path in files},
    )
