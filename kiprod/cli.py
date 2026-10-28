from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from kiprod.core.artifacts import write_bom
from kiprod.core.bom import build
from kiprod.core.project import ProjectNotFoundError, discover
from kiprod.kicad.cli_adapter import KiCadCliError, export_bom, version

app = typer.Typer(help="Build traceable KiCad production artifacts.", no_args_is_help=True)


def _build_bom(
    project: Path,
    output_dir: Path | None,
    imported_bom: Path | None = None,
    variant: str | None = None,
) -> tuple[Path, Path]:
    try:
        discovered = discover(project)
    except ProjectNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--project") from exc
    destination = output_dir or discovered.root / "docs" / "production" / "bom"
    if variant is None:
        return write_bom(build(discovered, imported_bom), destination)
    if imported_bom is not None:
        raise typer.BadParameter("--import-bom cannot be combined with --variant")
    if variant not in discovered.variants:
        raise typer.BadParameter(
            f"unknown variant {variant!r}; use `kiprod project` to list variants"
        )
    with TemporaryDirectory(prefix="kiprod-variant-") as temporary:
        exported = export_bom(discovered.main_schematic, Path(temporary) / "variant.csv", variant)
        return write_bom(build(discovered, exported_bom=exported), destination)


@app.command()
def bom(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
    output_dir: Path | None = typer.Option(None, help="Directory for generated BOM artifacts."),
    import_bom: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="CSV BOM to reconcile."
    ),
    variant: str | None = typer.Option(None, help="Named KiCad design variant."),
) -> None:
    """Build a normalized BOM without requiring a KiCad installation."""
    json_path, csv_path = _build_bom(project, output_dir, import_bom, variant)
    typer.echo(f"Wrote {json_path}")
    typer.echo(f"Wrote {csv_path}")


@app.command()
def run(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
    no_send: bool = typer.Option(True, help="Reserved: no external dispatch is implemented in M1."),
) -> None:
    """Run the currently available offline pipeline stages."""
    del no_send
    json_path, _ = _build_bom(project, None)
    typer.echo(f"M1 complete: {json_path}")


@app.command()
def doctor() -> None:
    """Report M1 runtime capabilities without requiring KiCad."""
    cli_version = version()
    state = cli_version or "not found"
    typer.echo(f"KiProd M1: Python core available; kicad-cli: {state}")


@app.command()
def project(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
) -> None:
    """Show discovered KiCad project inputs and assembly variants."""
    try:
        discovered = discover(project)
    except ProjectNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--project") from exc
    typer.echo(f"Project: {discovered.pro_file}")
    typer.echo(f"Schematics: {len(discovered.schematics)}; boards: {len(discovered.boards)}")
    typer.echo("Variants: " + (", ".join(discovered.variants) or "none"))


@app.command("export-bom")
def export_kicad_bom(
    schematic: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", "-o"),
    variant: str | None = typer.Option(None),
) -> None:
    """Use kicad-cli to produce an ungrouped BOM CSV for inspection or import."""
    try:
        path = export_bom(schematic, output, variant)
    except KiCadCliError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Wrote {path}")
