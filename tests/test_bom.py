from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from kiprod.cli import app
from kiprod.core.bom import build
from kiprod.core.project import discover

FIXTURE = Path(__file__).parent / "projects" / "basic"


def test_builds_grouped_bom_and_honors_dnp() -> None:
    bom = build(discover(FIXTURE))
    assert len(bom.lines) == 2
    resistor = next(line for line in bom.lines if line.mpn)
    assert resistor.references == ["R1", "R2"]
    assert resistor.quantity == 2
    assert resistor.sources[0].path == "basic.kicad_sch"


def test_cli_writes_traceable_json_and_csv(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["bom", "--project", str(FIXTURE), "--output-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "bom.normalized.json").read_text())
    assert payload["project"] == "basic"
    assert "basic.kicad_sch" in payload["input_hashes"]
    with (tmp_path / "bom.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
