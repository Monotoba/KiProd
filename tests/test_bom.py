from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from kiprod.cli import app
from kiprod.core.bom import build
from kiprod.core.project import discover
from kiprod.kicad.cli_adapter import export_bom

FIXTURE = Path(__file__).parent / "projects" / "basic"
REVIEWED_BOM = Path(__file__).parent / "fixtures" / "reviewed_bom.csv"


def test_builds_grouped_bom_and_honors_dnp() -> None:
    bom = build(discover(FIXTURE))
    assert len(bom.lines) == 2
    resistor = next(line for line in bom.lines if line.mpn)
    assert resistor.references == ["R1", "R2"]
    assert resistor.quantity == 2
    assert resistor.sources[0].path == "basic.kicad_sch"
    assert all("R3" not in line.references and "R4" not in line.references for line in bom.lines)


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


def test_imported_bom_enriches_missing_schematic_mpn() -> None:
    bom = build(discover(FIXTURE), REVIEWED_BOM)
    capacitor = next(line for line in bom.lines if line.references == ["C1"])
    assert capacitor.mpn == "GRM188R71C104KA01D"
    assert capacitor.fields["mpn"] == "GRM188R71C104KA01D"
    assert bom.imported_bom == str(REVIEWED_BOM)


def test_export_adapter_uses_kicad_cli_with_requested_variant(tmp_path: Path) -> None:
    output = tmp_path / "exported.csv"

    def fake_run(args: list[str], **_: object) -> SimpleNamespace:
        output.write_text("Reference,Value\nR1,1k\n")
        assert args[:4] == ["kicad-cli", "sch", "export", "bom"]
        assert "--variant" in args
        assert args[-1] == str(FIXTURE / "basic.kicad_sch")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("kiprod.kicad.cli_adapter.executable", return_value="kicad-cli"),
        patch("kiprod.kicad.cli_adapter.subprocess.run", side_effect=fake_run),
    ):
        assert export_bom(FIXTURE / "basic.kicad_sch", output, "production") == output
