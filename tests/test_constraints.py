from __future__ import annotations

import csv
from pathlib import Path

from typer.testing import CliRunner

from kiprod.cli import app
from kiprod.core.constraints import apply, check
from kiprod.core.defaults import Policy, Rule
from kiprod.core.models import BOMLine, NormalizedBOM, SourceRef


def test_missing_ic_mpn_is_under_constrained() -> None:
    bom = NormalizedBOM(
        project="demo",
        input_hashes={},
        lines=[
            BOMLine(
                line_id="1",
                references=["U1"],
                quantity=1,
                value="MCU",
                footprint="QFN",
                sources=[SourceRef(path="demo.kicad_sch")],
            )
        ],
    )
    findings = check(bom, {"ic": {"mpn": Rule(policy=Policy.ERROR)}}, interactive=False)
    assert findings[0].attribute == "mpn"
    assert findings[0].references == ["U1"]


def test_default_value_is_recorded_with_provenance() -> None:
    bom = NormalizedBOM(
        project="demo",
        input_hashes={},
        lines=[
            BOMLine(
                line_id="1",
                references=["R1"],
                quantity=1,
                value="4k7",
                footprint="0603",
                sources=[SourceRef(path="demo.kicad_sch")],
            )
        ],
    )
    resolved, findings = apply(
        bom,
        {"resistor": {"power_w": Rule(policy=Policy.DEFAULT, value=0.1)}},
        interactive=False,
    )
    assert not findings
    assert resolved.lines[0].resolved_fields["power_w"].model_dump() == {
        "value": "0.1",
        "source": "default",
    }


def test_noninteractive_run_writes_under_constrained_csv(tmp_path: Path) -> None:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(
        '(kicad_sch (symbol (lib_id "MCU") (in_bom yes) '
        '(property "Reference" "U1") (property "Value" "MCU")))'
    )
    config = tmp_path / "docs/production/quotes/config"
    config.mkdir(parents=True)
    (config / "kiprod.toml").write_text('[components.ic.mpn]\npolicy = "error"\n')
    result = CliRunner().invoke(app, ["run", "--project", str(tmp_path), "--non-interactive"])
    assert result.exit_code == 3, result.output
    with (tmp_path / "docs/production/bom/under_constrained.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "references": "U1",
            "category": "ic",
            "attribute": "mpn",
            "detail": "attribute is required",
        }
    ]
