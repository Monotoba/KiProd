from __future__ import annotations

from pathlib import Path

import pytest

from kiprod.analysis.assembly import extract as extract_assembly
from kiprod.analysis.capabilities import check_assembly, check_board
from kiprod.analysis.panelization import (
    discover_fabrication_notes,
    extract_boards_per_panel,
)
from kiprod.analysis.placements import write_placements
from kiprod.core.models import AssemblySpec, BoardSpec, Placement
from kiprod.kicad.board import extract
from kiprod.plugins.models import Manifest

FIXTURE = Path(__file__).parent / "fixtures" / "board_minimal.kicad_pcb"


def test_extracts_board_metrics_from_pcb_sexpr() -> None:
    board = extract(FIXTURE)
    assert board.layers == 2
    assert board.thickness_mm == 1.6
    assert board.width_mm == 40
    assert board.height_mm == 10
    assert board.min_track_mm == 0.075
    assert board.min_drill_mm == 0.2
    assert board.copper_finish == "ENIG"
    assert board.stackup[1]["material"] == "FR4"


def test_capability_check_flags_out_of_range_board() -> None:
    board = BoardSpec(
        source="test.kicad_pcb",
        layers=4,
        min_track_mm=0.075,
        min_drill_mm=0.1,
    )
    manifest = Manifest.model_validate(
        {
            "id": "example.fab",
            "name": "Example fab",
            "version": "1",
            "capabilities": {
                "pcb_fab": {"limits": {"layers": [1, 2], "min_track_mm": 0.1, "min_drill_mm": 0.2}}
            },
        }
    )
    findings = check_board(board, manifest)
    assert {finding.field for finding in findings} == {"layers", "min_track_mm", "min_drill_mm"}


def test_maps_placement_rows_to_assembler_column_names(tmp_path: Path) -> None:
    output = tmp_path / "cpl.csv"
    write_placements(
        [
            Placement(
                reference="R1",
                value="1k",
                footprint="0603",
                x_mm=10,
                y_mm=20,
                side="top",
                rotation=90,
            )
        ],
        ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"],
        output,
    )
    assert output.read_text().splitlines() == [
        "Designator,Mid X,Mid Y,Layer,Rotation",
        "R1,10.0,20.0,top,90.0",
    ]


def test_assembly_extracts_placements_and_packaging_from_board() -> None:
    assembly = extract_assembly(FIXTURE)
    assert assembly.placement_top == 2
    assert assembly.placement_bottom == 1
    assert assembly.unique_parts == 3
    assert assembly.smd_count == 2
    assert assembly.through_hole_count == 1
    assert assembly.smallest_package_mm == 1.6
    assert assembly.bga_count == 1
    assert assembly.finest_pitch_mm == 0.5
    assert assembly.programming_components == ["U1"]


def test_assembly_capability_check_flags_pitch_and_unsupported_packages() -> None:
    assembly = AssemblySpec(
        placement_top=12,
        placement_bottom=3,
        unique_parts=8,
        smd_count=15,
        through_hole_count=0,
        bga_count=1,
        qfn_count=2,
        finest_pitch_mm=0.4,
        programming_components=["U1"],
    )
    manifest = Manifest.model_validate(
        {
            "id": "example.assembly",
            "name": "Example assembly",
            "version": "1",
            "capabilities": {
                "pcb_assembly": {
                    "limits": {
                        "placements_per_side": 10,
                        "unique_parts": 10,
                        "min_pitch_mm": 0.5,
                        "supports_bga": False,
                        "supports_qfn": False,
                        "supports_programming": False,
                    }
                }
            },
        }
    )
    findings = check_assembly(assembly, manifest)
    assert {finding.field for finding in findings} == {
        "placements_per_side",
        "min_pitch_mm",
        "supports_bga",
        "supports_qfn",
        "supports_programming",
    }


def test_extracts_explicit_boards_per_panel_from_fabrication_notes(tmp_path: Path) -> None:
    notes = tmp_path / "fab-notes.txt"
    notes.write_text("Panelization: 4 boards per panel\n", encoding="utf-8")
    assert extract_boards_per_panel([notes]) == (4, str(notes))


def test_panel_count_is_unknown_without_explicit_fabrication_notes() -> None:
    assert extract_boards_per_panel([]) == (None, None)


def test_discovers_fabrication_notes_by_filename(tmp_path: Path) -> None:
    notes_dir = tmp_path / "docs"
    notes_dir.mkdir()
    notes = notes_dir / "fabrication-notes.md"
    notes.write_text("Boards per panel: 4", encoding="utf-8")
    (tmp_path / "ordinary.md").write_text("Boards per panel: 8", encoding="utf-8")
    hidden = tmp_path / ".private"
    hidden.mkdir()
    (hidden / "fab-notes.txt").write_text("Boards per panel: 16", encoding="utf-8")
    assert discover_fabrication_notes(tmp_path) == [notes]


def test_extracts_panel_count_from_pdf_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    from types import SimpleNamespace

    import kiprod.analysis.panelization as panelization

    pdf = tmp_path / "fab-notes.pdf"
    pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(panelization.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Boards per panel: 6"),
    )
    assert extract_boards_per_panel([pdf]) == (6, str(pdf))


def test_panel_count_rejects_conflicting_fabrication_notes(tmp_path: Path) -> None:
    first = tmp_path / "fab-a.txt"
    second = tmp_path / "fab-b.txt"
    first.write_text("Boards per panel: 4", encoding="utf-8")
    second.write_text("Boards per panel: 6", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting"):
        extract_boards_per_panel([first, second])
