from __future__ import annotations

from pathlib import Path

from kiprod.analysis.capabilities import check_board
from kiprod.core.models import BoardSpec
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
