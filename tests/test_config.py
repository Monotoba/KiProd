from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from kiprod.cli import app
from kiprod.core.config import (
    ConfigError,
    load,
    parse_quantities,
    save_project_quantities,
    update_quantities,
)


def test_configuration_layers_project_over_user(tmp_path: Path) -> None:
    user = tmp_path / "user.toml"
    user.write_text("[quantities]\nboards = [2, 10]\n")
    project = tmp_path / "docs/production/quotes/config"
    project.mkdir(parents=True)
    (project / "kiprod.toml").write_text("[quantities]\nboards = [5, 25]\n")
    assert load(tmp_path, user).quantities.boards == [5, 25]


def test_quantities_support_ranges_and_changes() -> None:
    assert parse_quantities("1, 10..30:10") == [1, 10, 20, 30]
    assert update_quantities([1, 5], add=[10], remove=[1]) == [5, 10]


def test_save_project_quantities_preserves_other_settings(tmp_path: Path) -> None:
    config_dir = tmp_path / "docs/production/quotes/config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "kiprod.toml"
    config_path.write_text(
        '[paths]\nproduction = "factory"\nconfig = "cfg"\nstate = "state"\n\n'
        "[quantities]\nboards = [1, 5]\n\n"
        '[components.resistor.power_w]\npolicy = "default"\nvalue = 0.25\n',
        encoding="utf-8",
    )

    saved_path = save_project_quantities(tmp_path, [10, 1, 5])

    settings = load(tmp_path)
    contents = saved_path.read_text(encoding="utf-8")
    assert settings.quantities.boards == [1, 5, 10]
    assert settings.paths.production == "factory"
    assert 'policy = "default"' in contents
    assert "boards = [1, 5, 10]" in contents


def test_save_project_quantities_creates_only_project_quantity_override(tmp_path: Path) -> None:
    user = tmp_path / "user.toml"
    user.write_text(
        '[paths]\nproduction = "custom-production"\nconfig = "custom-config"\n'
        'state = "custom-state"\n[quantities]\nboards = [2, 20]\n',
        encoding="utf-8",
    )

    save_project_quantities(tmp_path, [3, 30])

    settings = load(tmp_path, user)
    assert settings.quantities.boards == [3, 30]
    assert settings.paths.production == "custom-production"


def test_rejects_invalid_quantity_ranges() -> None:
    with pytest.raises(ConfigError):
        parse_quantities("10..1:1")


def test_config_cli_initializes_and_shows_project_settings(tmp_path: Path) -> None:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    runner = CliRunner()
    init = runner.invoke(app, ["config", "init", "--project", str(tmp_path)])
    assert init.exit_code == 0, init.output
    show = runner.invoke(app, ["config", "show", "--project", str(tmp_path)])
    assert show.exit_code == 0, show.output
    assert '"boards": [' in show.output


def test_run_accepts_quantity_replacement_and_changes(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / "demo.kicad_pro").write_text("{}")
    (project / "demo.kicad_sch").write_text("(kicad_sch)")
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--project",
            str(project),
            "--qty",
            "1,10..30:10",
            "--remove-qty",
            "20",
            "--add-qty",
            "50",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Board quantities: 1, 10, 30, 50" in result.output


def test_run_records_default_field_provenance(tmp_path: Path) -> None:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(
        '(kicad_sch (symbol (lib_id "R") (in_bom yes) '
        '(property "Reference" "R1") (property "Value" "1k")))'
    )
    config = tmp_path / "docs/production/quotes/config"
    config.mkdir(parents=True)
    (config / "kiprod.toml").write_text(
        '[components.resistor.power_w]\npolicy = "default"\nvalue = 0.1\n'
    )
    result = CliRunner().invoke(app, ["run", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    import json

    payload = json.loads((tmp_path / "docs/production/bom/bom.normalized.json").read_text())
    assert payload["lines"][0]["resolved_fields"]["power_w"] == {
        "value": "0.1",
        "source": "default",
    }
