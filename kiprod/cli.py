from __future__ import annotations

import getpass
import importlib.util
import ipaddress
import json
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import typer

from kiprod.ai.anthropic import AnthropicProvider
from kiprod.ai.evaluation import evaluate_review_fixtures
from kiprod.ai.openai_compatible import OpenAICompatibleProvider
from kiprod.ai.openai_responses import OpenAIResponsesProvider
from kiprod.ai.provider import LLMProvider, LLMResult, Message, ProviderFeature
from kiprod.ai.runtime import AIRequestManager, RolePolicy
from kiprod.analysis.assembly import extract as extract_assembly
from kiprod.analysis.capabilities import check_assembly, check_board
from kiprod.analysis.comparison import compare
from kiprod.analysis.landed import LandedCost
from kiprod.analysis.panelization import (
    discover_fabrication_notes,
    extract_boards_per_panel,
)
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
from kiprod.kicad.board import extract as extract_board
from kiprod.kicad.cli_adapter import KiCadCliError, export_bom, export_placements, version
from kiprod.net.http import HttpClient
from kiprod.plugins.host import PluginError, discover_plugins
from kiprod.reports.markdown import comparison_markdown
from kiprod.reports.run_archive import archive_inputs, input_paths, load_manifest
from kiprod.rfq.approval import approve_package, has_current_approval, package_sha256
from kiprod.rfq.delivery import send_approved_rfq
from kiprod.rfq.email import create_email_draft
from kiprod.rfq.inbox import import_reply
from kiprod.rfq.mailbox import poll_mailbox
from kiprod.rfq.package import build_package, verify_package
from kiprod.rfq.privacy import scan_privacy
from kiprod.rfq.quote_import import parse_quote_attachment
from kiprod.rfq.workflow import get_rfq_status, register_email_draft

app = typer.Typer(help="Build traceable KiCad production artifacts.", no_args_is_help=True)
config_app = typer.Typer(help="Manage layered project configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")
plugins_app = typer.Typer(help="Discover and validate supplier plugins.", no_args_is_help=True)
app.add_typer(plugins_app, name="plugins")
rfq_app = typer.Typer(help="Create and verify local supplier RFQ packages.", no_args_is_help=True)
app.add_typer(rfq_app, name="rfq")
ai_app = typer.Typer(help="Evaluate and run typed AI review tasks.", no_args_is_help=True)
app.add_typer(ai_app, name="ai")


