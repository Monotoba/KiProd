from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.kicad.sexpr import parse
from kiprod.kicad.writeback import (
    SchematicFieldUpdate,
    apply_writeback,
    prepare_writeback,
    writeback_fields,
)


def _schematic(project: Path) -> tuple[Path, str]:
    path = project / "demo.kicad_sch"
    original = (
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R1") (property "Value" "1k") '
        '(property "MPN" "OLD-MPN")))'
    )
    path.write_text(original, encoding="utf-8")
    return path, original


def test_writeback_preview_requires_approval_then_updates_with_backup(tmp_path: Path) -> None:
    path, original = _schematic(tmp_path)
    updates = [
        SchematicFieldUpdate(path, "R1", "MPN", "NEW-MPN"),
        SchematicFieldUpdate(path, "R1", "Supplier Part Number", "SKU-1"),
    ]

    plan = prepare_writeback(tmp_path, updates)
    assert path.read_text(encoding="utf-8") == original
    assert [(change.field, change.before, change.after) for change in plan.changes] == [
        ("MPN", "OLD-MPN", "NEW-MPN"),
        ("Supplier Part Number", "", "SKU-1"),
    ]

    backups = apply_writeback(tmp_path, plan)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    updated = path.read_text(encoding="utf-8")
    assert '"MPN" "NEW-MPN"' in updated
    assert '"Supplier Part Number" "SKU-1"' in updated
    parse(updated)


def test_writeback_rejects_schematic_changed_after_preview(tmp_path: Path) -> None:
    path, _original = _schematic(tmp_path)
    plan = prepare_writeback(tmp_path, [SchematicFieldUpdate(path, "R1", "MPN", "NEW-MPN")])
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after write-back preview"):
        apply_writeback(tmp_path, plan)


def test_writeback_confines_updates_to_schematic_files_in_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.kicad_sch"
    outside.write_text("(kicad_sch)", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the project"):
        writeback_fields(
            tmp_path,
            [SchematicFieldUpdate(outside, "R1", "MPN", "NEW-MPN")],
        )
