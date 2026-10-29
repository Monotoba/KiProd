from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kiprod.analysis.landed import LandedCost
from kiprod.cli import app
from kiprod.reports.run_archive import archive_inputs, input_paths, load_manifest


def _landed() -> LandedCost:
    return LandedCost(
        supplier_id="supplier-a",
        board_quantity=10,
        currency="USD",
        parts_total="12",
        total="12",
        per_board="1.2",
        lines=[],
    )


def test_run_archive_validates_hashes_and_paths(tmp_path: Path) -> None:
    source = tmp_path / "landed.json"
    source.write_text(_landed().model_dump_json())
    run_dir = tmp_path / "run"
    archive_inputs([source], None, run_dir)
    manifest = load_manifest(run_dir)
    assert manifest["kiprod_version"]
    assert manifest["python_version"]
    paths, bom_path = input_paths(run_dir, manifest)
    assert len(paths) == 1 and bom_path is None
    paths[0].write_text("tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_manifest(run_dir)


def test_run_archive_refuses_to_replace_existing_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "landed.json"
    source.write_text(_landed().model_dump_json())
    run_dir = tmp_path / "run"
    archive_inputs([source], None, run_dir)
    original = (run_dir / "run.json").read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        archive_inputs([source], None, run_dir)

    assert (run_dir / "run.json").read_bytes() == original


def test_run_archive_requires_landed_cost_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        archive_inputs([], None, tmp_path / "run")


def test_report_command_regenerates_archived_markdown_and_json(tmp_path: Path) -> None:
    source = tmp_path / "landed.json"
    source.write_text(_landed().model_dump_json())
    run_dir = tmp_path / "run"
    archive_inputs([source], None, run_dir)
    result = CliRunner().invoke(app, ["report", "--run", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert "supplier-a" in (run_dir / "comparison.md").read_text()
    assert (
        json.loads((run_dir / "comparison.json").read_text())["rows"][0]["supplier_id"]
        == "supplier-a"
    )
