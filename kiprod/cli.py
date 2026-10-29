from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from kiprod.analysis.comparison import compare
from kiprod.analysis.landed import LandedCost
from kiprod.core.artifacts import write_bom
from kiprod.core.bom import build
from kiprod.core.config import (
    DEFAULT_TOML,
    ConfigError,
    load,
    project_config_path,
    update_quantities,
)
from kiprod.core.constraints import apply, write
from kiprod.core.project import ProjectNotFoundError, discover
from kiprod.kicad.cli_adapter import KiCadCliError, export_bom, version
from kiprod.plugins.host import PluginError, discover_plugins
from kiprod.reports.markdown import comparison_markdown
from kiprod.reports.xlsx import comparison_workbook

app = typer.Typer(help="Build traceable KiCad production artifacts.", no_args_is_help=True)
config_app = typer.Typer(help="Manage layered project configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")
plugins_app = typer.Typer(help="Discover and validate supplier plugins.", no_args_is_help=True)
app.add_typer(plugins_app, name="plugins")


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
    qty: str | None = typer.Option(None, help="Replace quantities; supports 1,10..100:10."),
    add_qty: list[int] = typer.Option([], help="Add a board quantity; repeat as needed."),
    remove_qty: list[int] = typer.Option([], help="Remove a board quantity; repeat as needed."),
    non_interactive: bool = typer.Option(
        False, help="Fail rather than request missing attributes."
    ),
) -> None:
    """Run the currently available offline pipeline stages."""
    del no_send
    try:
        settings = load(_project_root(project))
        quantities = update_quantities(
            settings.quantities.boards,
            replacement=qty,
            add=add_qty,
            remove=remove_qty,
        )
    except ConfigError as exc:
        typer.echo(f"Invalid quantities: {exc}", err=True)
        raise typer.Exit(code=5) from exc
    try:
        discovered = discover(project)
    except ProjectNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--project") from exc
    bom, findings = apply(build(discovered), settings.components, interactive=not non_interactive)
    json_path, _ = write_bom(bom, discovered.root / "docs" / "production" / "bom")
    if findings:
        under_constrained = write(
            findings, discovered.root / "docs" / "production" / "bom" / "under_constrained.csv"
        )
        typer.echo(f"Under-constrained parts: {under_constrained}", err=True)
        raise typer.Exit(code=3)
    typer.echo("Board quantities: " + ", ".join(str(value) for value in quantities))
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


def _project_root(project: Path) -> Path:
    candidate = project.resolve()
    if candidate.suffix == ".kicad_pro" and candidate.is_file():
        return candidate.parent
    projects = sorted(candidate.glob("*.kicad_pro")) if candidate.is_dir() else []
    if len(projects) == 1:
        return candidate
    raise typer.BadParameter(
        f"expected exactly one .kicad_pro in {candidate}", param_hint="--project"
    )


@config_app.command("init")
def config_init(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
    force: bool = typer.Option(False, help="Replace an existing project configuration."),
) -> None:
    """Create the project-local configuration template."""
    destination = project_config_path(_project_root(project))
    if destination.exists() and not force:
        raise typer.BadParameter(
            f"configuration already exists: {destination}; use --force to replace it"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(DEFAULT_TOML, encoding="utf-8")
    typer.echo(f"Wrote {destination}")


@config_app.command("show")
def config_show(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
) -> None:
    """Print effective configuration after all layers are applied."""
    try:
        settings = load(_project_root(project))
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(settings.model_dump_json(indent=2))


@config_app.command("validate")
def config_validate(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
) -> None:
    """Validate the effective configuration."""
    try:
        load(_project_root(project))
    except ConfigError as exc:
        typer.echo(f"Invalid configuration: {exc}", err=True)
        raise typer.Exit(code=5) from exc
    typer.echo("Configuration is valid.")


def _plugin_paths(project: Path) -> list[Path]:
    root = _project_root(project)
    user_root = Path.home() / ".config" / "kiprod" / "suppliers"
    project_root = root / "docs" / "production" / "quotes" / "config" / "suppliers"
    bundled_root = Path(__file__).resolve().parent / "plugins" / "suppliers"
    return [project_root, user_root, bundled_root]


@plugins_app.command("list")
def plugins_list(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
) -> None:
    """List valid plugins using project, user, then bundled precedence."""
    try:
        plugins = discover_plugins(_plugin_paths(project))
    except PluginError as exc:
        typer.echo(f"Plugin error: {exc}", err=True)
        raise typer.Exit(code=5) from exc
    if not plugins:
        typer.echo("No plugins found.")
        return
    for plugin in plugins:
        resources = ", ".join(plugin.manifest.resource_types) or "unspecified"
        typer.echo(f"{plugin.manifest.id}\t{plugin.manifest.name}\t{resources}")


@plugins_app.command("test")
def plugins_test(
    plugin_id: str = typer.Argument(...),
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
) -> None:
    """Run a plugin health check in its isolated worker process."""
    try:
        plugins = discover_plugins(_plugin_paths(project))
        plugin = next((item for item in plugins if item.manifest.id == plugin_id), None)
        if plugin is None:
            raise PluginError(f"plugin not found: {plugin_id}")
        result = plugin.call("health_check")
    except PluginError as exc:
        typer.echo(f"Plugin test failed: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(f"{plugin_id}: {result}")


@app.command("quote")
def quote_lookup(
    mpn: str = typer.Argument(..., help="Manufacturer part number to search."),
    plugin_id: str = typer.Option(..., "--plugin", help="Plugin manifest ID to query."),
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
) -> None:
    """Search one enabled catalog plugin and print its source-backed offers."""
    try:
        plugins = discover_plugins(_plugin_paths(project))
        plugin = next((item for item in plugins if item.manifest.id == plugin_id), None)
        if plugin is None:
            raise PluginError(f"plugin not found: {plugin_id}")
        offers = plugin.call("search", mpn)
    except PluginError as exc:
        typer.echo(f"Quote lookup failed: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(json.dumps(offers, indent=2, sort_keys=True))


@app.command("compare")
def compare_quotes(
    inputs: list[Path] = typer.Argument(..., exists=True, dir_okay=False),
    output: Path = typer.Option(Path("comparison.md"), "--output", "-o"),
    workbook: Path | None = typer.Option(None, "--xlsx", help="Optional XLSX workbook path."),
    json_output: Path | None = typer.Option(None, "--json", help="Optional comparison JSON path."),
    bom: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="Normalized BOM JSON for coverage analysis."
    ),
) -> None:
    """Compare saved landed-cost JSON records and write an auditable Markdown table."""
    costs: list[LandedCost] = []
    try:
        for path in inputs:
            costs.append(LandedCost.model_validate_json(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"invalid landed-cost input: {exc}") from exc
    required_mpns: set[str] = set()
    if bom is not None:
        try:
            from kiprod.core.models import NormalizedBOM

            normalized_bom = NormalizedBOM.model_validate_json(bom.read_text(encoding="utf-8"))
            required_mpns = {line.mpn for line in normalized_bom.lines if line.mpn}
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(f"invalid normalized BOM: {exc}") from exc
    comparison = compare(costs, required_mpns)
    report = comparison_markdown(comparison)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    typer.echo(f"Wrote {output}")
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(comparison.model_dump_json(indent=2) + "\n", encoding="utf-8")
        typer.echo(f"Wrote {json_output}")
    if workbook is not None:
        try:
            workbook_path = comparison_workbook(comparison, costs, workbook)
        except ImportError as exc:
            raise typer.BadParameter("XLSX export requires `pip install kiprod[reports]`") from exc
        typer.echo(f"Wrote {workbook_path}")