class _BudgetedRoleProvider:
    def __init__(self, provider: LLMProvider, manager: AIRequestManager) -> None:
        self.provider = provider
        self.manager = manager
        self.name = provider.name
        self.is_local = provider.is_local

    def complete(
        self,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        result = self.manager.complete(
            "reasoning",
            messages,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not isinstance(result, LLMResult):
            raise RuntimeError("budget manager returned a dry-run plan during model evaluation")
        return result

    def supports(self, feature: ProviderFeature) -> bool:
        return self.provider.supports(feature)

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        return self.provider.estimate_cost(prompt_tokens, completion_tokens)


def _ai_provider(
    provider_type: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    prompt_cost_per_million: float | None,
    completion_cost_per_million: float | None,
) -> LLMProvider:
    if provider_type == "openai":
        endpoint = base_url or "https://api.openai.com/v1"
    elif provider_type == "anthropic":
        endpoint = base_url or "https://api.anthropic.com"
    elif provider_type == "compatible":
        if not base_url:
            raise ValueError("--base-url is required for the compatible provider")
        endpoint = base_url
    else:
        raise ValueError("provider must be one of: openai, anthropic, compatible")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("provider base URL must be a valid HTTP(S) origin/path")
    host = parsed.hostname.casefold()
    local = host == "localhost"
    try:
        local = local or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not local:
        raise ValueError("unencrypted model providers are allowed only on loopback")
    client = HttpClient({host}, allow_local_http=parsed.scheme == "http" and local)
    if provider_type == "openai":
        if not api_key:
            raise ValueError("OpenAI API key is required")
        return OpenAIResponsesProvider(
            api_key=api_key,
            base_url=endpoint,
            model=model,
            http=client,
            prompt_cost_per_million=prompt_cost_per_million,
            completion_cost_per_million=completion_cost_per_million,
        )
    if provider_type == "anthropic":
        if not api_key:
            raise ValueError("Anthropic API key is required")
        return AnthropicProvider(
            api_key=api_key,
            base_url=endpoint,
            model=model,
            http=client,
            prompt_cost_per_million=prompt_cost_per_million,
            completion_cost_per_million=completion_cost_per_million,
        )
    return OpenAICompatibleProvider(
        base_url=endpoint,
        provider_name="openai_compatible",
        api_key=api_key,
        model=model,
        http=client,
        prompt_cost_per_million=prompt_cost_per_million,
        completion_cost_per_million=completion_cost_per_million,
    )


@ai_app.command("eval")
def ai_evaluate(
    provider_type: str = typer.Argument(..., help="Provider: openai, anthropic, compatible."),
    model: str = typer.Option(..., "--model"),
    base_url: str | None = typer.Option(None, "--base-url"),
    api_key_env: str | None = typer.Option(None, "--api-key-env"),
    fixtures: Path = typer.Option(Path("tests/fixtures/ai_review"), "--fixtures", exists=True),
    expected: Path = typer.Option(
        Path("tests/fixtures/ai_review/expected.json"), "--expected", exists=True
    ),
    prompt_dir: list[Path] = typer.Option([], "--prompt-dir", exists=True, file_okay=False),
    max_output_tokens: int = typer.Option(2000, "--max-output-tokens", min=16),
    max_run_tokens: int = typer.Option(20000, "--max-run-tokens", min=1),
    max_run_cost: float | None = typer.Option(None, "--max-run-cost", min=0.0),
    prompt_cost_per_million: float | None = typer.Option(None, "--prompt-cost-per-million"),
    completion_cost_per_million: float | None = typer.Option(
        None, "--completion-cost-per-million"
    ),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """Make live provider requests and evaluate one model against labeled BOM fixtures."""
    key_env = api_key_env or {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "compatible": "KIPROD_AI_API_KEY",
    }.get(provider_type)
    api_key = os.environ.get(key_env) if key_env else None
    if key_env and key_env not in os.environ:
        raise typer.BadParameter(f"API key environment variable is not set: {key_env}")
    try:
        provider = _ai_provider(
            provider_type,
            model,
            base_url,
            api_key,
            prompt_cost_per_million,
            completion_cost_per_million,
        )
        manager = AIRequestManager(
            {"reasoning": RolePolicy(provider, model, max_output_tokens=max_output_tokens)},
            max_run_tokens=max_run_tokens,
            max_run_cost=max_run_cost,
        )
        budgeted = _BudgetedRoleProvider(provider, manager)
        evaluation = evaluate_review_fixtures(
            fixtures,
            expected,
            budgeted,
            prompt_dirs=prompt_dir or None,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    serialized = evaluation.model_dump_json(indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    typer.echo(serialized, nl=False)
    if not evaluation.passed:
        raise typer.Exit(code=1)


@rfq_app.command("package")
def rfq_package(
    files: list[Path] = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(..., "--output", "-o"),
    signing_key: str = typer.Option(..., "--signing-key", help="Local GPG key ID or fingerprint."),
) -> None:
    """Scan, sign, and zip only the explicitly selected files; never send email."""
    names = [path.name for path in files]
    if len(names) != len(set(names)):
        raise typer.BadParameter("input files must have unique filenames")
    try:
        package = build_package(dict(zip(names, files, strict=True)), output, signing_key)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Wrote signed RFQ package {package}")


@rfq_app.command("verify")
def rfq_verify(package: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Verify RFQ package file hashes, contents, and detached GPG signature."""
    try:
        files = verify_package(package)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("Verified RFQ package files: " + ", ".join(files))


@rfq_app.command("scan-privacy")
def rfq_scan_privacy(
    files: list[Path] = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Run the RFQ privacy checks on explicitly selected files without packaging them."""
    names = [path.name for path in files]
    if len(names) != len(set(names)):
        raise typer.BadParameter("input files must have unique filenames")
    try:
        with TemporaryDirectory(prefix="kiprod-privacy-") as temporary:
            stage = Path(temporary)
            for path in files:
                shutil.copyfile(path, stage / path.name)
            findings = scan_privacy(stage)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if findings:
        for finding in findings:
            typer.echo(finding, err=True)
        raise typer.Exit(code=3)
    typer.echo(f"No privacy findings in {len(files)} selected file(s).")


@rfq_app.command("draft")
def rfq_draft(
    rfq_id: str = typer.Argument(...),
    package: Path = typer.Argument(..., exists=True, dir_okay=False),
    recipient: str = typer.Option(..., "--to"),
    sender: str = typer.Option(..., "--from"),
    subject: str = typer.Option(..., "--subject"),
    body_file: Path = typer.Option(..., "--body", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", "-o"),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"),
        "--database",
        help="Local RFQ audit database.",
    ),
) -> None:
    """Create a verified local email draft; this command does not send messages."""
    try:
        draft = create_email_draft(
            rfq_id=rfq_id,
            sender=sender,
            recipient=recipient,
            subject=subject,
            body=body_file.read_text(encoding="utf-8"),
            package=package,
            output=output,
        )
        status = register_email_draft(database, rfq_id, recipient, draft)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Wrote email draft {draft}")
    typer.echo(f"RFQ {status.rfq_id}: {status.state}; email SHA-256 {status.payload_sha256}")


@rfq_app.command("status")
def rfq_status(
    rfq_id: str = typer.Argument(...),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"),
        "--database",
        help="Local RFQ audit database.",
    ),
) -> None:
    """Show the current state and payload hash for one RFQ."""
    status = get_rfq_status(database, rfq_id)
    if status is None:
        raise typer.BadParameter(f"unknown RFQ ID: {rfq_id}")
    typer.echo(
        f"{status.rfq_id}: {status.state}; recipient {status.recipient}; "
        f"email SHA-256 {status.payload_sha256}"
    )


@rfq_app.command("send")
def rfq_send(
    rfq_id: str = typer.Argument(...),
    smtp_host: str = typer.Option(..., "--smtp-host"),
    smtp_port: int = typer.Option(587, "--smtp-port"),
    username: str | None = typer.Option(None, "--username"),
    password_env: str = typer.Option("KIPROD_SMTP_PASSWORD", "--password-env"),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"),
        "--database",
        help="Local RFQ audit database.",
    ),
) -> None:
    """Send an approved exact email over SMTP STARTTLS; failures remain retryable."""
    password = os.environ.get(password_env) if username else None
    if username and password is None:
        raise typer.BadParameter(f"SMTP password environment variable is not set: {password_env}")
    try:
        status = send_approved_rfq(
            database,
            rfq_id,
            smtp_host,
            smtp_port=smtp_port,
            username=username,
            password=password,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"RFQ {status.rfq_id} sent to {status.recipient}; state is {status.state}")


@rfq_app.command("import-reply")
def rfq_import_reply(
    message: Path = typer.Argument(..., exists=True, dir_okay=False),
    output_root: Path = typer.Option(
        Path("docs/production/.kiprod/replies"),
        "--output-root",
        help="Local directory for captured messages and attachments.",
    ),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"),
        "--database",
        help="Local RFQ audit database.",
    ),
) -> None:
    """Match and capture a saved supplier reply without connecting to a mailbox."""
    try:
        imported = import_reply(message, database, output_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Matched {imported.rfq_id}; state is {imported.state}")
    typer.echo(f"Stored email: {imported.stored_message}")
    typer.echo("Attachments: " + (", ".join(imported.attachments) or "none"))


@rfq_app.command("poll-mailbox")
def rfq_poll_mailbox(
    provider: str = typer.Argument(..., help="Mailbox API: graph or gmail."),
    token_env: str = typer.Option("KIPROD_MAILBOX_TOKEN", "--token-env"),
    limit: int = typer.Option(50, min=1, max=100),
    output_root: Path = typer.Option(
        Path("docs/production/.kiprod/replies"),
        "--output-root",
        help="Local directory for captured messages and attachments.",
    ),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"),
        "--database",
        help="Local RFQ audit database.",
    ),
) -> None:
    """Read messages through Microsoft Graph or Gmail APIs and import matching RFQs."""
    token = os.environ.get(token_env)
    if not token:
        raise typer.BadParameter(f"mailbox access token environment variable is empty: {token_env}")
    try:
        result = poll_mailbox(
            provider,
            token,
            database,
            output_root,
            limit=limit,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Checked {result.checked} message(s); imported {len(result.imported)} RFQ reply(s)."
    )
    if result.more_available:
        typer.echo("More mailbox pages are available; run the poll command again to continue.")
    for item in result.skipped + result.errors:
        typer.echo(item, err=True)


@rfq_app.command("parse-quote")
def rfq_parse_quote(
    attachment: Path = typer.Argument(..., exists=True, dir_okay=False),
    supplier_id: str = typer.Option(..., "--supplier-id"),
    output: Path = typer.Option(..., "--output", "-o"),
    currency: str | None = typer.Option(
        None, "--currency", help="Use only if the file omits currency."
    ),
) -> None:
    """Parse a CSV/XLSX quote into source-backed candidates and a review queue."""
    try:
        result = parse_quote_attachment(attachment, supplier_id, currency=currency)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Wrote {len(result.offers)} offer candidate(s) and "
        f"{len(result.review_queue)} review item(s) to {output}"
    )


@rfq_app.command("approve")
def rfq_approve(
    payload: Path = typer.Argument(..., exists=True, dir_okay=False),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"),
        "--database",
        help="Local RFQ audit database.",
    ),
    user: str = typer.Option(
        getpass.getuser(), "--user", help="Name recorded in the approval log."
    ),
) -> None:
    """Record interactive approval for the exact current file bytes."""
    digest = package_sha256(payload)
    typer.echo(f"Payload SHA-256: {digest}")
    if not typer.confirm("Approve this exact RFQ payload?"):
        raise typer.Exit(code=2)
    try:
        record = approve_package(payload, database, user, expected_hash=digest)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Approval {record.approval_id} recorded for {record.user} at {record.approved_at}")


