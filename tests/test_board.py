from __future__ import annotations

from pathlib import Path

from kiprod.analysis.assembly import extract as extract_assembly
from kiprod.analysis.capabilities import check_board
from kiprod.analysis.placements import write_placements
from kiprod.core.models import BoardSpec, Placement
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
    assert assembly.placement_top == 1
    assert assembly.placement_bottom == 1
    assert assembly.unique_parts == 2
    assert assembly.smd_count == 1
    assert assembly.through_hole_count == 1
    assert assembly.smallest_package_mm == 1.6
