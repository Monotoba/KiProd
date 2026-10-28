from __future__ import annotations

from pathlib import Path

import typer

from kiprod.core.artifacts import write_bom
from kiprod.core.bom import build
from kiprod.core.project import ProjectNotFoundError, discover

app = typer.Typer(help="Build traceable KiCad production artifacts.", no_args_is_help=True)


def _build_bom(project: Path, output_dir: Path | None) -> tuple[Path, Path]:
    try:
        discovered = discover(project)
    except ProjectNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--project") from exc
    destination = output_dir or discovered.root / "docs" / "production" / "bom"
    return write_bom(build(discovered), destination)


@app.command()
def bom(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
    output_dir: Path | None = typer.Option(None, help="Directory for generated BOM artifacts."),
) -> None:
    """Build a normalized BOM without requiring a KiCad installation."""
    json_path, csv_path = _build_bom(project, output_dir)
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
    typer.echo("KiProd M1: Python core available; kicad-cli export adapter pending.")