@rfq_app.command("approval-status")
def rfq_approval_status(
    payload: Path = typer.Argument(..., exists=True, dir_okay=False),
    database: Path = typer.Option(
        Path("docs/production/.kiprod/state.sqlite"), "--database", help="Local RFQ audit database."
    ),
) -> None:
    """Check whether an approval matches the file's current bytes."""
    if has_current_approval(payload, database):
        typer.echo(f"Current payload is approved: {package_sha256(payload)}")
        return
    typer.echo(f"Current payload has no matching approval: {package_sha256(payload)}")
    raise typer.Exit(code=1)


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
    """Report installed KiProd runtime capabilities."""
    cli_version = version()
    typer.echo(f"KiProd {__import__('kiprod').__version__}")
    typer.echo(f"Python core: available ({sys.version.split()[0]})")
    typer.echo(f"kicad-cli: {cli_version or 'not found'}")
    xlsx_status = "available" if importlib.util.find_spec("openpyxl") else "install kiprod[reports]"
    typer.echo(f"XLSX reports: {xlsx_status}")


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


@app.command("board")
def inspect_board(
    project: Path = typer.Option(Path.cwd(), exists=True, file_okay=True, dir_okay=True),
    plugin_id: str | None = typer.Option(None, "--supplier", help="Optional fab plugin to check."),
    fab_notes: list[Path] = typer.Option(
        [],
        "--fab-notes",
        exists=True,
        dir_okay=False,
        help="Fabrication note text file; repeatable.",
    ),
) -> None:
    """Extract board fabrication metrics and optionally check supplier limits."""
    try:
        discovered = discover(project)
    except ProjectNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--project") from exc
    if not discovered.boards:
        raise typer.BadParameter("project has no .kicad_pcb board")
    board = extract_board(discovered.boards[0])
    try:
        notes = sorted(set(discover_fabrication_notes(discovered.root) + fab_notes))
        boards_per_panel, panel_count_source = extract_boards_per_panel(notes)
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--fab-notes") from exc
    if boards_per_panel is not None:
        board = board.model_copy(
            update={"boards_per_panel": boards_per_panel, "panel_count_source": panel_count_source}
        )
    assembly = extract_assembly(discovered.boards[0])
    typer.echo(
        json.dumps({"board": board.model_dump(), "assembly": assembly.model_dump()}, indent=2)
    )
    if plugin_id:
        try:
            plugin = next(
                (
                    item
                    for item in discover_plugins(_plugin_paths(project))
                    if item.manifest.id == plugin_id
                ),
                None,
            )
        except PluginError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if plugin is None:
            raise typer.BadParameter(f"plugin not found: {plugin_id}")
        findings = check_board(board, plugin.manifest) + check_assembly(assembly, plugin.manifest)
        typer.echo(json.dumps([item.model_dump() for item in findings], indent=2))


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


@app.command("export-cpl")
def export_cpl(
    board: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", "-o"),
    variant: str | None = typer.Option(None),
) -> None:
    """Export a KiCad position/centroid CSV in millimeters."""
    try:
        path = export_placements(board, output, variant)
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
    run_dir: Path | None = typer.Option(
        None, "--run-dir", help="Archive all inputs and generated reports."
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
            from kiprod.reports.xlsx import comparison_workbook

            workbook_path = comparison_workbook(comparison, costs, workbook)
        except ImportError as exc:
            raise typer.BadParameter("XLSX export requires `pip install kiprod[reports]`") from exc
        typer.echo(f"Wrote {workbook_path}")
    if run_dir is not None:
        archive_inputs(inputs, bom, run_dir)
        shutil.copyfile(output, run_dir / "comparison.md")
        (run_dir / "comparison.json").write_text(
            comparison.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        if workbook is not None:
            shutil.copyfile(workbook, run_dir / "comparison.xlsx")
        typer.echo(f"Archived run {run_dir}")


@app.command("report")
def regenerate_report(
    run_dir: Path = typer.Option(..., "--run", exists=True, file_okay=False),
    workbook: bool = typer.Option(False, "--xlsx", help="Also regenerate the XLSX workbook."),
) -> None:
    """Regenerate comparison reports from hash-verified saved inputs."""
    try:
        manifest = load_manifest(run_dir)
        inputs, bom_path = input_paths(run_dir, manifest)
        costs = [
            LandedCost.model_validate_json(path.read_text(encoding="utf-8")) for path in inputs
        ]
        required_mpns: set[str] = set()
        if bom_path:
            from kiprod.core.models import NormalizedBOM

            loaded_bom = NormalizedBOM.model_validate_json(bom_path.read_text(encoding="utf-8"))
            required_mpns = {line.mpn for line in loaded_bom.lines if line.mpn}
        comparison = compare(costs, required_mpns)
        (run_dir / "comparison.md").write_text(comparison_markdown(comparison), encoding="utf-8")
        (run_dir / "comparison.json").write_text(
            comparison.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        if workbook:
            from kiprod.reports.xlsx import comparison_workbook

            comparison_workbook(comparison, costs, run_dir / "comparison.xlsx")
    except (OSError, ValueError, KeyError) as exc:
        raise typer.BadParameter(f"cannot regenerate report: {exc}") from exc
    typer.echo(f"Regenerated reports in {run_dir}")
