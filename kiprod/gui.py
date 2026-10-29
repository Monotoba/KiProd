from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import uuid4

from kiprod.ai.review import ReviewFinding, ReviewReport, review_bom
from kiprod.ai.review_decisions import (
    Disposition,
    finding_key,
    latest_dispositions,
    load_decisions,
    record_decision,
)
from kiprod.analysis.assembly import extract as extract_assembly
from kiprod.analysis.capabilities import check_assembly, check_board
from kiprod.analysis.comparison import Comparison, ComparisonWeights, compare
from kiprod.analysis.landed import LandedCost
from kiprod.analysis.panelization import discover_fabrication_notes, extract_boards_per_panel
from kiprod.core.artifacts import write_bom
from kiprod.core.bom import build
from kiprod.core.bom_edits import (
    BOMOverrides,
    apply_bom_overrides,
    load_bom_overrides,
    save_bom_overrides,
)
from kiprod.core.config import ConfigError, load, parse_quantities, save_project_quantities
from kiprod.core.models import AssemblySpec, BoardSpec, NormalizedBOM, Offer, Project
from kiprod.core.project import discover
from kiprod.kicad.board import extract as extract_board
from kiprod.kicad.cli_adapter import export_bom
from kiprod.kicad.writeback import (
    SchematicFieldUpdate,
    apply_writeback,
    prepare_writeback,
)
from kiprod.plugins.credentials import (
    CredentialStoreUnavailable,
    has_credential,
    save_credential,
)
from kiprod.plugins.host import PluginError, discover_plugins
from kiprod.plugins.models import Manifest
from kiprod.plugins.settings import load_plugin_settings, save_plugin_settings
from kiprod.reports.markdown import comparison_markdown
from kiprod.reports.run_archive import archive_inputs, input_paths, load_manifest
from kiprod.rfq.offer_review import (
    OfferDisposition,
    candidate_key,
    latest_offer_decisions,
    load_offer_decisions,
    record_offer_decision,
)
from kiprod.rfq.quote_import import QuoteImportResult, quote_source_preview_html


def _create_comparison(
    project: Project,
    input_files: list[Path],
    bom_path: Path,
    weights: ComparisonWeights | None = None,
) -> tuple[Comparison, Path]:
    if not input_files:
        raise ValueError("select at least one landed-cost JSON file")
    costs = [
        LandedCost.model_validate_json(path.read_text(encoding="utf-8")) for path in input_files
    ]
    normalized_bom = NormalizedBOM.model_validate_json(bom_path.read_text(encoding="utf-8"))
    required_mpns = {line.mpn for line in normalized_bom.lines if line.mpn}
    weights = weights or ComparisonWeights()
    result = compare(costs, required_mpns, weights)
    run_id = datetime.now(UTC).strftime("gui-%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    run_dir = project.root / "docs" / "production" / "quotes" / "runs" / run_id
    archive_inputs(
        input_files,
        bom_path,
        run_dir,
        comparison_weights=weights.model_dump(),
    )
    (run_dir / "comparison.md").write_text(comparison_markdown(result), encoding="utf-8")
    (run_dir / "comparison.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return result, run_dir


def _regenerate_comparison(run_dir: Path) -> Comparison:
    manifest = load_manifest(run_dir)
    inputs, bom_path = input_paths(run_dir, manifest)
    costs = [LandedCost.model_validate_json(path.read_text(encoding="utf-8")) for path in inputs]
    required_mpns: set[str] = set()
    if bom_path is not None:
        normalized_bom = NormalizedBOM.model_validate_json(bom_path.read_text(encoding="utf-8"))
        required_mpns = {line.mpn for line in normalized_bom.lines if line.mpn}
    weights = ComparisonWeights.model_validate(manifest.get("comparison_weights", {}))
    result = compare(costs, required_mpns, weights)
    (run_dir / "comparison.md").write_text(comparison_markdown(result), encoding="utf-8")
    (run_dir / "comparison.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return result


def _comparison_chart_html(comparison: Comparison) -> str:
    """Render dependency-free bar charts, keeping unlike quantity/currency groups apart."""
    if not comparison.rows:
        return "<html><body><p>No comparison rows are available.</p></body></html>"
    groups: dict[tuple[int, str], list[Any]] = {}
    for row in comparison.rows:
        groups.setdefault((row.board_quantity, row.currency), []).append(row)
    sections = [
        "<html><body><h1>Supplier comparison charts</h1>",
        "<p>Bars are scaled within each board quantity and currency group. "
        "Weighted score is lower-is-better; its bar shows score magnitude.</p>",
    ]

    def append_bar_row(label: str, width: float, color: str, value: str) -> str:
        return (
            "<tr><td width='170'>"
            f"{escape(label)}</td><td><table width='100%' cellspacing='0' cellpadding='0'>"
            f"<tr><td width='{width:.2f}%' bgcolor='{color}'>&nbsp;</td>"
            "<td>&nbsp;</td></tr></table></td><td align='right'>"
            f"{escape(value)}</td></tr>"
        )

    for (quantity, currency), rows in sorted(groups.items()):
        sections.append(f"<h2>{quantity} boards · {escape(currency)}</h2>")
        max_cost = max(float(row.per_board) for row in rows)
        max_score = max(row.ranking_score for row in rows)
        sections.append("<h3>Landed cost per board</h3><table width='100%'>")
        for row in rows:
            width = float(row.per_board) / max_cost * 100 if max_cost else 0
            sections.append(
                append_bar_row(row.supplier_id, width, "#3976b9", f"{row.per_board} {currency}")
            )
        sections.append("</table><h3>Weighted score (lower is better)</h3><table width='100%'>")
        for row in rows:
            width = row.ranking_score / max_score * 100 if max_score else 0
            sections.append(
                append_bar_row(row.supplier_id, width, "#cf8640", f"{row.ranking_score:.3f}")
            )
        sections.append("</table>")
    sections.append("</body></html>")
    return "".join(sections)


def _plugin_paths(project: Project) -> list[Path]:
    return [
        project.root / "docs" / "production" / "quotes" / "config" / "suppliers",
        Path.home() / ".config" / "kiprod" / "suppliers",
        Path(__file__).resolve().parent / "plugins" / "suppliers",
    ]


def _quote_results(project: Project) -> tuple[list[Path], list[tuple[Path, QuoteImportResult]]]:
    reply_root = project.root / "docs" / "production" / ".kiprod" / "replies"
    reply_paths: list[Path] = []
    if reply_root.is_dir():
        for path in sorted(reply_root.rglob("*.eml")):
            resolved = path.resolve()
            if resolved.is_relative_to(reply_root.resolve()) and resolved.is_file():
                reply_paths.append(resolved)

    quote_root = project.root / "docs" / "production" / "quotes"
    offer_results: list[tuple[Path, QuoteImportResult]] = []
    if quote_root.is_dir():
        for path in sorted(quote_root.rglob("*.json")):
            if "config" in path.relative_to(quote_root).parts:
                continue
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(quote_root.resolve()):
                    continue
                result = QuoteImportResult.model_validate_json(resolved.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            offer_results.append((resolved, result))
    return reply_paths, offer_results


def _evidence_path(project_root: Path, source_path: str) -> Path:
    root = project_root.resolve()
    candidate = (root / source_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("review evidence path escapes the selected project")
    return candidate


def _quote_source_path(project_root: Path, source_path: str) -> Path | None:
    production_root = (project_root / "docs" / "production").resolve()
    basename = Path(source_path).name
    if not basename:
        return None
    for candidate in sorted(production_root.rglob(basename)):
        resolved = candidate.resolve()
        if (
            resolved.is_relative_to(production_root)
            and resolved.is_file()
            and "config" not in candidate.relative_to(production_root).parts
        ):
            return resolved
    return None


def _qt() -> tuple[Any, ...]:
    try:
        from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal  # type: ignore[import-not-found]
        from PySide6.QtGui import QDesktopServices  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QApplication,
            QCheckBox,
            QComboBox,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QProgressBar,
            QPushButton,
            QSplitter,
            QTableWidget,
            QTableWidgetItem,
            QTabWidget,
            QTextBrowser,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise RuntimeError(
            "The desktop GUI requires PySide6. Install it with `./scripts/setup-gui.sh`."
        ) from exc
    return (
        QApplication,
        QObject,
        QThread,
        Qt,
        Signal,
        QDesktopServices,
        QUrl,
        QComboBox,
        QCheckBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSplitter,
        QTabWidget,
        QTextBrowser,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )


def _load_project(
    project_path: Path,
    variant: str | None,
    progress: Callable[[int, str], None] | None = None,
) -> tuple[
    Project,
    NormalizedBOM,
    ReviewReport,
    BoardSpec | None,
    AssemblySpec | None,
    Path,
    Path,
]:
    project = discover(project_path)
    if progress:
        progress(10, "Project discovered")
    if variant:
        if variant not in project.variants:
            raise ValueError(f"unknown project variant: {variant}")
        with TemporaryDirectory(prefix="kiprod-gui-variant-") as temporary:
            exported = export_bom(project.main_schematic, Path(temporary) / "variant.csv", variant)
            bom = build(project, exported_bom=exported)
    else:
        bom = build(project)
    if progress:
        progress(35, "Normalized BOM built")
    output_dir = project.root / "docs" / "production" / "bom"
    override_path = output_dir / "bom.user-overrides.json"
    bom = apply_bom_overrides(bom, load_bom_overrides(override_path))
    json_path, csv_path = write_bom(bom, output_dir)
    report = review_bom(bom)
    review_path = output_dir / "review.deterministic.json"
    review_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if progress:
        progress(60, "BOM and deterministic review saved")
    board_spec: BoardSpec | None = None
    assembly_spec: AssemblySpec | None = None
    if project.boards:
        if progress:
            progress(70, "Extracting board and assembly metrics")
        board_spec = extract_board(project.boards[0])
        notes = discover_fabrication_notes(project.root)
        boards_per_panel, panel_count_source = extract_boards_per_panel(notes)
        if boards_per_panel is not None:
            board_spec = board_spec.model_copy(
                update={
                    "boards_per_panel": boards_per_panel,
                    "panel_count_source": panel_count_source,
                }
            )
        assembly_spec = extract_assembly(project.boards[0])
        (output_dir / "board_assembly.json").write_text(
            json.dumps(
                {"board": board_spec.model_dump(), "assembly": assembly_spec.model_dump()},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif progress:
        progress(90, "No PCB found; board and assembly analysis skipped")
    if progress:
        progress(95, "Refreshing supplier and quote views")
    return project, bom, report, board_spec, assembly_spec, json_path, csv_path


def run_gui(project_path: Path | None = None) -> int:
    (
        QApplication,
        QObject,
        QThread,
        Qt,
        Signal,
        QDesktopServices,
        QUrl,
        QComboBox,
        QCheckBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSplitter,
        QTabWidget,
        QTextBrowser,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    ) = _qt()

    class ProjectWorker(QObject):  # type: ignore[valid-type,misc]
        completed = Signal(object)
        failed = Signal(str)
        progress = Signal(int, str)
        finished = Signal()

        def __init__(self, path: Path, variant: str | None) -> None:
            super().__init__()
            self.path = path
            self.variant = variant

        def run(self) -> None:
            try:
                self.completed.emit(
                    _load_project(self.path, self.variant, progress=self.progress.emit)
                )
            except Exception as exc:  # Surface file/tool errors in the status drawer.
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            finally:
                self.finished.emit()

    class MainWindow(QMainWindow):  # type: ignore[valid-type,misc]
        def __init__(self, initial_path: Path | None) -> None:
            super().__init__()
            self.setWindowTitle("KiProd — KiCad production workspace")
            self.resize(1180, 760)
            self.current_project: Project | None = None
            self.current_json_path: Path | None = None
            self.current_project_path: Path | None = None
            self.thread: Any = None
            self.worker: Any = None

            central = QWidget()
            root_layout = QVBoxLayout(central)
            run_bar = QHBoxLayout()
            self.project_field = QLineEdit(str(initial_path or Path.cwd()))
            self.project_field.setPlaceholderText("KiCad project directory or .kicad_pro file")
            browse_button = QPushButton("Browse…")
            self.variant_combo = QComboBox()
            self.variant_combo.addItem("Default variant", "")
            self.run_button = QPushButton("Build BOM and review")
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Ready")
            self.open_folder_button = QPushButton("Open output folder")
            self.open_folder_button.setEnabled(False)
            run_bar.addWidget(QLabel("Project"))
            run_bar.addWidget(self.project_field, 1)
            run_bar.addWidget(browse_button)
            run_bar.addWidget(self.variant_combo)
            run_bar.addWidget(self.run_button)
            run_bar.addWidget(self.progress_bar)
            run_bar.addWidget(self.open_folder_button)
            root_layout.addLayout(run_bar)

            splitter = QSplitter(Qt.Orientation.Vertical)
            self.tabs = QTabWidget()
            self.project_page = QPlainTextEdit()
            self.project_page.setReadOnly(True)
            self.plugins_table = QTableWidget(0, 3)
            self.plugins_table.setHorizontalHeaderLabels(["Supplier", "Resources", "Status"])
            self.plugins_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.plugins_table.currentCellChanged.connect(self.show_plugin_details)
            self.plugin_details = QPlainTextEdit()
            self.plugin_details.setReadOnly(True)
            self.plugin_settings_widget = QWidget()
            self.plugin_settings_layout = QFormLayout(self.plugin_settings_widget)
            self.plugin_settings_status = QLabel("Select a supplier to view its manifest settings.")
            self.save_plugin_settings_button = QPushButton("Save supplier settings")
            self.save_plugin_settings_button.clicked.connect(self.save_selected_plugin_settings)
            self.save_plugin_credentials_button = QPushButton("Save entered credentials to keyring")
            self.save_plugin_credentials_button.clicked.connect(
                self.save_selected_plugin_credentials
            )
            self.supplier_detail_tabs = QTabWidget()
            self.supplier_detail_tabs.addTab(self.plugin_details, "Overview")
            self.plugin_results_table = QTableWidget(0, 6)
            self.plugin_results_table.setHorizontalHeaderLabels(
                ["MPN", "Supplier PN", "Price breaks", "Currency", "Review", "Source"]
            )
            self.plugin_results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.supplier_detail_tabs.addTab(self.plugin_results_table, "Results")
            self.plugin_docs = QTextBrowser()
            self.plugin_docs.setOpenExternalLinks(False)
            self.supplier_detail_tabs.addTab(self.plugin_docs, "Docs")
            self.plugin_board_details = QPlainTextEdit()
            self.plugin_board_details.setReadOnly(True)
            self.supplier_detail_tabs.addTab(self.plugin_board_details, "Board Fab")
            self.plugin_assembly_details = QPlainTextEdit()
            self.plugin_assembly_details.setReadOnly(True)
            self.supplier_detail_tabs.addTab(self.plugin_assembly_details, "Assembly")
            supplier_settings_page = QWidget()
            supplier_details_layout = QVBoxLayout(supplier_settings_page)
            supplier_details_layout.addWidget(self.plugin_settings_widget)
            supplier_details_layout.addWidget(self.plugin_settings_status)
            supplier_details_layout.addWidget(self.save_plugin_settings_button)
            supplier_details_layout.addWidget(self.save_plugin_credentials_button)
            self.supplier_detail_tabs.addTab(supplier_settings_page, "Settings")
            supplier_details = QWidget()
            supplier_container_layout = QVBoxLayout(supplier_details)
            supplier_container_layout.addWidget(self.supplier_detail_tabs)
            self.quotes_tabs = QTabWidget()
            self.reply_table = QTableWidget(0, 2)
            self.reply_table.setHorizontalHeaderLabels(["Captured reply", "Path"])
            self.reply_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.reply_table.cellDoubleClicked.connect(self.open_reply)
            self.offer_table = QTableWidget(0, 4)
            self.offer_table.setHorizontalHeaderLabels(
                ["Offer file", "Supplier", "Offers", "Needs review"]
            )
            self.offer_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.offer_table.cellDoubleClicked.connect(self.open_offer_file)
            self.offer_table.currentCellChanged.connect(self.show_offer_details)
            self.offer_details = QPlainTextEdit()
            self.offer_details.setReadOnly(True)
            self.offer_correction = QPlainTextEdit()
            self.offer_correction.setPlaceholderText(
                "Edit the typed offer JSON, then save correction."
            )
            self.offer_candidate_combo = QComboBox()
            self.offer_candidate_combo.currentIndexChanged.connect(self.show_selected_offer)
            candidate_views = QTabWidget()
            self.offer_candidate_views = candidate_views
            candidate_views.addTab(self.offer_details, "Original candidate")
            candidate_views.addTab(self.offer_correction, "Correction")
            self.offer_review_queue_table = QTableWidget(0, 4)
            self.offer_review_queue_table.setHorizontalHeaderLabels(
                ["Source reference", "Confidence", "Issue", "Candidate MPN"]
            )
            self.offer_review_queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.offer_review_queue_table.cellDoubleClicked.connect(self.open_review_queue_source)
            self.offer_review_queue_table.currentCellChanged.connect(
                self.show_review_queue_evidence
            )
            candidate_views.addTab(self.offer_review_queue_table, "Review queue")
            self.offer_source_preview = QTextBrowser()
            self.offer_source_preview.setOpenExternalLinks(False)
            candidate_views.addTab(self.offer_source_preview, "Source evidence")
            self.offer_review_comment = QLineEdit()
            self.offer_review_comment.setPlaceholderText(
                "Comment (required for correction/rejection)"
            )
            self.offer_review_status = QLabel("Select an imported offer candidate.")
            self.open_quote_source_button = QPushButton("Open cited quote file")
            self.open_quote_source_button.clicked.connect(self.open_selected_quote_source)
            offer_actions = QHBoxLayout()
            for label, disposition in (
                ("Confirm", "confirmed"),
                ("Save correction", "corrected"),
                ("Reject", "rejected"),
            ):
                button = QPushButton(label)
                button.clicked.connect(
                    lambda _checked=False, choice=disposition: self.decide_selected_offer(choice)
                )
                offer_actions.addWidget(button)
            offer_panel = QWidget()
            offer_panel_layout = QVBoxLayout(offer_panel)
            offer_panel_layout.addWidget(self.offer_candidate_combo)
            offer_panel_layout.addWidget(candidate_views, 1)
            offer_panel_layout.addWidget(self.offer_review_comment)
            offer_panel_layout.addWidget(self.offer_review_status)
            offer_panel_layout.addWidget(self.open_quote_source_button)
            offer_panel_layout.addLayout(offer_actions)
            offer_splitter = QSplitter(Qt.Orientation.Horizontal)
            offer_splitter.addWidget(self.offer_table)
            offer_splitter.addWidget(offer_panel)
            offer_splitter.setSizes([500, 500])
            self.quotes_tabs.addTab(self.reply_table, "Captured replies")
            self.quotes_tabs.addTab(offer_splitter, "Imported offers")
            self.board_table = QTableWidget(0, 2)
            self.board_table.setHorizontalHeaderLabels(["Board metric", "Value"])
            self.board_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.assembly_table = QTableWidget(0, 2)
            self.assembly_table.setHorizontalHeaderLabels(["Assembly metric", "Value"])
            self.assembly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.board_checks_table = QTableWidget(0, 5)
            self.board_checks_table.setHorizontalHeaderLabels(
                ["Supplier", "Status", "Metric", "Project value", "Supplier limit"]
            )
            self.board_checks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            board_page = QTabWidget()
            board_page.addTab(self.board_table, "Extracted metrics")
            board_page.addTab(self.board_checks_table, "Supplier checks")
            self.assembly_checks_table = QTableWidget(0, 5)
            self.assembly_checks_table.setHorizontalHeaderLabels(
                ["Supplier", "Status", "Metric", "Project value", "Supplier limit"]
            )
            self.assembly_checks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            assembly_page = QTabWidget()
            assembly_page.addTab(self.assembly_table, "Extracted metrics")
            assembly_page.addTab(self.assembly_checks_table, "Supplier checks")
            self.bom_table = QTableWidget(0, 6)
            self.bom_table.setHorizontalHeaderLabels(
                ["References", "Qty", "Value", "Footprint", "MPN", "MPN source"]
            )
            self.bom_table.setEditTriggers(
                QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
            )
            self.bom_table.horizontalHeader().setStretchLastSection(True)
            bom_page = QWidget()
            bom_layout = QVBoxLayout(bom_page)
            bom_actions = QHBoxLayout()
            self.bom_filter = QCheckBox("Only show lines needing MPN or footprint review")
            self.bom_filter.toggled.connect(self.filter_bom_lines)
            self.save_bom_button = QPushButton("Save MPN changes")
            self.save_bom_button.clicked.connect(self.save_bom_edits)
            bom_actions.addWidget(self.bom_filter)
            bom_actions.addStretch(1)
            bom_actions.addWidget(self.save_bom_button)
            bom_layout.addLayout(bom_actions)
            bom_layout.addWidget(self.bom_table, 1)
            self.review_table = QTableWidget(0, 6)
            self.review_table.setHorizontalHeaderLabels(
                ["Severity", "Code", "References", "Finding", "Suggested action", "Decision"]
            )
            self.review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.review_table.horizontalHeader().setStretchLastSection(True)
            self.review_table.currentCellChanged.connect(self.show_finding_details)
            review_page = QWidget()
            review_layout = QVBoxLayout(review_page)
            review_splitter = QSplitter(Qt.Orientation.Horizontal)
            review_splitter.addWidget(self.review_table)
            decision_panel = QWidget()
            decision_layout = QVBoxLayout(decision_panel)
            self.review_details = QPlainTextEdit()
            self.review_details.setReadOnly(True)
            self.review_comment = QLineEdit()
            self.review_comment.setPlaceholderText("Review comment (required for dismiss/defer)")
            decision_layout.addWidget(self.review_details, 1)
            decision_layout.addWidget(self.review_comment)
            self.open_evidence_button = QPushButton("Open source evidence")
            self.open_evidence_button.clicked.connect(self.open_selected_evidence)
            decision_layout.addWidget(self.open_evidence_button)
            decision_buttons = QHBoxLayout()
            for label, disposition in (
                ("Accept", "accept"),
                ("Dismiss", "dismiss"),
                ("Defer", "defer"),
            ):
                button = QPushButton(label)
                button.clicked.connect(
                    lambda _checked=False, choice=disposition: self.record_selected_review(choice)
                )
                decision_buttons.addWidget(button)
            decision_layout.addLayout(decision_buttons)
            review_splitter.addWidget(decision_panel)
            review_splitter.setSizes([700, 480])
            review_layout.addWidget(review_splitter)
            self.reports_list = QTableWidget(0, 2)
            self.reports_list.setHorizontalHeaderLabels(["Artifact", "Path"])
            self.reports_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.reports_list.cellDoubleClicked.connect(self.open_report)
            reports_page = QWidget()
            reports_layout = QVBoxLayout(reports_page)
            self.regenerate_button = QPushButton("Regenerate selected saved comparison")
            self.regenerate_button.clicked.connect(self.regenerate_selected_report)
            reports_layout.addWidget(self.regenerate_button)
            reports_layout.addWidget(self.reports_list, 1)
            compare_page = QWidget()
            self.compare_page = compare_page
            compare_layout = QVBoxLayout(compare_page)
            compare_actions = QHBoxLayout()
            self.compare_button = QPushButton("Compare saved landed-cost files…")
            self.compare_button.clicked.connect(self.choose_comparison_inputs)
            compare_actions.addWidget(self.compare_button)
            compare_actions.addWidget(QLabel("Price weight"))
            self.compare_price_weight = QLineEdit("1")
            self.compare_price_weight.setMaximumWidth(60)
            compare_actions.addWidget(self.compare_price_weight)
            compare_actions.addWidget(QLabel("Lead-time weight"))
            self.compare_lead_weight = QLineEdit("0")
            self.compare_lead_weight.setMaximumWidth(60)
            compare_actions.addWidget(self.compare_lead_weight)
            compare_actions.addStretch(1)
            compare_layout.addLayout(compare_actions)
            self.comparison_table = QTableWidget(0, 14)
            self.comparison_table.setHorizontalHeaderLabels(
                [
                    "Rank",
                    "Supplier",
                    "Boards",
                    "Currency",
                    "Total",
                    "Per board",
                    "Parts",
                    "Shipping",
                    "NRE",
                    "Duty",
                    "Fees",
                    "Lead days",
                    "Score",
                    "Lines",
                ]
            )
            self.comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.best_mix_table = QTableWidget(0, 9)
            self.best_mix_table.setHorizontalHeaderLabels(
                [
                    "Boards",
                    "MPN",
                    "Supplier",
                    "Supplier PN",
                    "Parts cost",
                    "Source",
                    "Mix total",
                    "Per board",
                    "Coverage gaps",
                ]
            )
            self.best_mix_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.comparison_chart = QTextBrowser()
            self.comparison_chart.setOpenExternalLinks(False)
            self.writeback_button = QPushButton("Review and write best-mix fields to schematic…")
            self.writeback_button.setEnabled(False)
            self.writeback_button.clicked.connect(self.approve_best_mix_writeback)
            compare_layout.addWidget(self.writeback_button)
            self.comparison_views = QTabWidget()
            self.comparison_views.addTab(self.comparison_table, "Supplier ranking")
            self.comparison_views.addTab(self.best_mix_table, "Best mix")
            self.comparison_views.addTab(self.comparison_chart, "Charts")
            compare_layout.addWidget(self.comparison_views, 1)
            self.coverage_label = QLabel("Choose saved landed-cost JSON files to compare.")
            compare_layout.addWidget(self.coverage_label)
            settings_page = QWidget()
            settings_layout = QFormLayout(settings_page)
            self.settings_quantity = QLineEdit()
            self.settings_paths = QPlainTextEdit()
            self.settings_paths.setReadOnly(True)
            self.save_settings_button = QPushButton("Save project settings")
            self.save_settings_button.clicked.connect(self.save_settings)
            settings_layout.addRow("Board quantities", self.settings_quantity)
            settings_layout.addRow("Effective paths", self.settings_paths)
            settings_layout.addRow(self.save_settings_button)
            self.tabs.addTab(self.project_page, "Project")
            self.tabs.addTab(bom_page, "BOM & Specs")
            self.tabs.addTab(review_page, "Review")
            self.tabs.addTab(board_page, "Boards")
            self.tabs.addTab(assembly_page, "Assembly")
            supplier_splitter = QSplitter(Qt.Orientation.Horizontal)
            supplier_splitter.addWidget(self.plugins_table)
            supplier_splitter.addWidget(supplier_details)
            self.tabs.addTab(supplier_splitter, "Components")
            self.tabs.addTab(self.quotes_tabs, "Quotes Inbox")
            self.tabs.addTab(compare_page, "Compare")
            self.tabs.addTab(reports_page, "Reports")
            self.tabs.addTab(settings_page, "Settings")
            splitter.addWidget(self.tabs)
            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setPlaceholderText("Run progress and warnings appear here.")
            self.log.setMaximumBlockCount(1000)
            splitter.addWidget(self.log)
            splitter.setSizes([540, 170])
            root_layout.addWidget(splitter, 1)
            self.setCentralWidget(central)

            browse_button.clicked.connect(self.browse_project)
            self.run_button.clicked.connect(self.start_run)
            self.open_folder_button.clicked.connect(self.open_output_folder)
            self.statusBar().showMessage("Choose a KiCad project to get started.")
            if initial_path is not None:
                self.start_run()

        def browse_project(self) -> None:
            selected = QFileDialog.getExistingDirectory(
                self, "Select KiCad project folder", self.project_field.text()
            )
            if selected:
                self.project_field.setText(selected)

        def start_run(self) -> None:
            path_text = self.project_field.text().strip()
            if not path_text:
                QMessageBox.warning(self, "Project required", "Select a KiCad project folder.")
                return
            project_path = Path(path_text).expanduser()
            same_project = (
                self.current_project_path is not None
                and project_path.resolve() == self.current_project_path.resolve()
            )
            variant = self.variant_combo.currentData() if same_project else None
            self.run_button.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Starting…")
            self.statusBar().showMessage("Building normalized BOM and deterministic review…")
            self.log.appendPlainText(f"Loading project: {project_path}")
            self.thread = QThread(self)
            self.worker = ProjectWorker(project_path, variant or None)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.completed.connect(self.on_completed)
            self.worker.failed.connect(self.on_failed)
            self.worker.progress.connect(self.on_progress)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.finished.connect(self.on_finished)
            self.thread.start()

        def on_completed(self, result: object) -> None:
            project, bom, report, board_spec, assembly_spec, json_path, _csv_path = cast(
                tuple[
                    Project,
                    NormalizedBOM,
                    ReviewReport,
                    BoardSpec | None,
                    AssemblySpec | None,
                    Path,
                    Path,
                ],
                result,
            )
            self.current_project = project
            self.current_project_path = project.root
            self.current_json_path = json_path
            self.current_bom = bom
            self.current_board_spec = board_spec
            self.current_assembly_spec = assembly_spec
            self.bom_override_path = (
                project.root / "docs" / "production" / "bom" / "bom.user-overrides.json"
            )
            self.current_findings = report.findings
            self.review_decision_path = (
                project.root / "docs" / "production" / "bom" / "review.decisions.json"
            )
            self.refresh_settings(project)
            selected_variant = self.variant_combo.currentData()
            self.variant_combo.blockSignals(True)
            self.variant_combo.clear()
            self.variant_combo.addItem("Default variant", "")
            for variant in project.variants:
                self.variant_combo.addItem(variant, variant)
            if selected_variant:
                selected_index = self.variant_combo.findData(selected_variant)
                if selected_index >= 0:
                    self.variant_combo.setCurrentIndex(selected_index)
            self.variant_combo.blockSignals(False)
            self.project_page.setPlainText(
                "Project: "
                + str(project.pro_file)
                + f"\nSchematics: {len(project.schematics)}"
                + f"\nBoards: {len(project.boards)}"
                + "\nVariants: "
                + (", ".join(project.variants) or "none")
                + f"\nHashed inputs: {len(project.input_hashes)}"
                + "\n\nInput SHA-256 hashes:\n"
                + "\n".join(
                    f"{name}  {digest}" for name, digest in sorted(project.input_hashes.items())
                )
            )
            self.bom_table.setRowCount(len(bom.lines))
            for row, line in enumerate(bom.lines):
                mpn_source = line.resolved_fields.get("mpn")
                source_label = (
                    mpn_source.source
                    if mpn_source
                    else "imported BOM"
                    if bom.imported_bom
                    else "schematic"
                    if line.mpn
                    else "missing"
                )
                values = [
                    ", ".join(line.references),
                    str(line.quantity),
                    line.value,
                    line.footprint,
                    line.mpn or "",
                    source_label,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column != 4:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.bom_table.setItem(row, column, item)
            self.refresh_review_view(bom, report)
            self.refresh_review_decisions()
            self._fill_metrics(self.board_table, board_spec.model_dump() if board_spec else {})
            self._fill_metrics(
                self.assembly_table,
                assembly_spec.model_dump() if assembly_spec else {},
            )
            self.refresh_quote_files(project)
            self.refresh_plugins(project)
            self.refresh_supplier_checks(board_spec, assembly_spec)
            self.refresh_reports()
            self.open_folder_button.setEnabled(True)
            self.log.appendPlainText(
                f"Wrote {json_path}; reviewed {len(bom.lines)} BOM lines and found "
                f"{len(report.findings)} deterministic findings."
            )
            self.statusBar().showMessage(f"Ready — {len(bom.lines)} BOM lines")
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Complete")
            if not project.boards:
                self.log.appendPlainText(
                    "WARNING: No PCB found; board and assembly views are empty."
                )

        def refresh_review_view(self, bom: NormalizedBOM, report: ReviewReport) -> None:
            self.review_table.setRowCount(len(report.findings))
            for row, finding in enumerate(report.findings):
                references = ", ".join(
                    reference
                    for line in bom.lines
                    if line.line_id in finding.line_ids
                    for reference in line.references
                )
                values = [
                    finding.severity,
                    finding.code,
                    references,
                    finding.summary,
                    finding.suggested_action or "",
                    "Open",
                ]
                for column, value in enumerate(values):
                    self.review_table.setItem(row, column, QTableWidgetItem(value))

        def on_progress(self, value: int, message: str) -> None:
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(message)
            self.statusBar().showMessage(message)

        def filter_bom_lines(self, enabled: bool) -> None:
            bom = getattr(self, "current_bom", None)
            if bom is None:
                return
            for row, line in enumerate(bom.lines):
                self.bom_table.setRowHidden(
                    row, enabled and bool(line.mpn) and bool(line.footprint)
                )

        def save_bom_edits(self) -> None:
            bom = getattr(self, "current_bom", None)
            if bom is None or self.current_project_path is None:
                return
            try:
                existing = load_bom_overrides(self.bom_override_path)
                overrides = dict(existing.mpn)
                for row, line in enumerate(bom.lines):
                    item = self.bom_table.item(row, 4)
                    value = item.text().strip() if item is not None else ""
                    normalized = value or None
                    prior = line.resolved_fields.get("mpn")
                    if normalized != line.mpn or (prior is not None and prior.source == "user"):
                        overrides[line.line_id] = normalized
                    else:
                        overrides.pop(line.line_id, None)
                saved = BOMOverrides(mpn=overrides)
                save_bom_overrides(self.bom_override_path, saved)
                updated = apply_bom_overrides(bom, saved)
                output_dir = self.current_project_path / "docs" / "production" / "bom"
                json_path, _csv_path = write_bom(updated, output_dir)
                report = review_bom(updated)
                (output_dir / "review.deterministic.json").write_text(
                    report.model_dump_json(indent=2) + "\n", encoding="utf-8"
                )
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "BOM changes were not saved", str(exc))
                return
            self.current_bom = updated
            self.current_json_path = json_path
            self.current_findings = report.findings
            self.refresh_bom_view(updated)
            self.refresh_review_view(updated, report)
            self.refresh_review_decisions()
            self.refresh_reports()
            self.log.appendPlainText(f"Saved user MPN overrides: {self.bom_override_path}")
            self.statusBar().showMessage("BOM MPN changes saved")

        def refresh_bom_view(self, bom: NormalizedBOM) -> None:
            self.bom_table.setRowCount(len(bom.lines))
            for row, line in enumerate(bom.lines):
                resolved = line.resolved_fields.get("mpn")
                source = (
                    resolved.source
                    if resolved
                    else "imported BOM"
                    if bom.imported_bom
                    else "schematic"
                    if line.mpn
                    else "missing"
                )
                values = [
                    ", ".join(line.references),
                    str(line.quantity),
                    line.value,
                    line.footprint,
                    line.mpn or "",
                    source,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column != 4:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.bom_table.setItem(row, column, item)
            self.filter_bom_lines(self.bom_filter.isChecked())

        def refresh_review_decisions(self) -> None:
            try:
                dispositions = latest_dispositions(load_decisions(self.review_decision_path))
            except (OSError, ValueError) as exc:
                self.log.appendPlainText(f"WARNING: review decision file is invalid: {exc}")
                dispositions = {}
            for row, finding in enumerate(self.current_findings):
                item = self.review_table.item(row, 5)
                if item is not None:
                    item.setText(dispositions.get(finding_key(finding), "Open"))

        def show_finding_details(
            self, row: int, column: int, previous_row: int, previous_column: int
        ) -> None:
            del column, previous_row, previous_column
            findings = getattr(self, "current_findings", [])
            if not 0 <= row < len(findings):
                self.review_details.clear()
                return
            finding: ReviewFinding = findings[row]
            evidence = [
                f"{source.path}" + (f"#{source.reference}" if source.reference else "")
                for source in finding.evidence
            ]
            self.review_details.setPlainText(
                f"{finding.severity.upper()} — {finding.code}\n\n{finding.summary}\n\n"
                f"Suggested action: {finding.suggested_action or '(none)'}\n"
                f"BOM line IDs: {', '.join(finding.line_ids) or '(none)'}\n"
                f"Source: {finding.source}; provider: {finding.provider or '(rule)'}; "
                f"model: {finding.model or '(none)'}; "
                f"prompt: {finding.prompt_version or '(none)'}\n\n"
                "Evidence:\n" + ("\n".join(evidence) or "(no source evidence recorded)")
            )

        def record_selected_review(self, disposition: str) -> None:
            row = self.review_table.currentRow()
            findings = getattr(self, "current_findings", [])
            if not 0 <= row < len(findings):
                QMessageBox.information(self, "Select a finding", "Select a review finding first.")
                return
            try:
                result = record_decision(
                    self.review_decision_path,
                    findings[row],
                    cast(Disposition, disposition),
                    self.review_comment.text(),
                )
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Review decision was not saved", str(exc))
                return
            latest = latest_dispositions(result)
            item = self.review_table.item(row, 5)
            if item is not None:
                item.setText(latest[finding_key(findings[row])])
            self.review_comment.clear()
            self.log.appendPlainText(
                f"Recorded {disposition} for {findings[row].code} in {self.review_decision_path}"
            )

        def open_selected_evidence(self) -> None:
            row = self.review_table.currentRow()
            findings = getattr(self, "current_findings", [])
            if self.current_project_path is None or not 0 <= row < len(findings):
                return
            sources = findings[row].evidence
            if not sources:
                QMessageBox.information(
                    self, "No source evidence", "This finding has no recorded source file."
                )
                return
            try:
                source = _evidence_path(self.current_project_path, sources[0].path)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid evidence path", str(exc))
                return
            if not source.is_file():
                QMessageBox.warning(self, "Evidence file not found", str(source))
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(source)))

        def refresh_settings(self, project: Project) -> None:
            try:
                settings = load(project.root)
            except ConfigError as exc:
                self.settings_quantity.clear()
                self.settings_paths.setPlainText(f"Configuration error:\n{exc}")
                self.save_settings_button.setEnabled(False)
                self.log.appendPlainText(f"WARNING: project settings could not be loaded: {exc}")
                return
            self.save_settings_button.setEnabled(True)
            self.settings_quantity.setText(", ".join(map(str, settings.quantities.boards)))
            self.settings_paths.setPlainText(
                f"Production: {settings.paths.production}\n"
                f"Configuration: {settings.paths.config}\n"
                f"Local state: {settings.paths.state}\n\n"
                "Only board quantities are editable here. Other settings and unknown TOML keys "
                "are preserved. Secrets belong in the operating system keyring."
            )

        def save_settings(self) -> None:
            if self.current_project is None:
                return
            try:
                quantities = parse_quantities(self.settings_quantity.text())
                config_path = save_project_quantities(self.current_project.root, quantities)
            except (ConfigError, OSError) as exc:
                QMessageBox.critical(self, "Settings were not saved", str(exc))
                return
            self.log.appendPlainText(f"Saved project settings: {config_path}")
            self.statusBar().showMessage("Project settings saved")
            self.refresh_settings(self.current_project)

        @staticmethod
        def _fill_metrics(table: Any, metrics: dict[str, Any]) -> None:
            table.setRowCount(len(metrics))
            for row, (name, value) in enumerate(metrics.items()):
                table.setItem(row, 0, QTableWidgetItem(name.replace("_", " ").title()))
                table.setItem(row, 1, QTableWidgetItem(json.dumps(value, sort_keys=True)))

        def refresh_plugins(self, project: Project) -> None:
            self.plugins_table.setRowCount(0)
            self.plugin_details.clear()
            self.plugin_results_table.setRowCount(0)
            self.plugin_docs.setMarkdown("Select a supplier to view its local documentation.")
            self.plugin_board_details.clear()
            self.plugin_assembly_details.clear()
            self.plugins = []
            self.save_plugin_settings_button.setEnabled(False)
            self.save_plugin_credentials_button.setEnabled(False)
            self.plugin_settings_status.setText("No supplier selected.")
            try:
                plugins = discover_plugins(_plugin_paths(project))
            except PluginError as exc:
                self.plugin_details.setPlainText(f"Plugin discovery failed:\n{exc}")
                return
            self.plugins = plugins
            self.plugins_table.setRowCount(len(plugins))
            if not plugins:
                self.plugin_details.setPlainText(
                    "No supplier plugins are installed. Add a validated plugin under the project "
                    "or user supplier configuration folder."
                )
                return
            for row, plugin in enumerate(plugins):
                manifest = plugin.manifest
                resources = ", ".join(manifest.resource_types) or "unspecified"
                values = [manifest.name, resources, "Manifest found"]
                for column, value in enumerate(values):
                    self.plugins_table.setItem(row, column, QTableWidgetItem(value))
            self.plugins_table.selectRow(0)

        def refresh_supplier_checks(
            self, board_spec: BoardSpec | None, assembly_spec: AssemblySpec | None
        ) -> None:
            self._fill_capability_checks(
                self.board_checks_table, board_spec, "pcb_fab", check_board
            )
            self._fill_capability_checks(
                self.assembly_checks_table, assembly_spec, "pcb_assembly", check_assembly
            )

        def _fill_capability_checks(
            self, table: Any, spec: Any, capability: str, checker: Any
        ) -> None:
            table.setRowCount(0)
            if spec is None:
                return
            plugins = getattr(self, "plugins", [])
            matching = [
                plugin
                for plugin in plugins
                if isinstance(plugin.manifest.capabilities.get(capability), dict)
            ]
            if not matching:
                table.setRowCount(1)
                table.setItem(0, 0, QTableWidgetItem("(none configured)"))
                table.setItem(0, 1, QTableWidgetItem("No supplier capability manifest"))
                return
            rows: list[list[str]] = []
            for plugin in matching:
                findings = checker(spec, plugin.manifest)
                if findings:
                    for finding in findings:
                        rows.append(
                            [
                                plugin.manifest.name,
                                "Review",
                                finding.field,
                                str(finding.required),
                                str(finding.limit),
                            ]
                        )
                else:
                    rows.append(
                        [
                            plugin.manifest.name,
                            "No reported violation",
                            "",
                            "",
                            "",
                        ]
                    )
            table.setRowCount(len(rows))
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    table.setItem(row, column, QTableWidgetItem(value))

        def show_plugin_details(
            self, row: int, column: int, previous_row: int, previous_column: int
        ) -> None:
            del column, previous_row, previous_column
            plugins = getattr(self, "plugins", [])
            if row < 0 or row >= len(plugins):
                return
            manifest: Manifest = plugins[row].manifest
            self.selected_plugin_row = row
            settings = [
                f"{field.get('label', field.get('key', 'Field'))} "
                f"({field.get('key', '')}; {field.get('type', 'string')})"
                for field in manifest.fields
            ]
            credential_labels = [
                f"{credential.label} ({credential.key}): keyring-backed"
                for credential in manifest.credentials
            ]
            capabilities = json.dumps(manifest.capabilities, indent=2, sort_keys=True)
            self.plugin_details.setPlainText(
                f"{manifest.name} ({manifest.id})\nVersion: {manifest.version}\n"
                f"Resources: {', '.join(manifest.resource_types) or 'unspecified'}\n\n"
                "Settings fields from manifest:\n"
                + ("\n".join(settings) or "(none)")
                + "\n\nCredential labels (values are never shown):\n"
                + ("\n".join(credential_labels) or "(none)")
                + "\n\nCapabilities:\n"
                + capabilities
            )
            self.refresh_plugin_results(manifest.id)
            self.refresh_plugin_docs(plugins[row].path)
            self.refresh_plugin_capability_views(manifest)
            self._build_plugin_settings_form(manifest)

        def refresh_plugin_capability_views(self, manifest: Manifest) -> None:
            for capability, spec, checker, view, title in (
                (
                    "pcb_fab",
                    getattr(self, "current_board_spec", None),
                    check_board,
                    self.plugin_board_details,
                    "Board fabrication",
                ),
                (
                    "pcb_assembly",
                    getattr(self, "current_assembly_spec", None),
                    check_assembly,
                    self.plugin_assembly_details,
                    "Assembly",
                ),
            ):
                declared = manifest.capabilities.get(capability)
                if not isinstance(declared, dict):
                    view.setPlainText(f"{manifest.name} does not declare {title} capability.")
                elif spec is None:
                    view.setPlainText(f"No project {title.lower()} metrics are available.")
                else:
                    findings = checker(spec, manifest)
                    view.setPlainText(
                        f"Supplier: {manifest.name} ({manifest.id})\n"
                        f"Capability: {capability}\n\nDeclared supplier limits:\n"
                        f"{json.dumps(declared.get('limits', {}), indent=2, sort_keys=True)}"
                        f"\n\nProject metrics:\n"
                        f"{json.dumps(spec.model_dump(), indent=2, sort_keys=True)}"
                        "\n\nCompatibility findings:\n"
                        + (
                            "\n".join(f"• {finding.message}" for finding in findings)
                            if findings
                            else "No violations reported by the declared limits."
                        )
                    )

        def refresh_plugin_results(self, supplier_id: str) -> None:
            results = [
                (path, result)
                for path, result in getattr(self, "offer_results", [])
                if result.supplier_id == supplier_id
            ]
            rows = [(path, candidate) for path, result in results for candidate in result.offers]
            self.plugin_results_table.setRowCount(len(rows))
            for row, (path, candidate) in enumerate(rows):
                offer = candidate.offer
                values = [
                    offer.manufacturer_part_number,
                    offer.supplier_part_number or "",
                    json.dumps([item.model_dump() for item in offer.price_breaks]),
                    offer.currency,
                    "Review required" if candidate.requires_review else "Imported",
                    f"{path.name}: {offer.source_ref or ''}",
                ]
                for column, value in enumerate(values):
                    self.plugin_results_table.setItem(row, column, QTableWidgetItem(value))
            if not rows:
                self.plugin_results_table.setRowCount(1)
                self.plugin_results_table.setItem(
                    0, 0, QTableWidgetItem("No imported offers for this supplier.")
                )

        def refresh_plugin_docs(self, plugin_path: Path) -> None:
            readme = (plugin_path / "README.md").resolve()
            try:
                readme.relative_to(plugin_path.resolve())
                content = readme.read_text(encoding="utf-8") if readme.is_file() else ""
            except (OSError, ValueError):
                content = ""
            self.plugin_docs.setMarkdown(
                content or "No local README.md is available for this supplier."
            )

        def _build_plugin_settings_form(self, manifest: Manifest) -> None:
            while self.plugin_settings_layout.count():
                item = self.plugin_settings_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.plugin_setting_widgets: dict[str, tuple[dict[str, object], Any]] = {}
            self.plugin_credential_widgets: dict[str, Any] = {}
            credential_labels: dict[str, str] = {}
            if self.current_project_path is None:
                self.save_plugin_settings_button.setEnabled(False)
                return
            try:
                saved = load_plugin_settings(self.current_project_path, manifest.id)
            except (OSError, ValueError) as exc:
                self.plugin_settings_status.setText(f"Could not load settings: {exc}")
                self.save_plugin_settings_button.setEnabled(False)
                return
            for descriptor in manifest.fields:
                key = str(descriptor["key"])
                kind = descriptor.get("type", "string")
                if kind == "secret":
                    credential_labels[key] = str(descriptor.get("label", key))
                    continue
                value = saved.get(key, descriptor.get("default"))
                if kind == "bool":
                    widget = QCheckBox()
                    widget.setChecked(value if isinstance(value, bool) else False)
                elif kind == "enum":
                    widget = QComboBox()
                    options = descriptor.get("options", [])
                    if isinstance(options, list):
                        for option in options:
                            if isinstance(option, dict):
                                option_value = str(option.get("value", option.get("label", "")))
                                option_label = str(option.get("label", option_value))
                            else:
                                option_value = str(option)
                                option_label = option_value
                            widget.addItem(option_label, option_value)
                    if value is not None:
                        index = widget.findData(str(value))
                        if index >= 0:
                            widget.setCurrentIndex(index)
                elif kind in {"table", "group"}:
                    widget = QLabel("Complex field; configure through the plugin documentation.")
                else:
                    widget = QLineEdit(
                        ", ".join(map(str, value))
                        if isinstance(value, list)
                        else ""
                        if value is None
                        else str(value)
                    )
                help_text = descriptor.get("help")
                if isinstance(help_text, str):
                    widget.setToolTip(help_text)
                label = str(descriptor.get("label", key))
                if descriptor.get("required", False):
                    label += " *"
                self.plugin_settings_layout.addRow(label, widget)
                if kind not in {"table", "group"}:
                    self.plugin_setting_widgets[key] = (descriptor, widget)
            keyring_ready = True
            for credential in manifest.credentials:
                credential_labels[credential.key] = credential.label
            for credential_key, credential_label in credential_labels.items():
                editor = QLineEdit()
                editor.setEchoMode(QLineEdit.EchoMode.Password)
                editor.setPlaceholderText("Enter new value; saved value is never displayed")
                status = QLabel()
                try:
                    configured = has_credential(manifest.id, credential_key)
                    status.setText("Stored in OS keyring" if configured else "Not configured")
                except CredentialStoreUnavailable as exc:
                    keyring_ready = False
                    status.setText(str(exc))
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(editor, 1)
                row_layout.addWidget(status)
                self.plugin_settings_layout.addRow(credential_label, row_widget)
                self.plugin_credential_widgets[credential_key] = editor
            self.plugin_settings_status.setText(
                "Credential values are kept out of project files and application logs."
            )
            self.save_plugin_settings_button.setEnabled(True)
            self.save_plugin_credentials_button.setEnabled(
                bool(manifest.credentials) and keyring_ready
            )

        def save_selected_plugin_settings(self) -> None:
            plugins = getattr(self, "plugins", [])
            row = getattr(self, "selected_plugin_row", -1)
            if self.current_project_path is None or not 0 <= row < len(plugins):
                return
            manifest: Manifest = plugins[row].manifest
            values: dict[str, object] = {}
            try:
                for key, (descriptor, widget) in self.plugin_setting_widgets.items():
                    kind = descriptor.get("type", "string")
                    if kind == "bool":
                        values[key] = widget.isChecked()
                    elif kind == "enum":
                        values[key] = widget.currentData()
                    else:
                        text = widget.text().strip()
                        if not text:
                            values[key] = None
                        elif kind == "int":
                            values[key] = int(text)
                        elif kind == "float":
                            values[key] = float(text)
                        elif kind == "multi_enum":
                            values[key] = [part.strip() for part in text.split(",") if part.strip()]
                        else:
                            values[key] = text
                path = save_plugin_settings(self.current_project_path, manifest, values)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Supplier settings were not saved", str(exc))
                return
            self.plugin_settings_status.setText(f"Saved locally: {path}")
            self.log.appendPlainText(f"Saved supplier settings for {manifest.id}: {path}")

        def save_selected_plugin_credentials(self) -> None:
            plugins = getattr(self, "plugins", [])
            row = getattr(self, "selected_plugin_row", -1)
            if not 0 <= row < len(plugins):
                return
            manifest: Manifest = plugins[row].manifest
            entered = {
                key: widget.text()
                for key, widget in self.plugin_credential_widgets.items()
                if widget.text()
            }
            if not entered:
                QMessageBox.information(
                    self, "No credentials entered", "Enter a credential value first."
                )
                return
            try:
                for key, value in entered.items():
                    save_credential(manifest.id, key, value)
            except (CredentialStoreUnavailable, OSError, ValueError) as exc:
                QMessageBox.critical(self, "Credential was not saved", str(exc))
                return
            for widget in self.plugin_credential_widgets.values():
                widget.clear()
            self.log.appendPlainText(f"Saved credential(s) to OS keyring for {manifest.id}")
            self._build_plugin_settings_form(manifest)

        def refresh_quote_files(self, project: Project) -> None:
            reply_paths, offer_results = _quote_results(project)
            self.reply_table.setRowCount(len(reply_paths))
            for row, path in enumerate(reply_paths):
                self.reply_table.setItem(row, 0, QTableWidgetItem(path.name))
                self.reply_table.setItem(row, 1, QTableWidgetItem(str(path)))

            self.offer_results = offer_results
            self.offer_decision_path = (
                project.root / "docs" / "production" / "quotes" / "review.decisions.json"
            )
            try:
                self.offer_decisions = latest_offer_decisions(
                    load_offer_decisions(self.offer_decision_path)
                )
            except (OSError, ValueError) as exc:
                self.offer_decisions = {}
                self.log.appendPlainText(f"WARNING: quote decision log is invalid: {exc}")
            self.offer_table.setRowCount(len(offer_results))
            for row, (path, result) in enumerate(offer_results):
                self.offer_table.setItem(row, 0, QTableWidgetItem(path.name))
                self.offer_table.setItem(row, 1, QTableWidgetItem(result.supplier_id))
                self.offer_table.setItem(row, 2, QTableWidgetItem(str(len(result.offers))))
                needs_review = len(result.review_queue) + sum(
                    candidate.requires_review for candidate in result.offers
                )
                self.offer_table.setItem(row, 3, QTableWidgetItem(str(needs_review)))
            plugins = getattr(self, "plugins", [])
            selected_row = getattr(self, "selected_plugin_row", -1)
            if 0 <= selected_row < len(plugins):
                self.refresh_plugin_results(plugins[selected_row].manifest.id)

        def open_reply(self, row: int, column: int) -> None:
            del column
            item = self.reply_table.item(row, 1)
            if item:
                QDesktopServices.openUrl(QUrl.fromLocalFile(item.text()))

        def open_offer_file(self, row: int, column: int) -> None:
            del column
            results = getattr(self, "offer_results", [])
            if 0 <= row < len(results):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(results[row][0])))

        def show_offer_details(
            self, row: int, column: int, previous_row: int, previous_column: int
        ) -> None:
            del column, previous_row, previous_column
            results = getattr(self, "offer_results", [])
            if not 0 <= row < len(results):
                self.offer_candidate_combo.clear()
                self.offer_details.clear()
                self.offer_review_queue_table.setRowCount(0)
                self.offer_source_preview.setHtml("<p>Select an imported quote source.</p>")
                return
            _path, result = results[row]
            self.offer_review_queue_table.setRowCount(len(result.review_queue))
            for queue_row, item in enumerate(result.review_queue):
                values = [
                    f"{item.source_ref.path}#{item.source_ref.reference or ''}",
                    f"{item.confidence:.2f}",
                    item.issue,
                    item.candidate_mpn or "",
                ]
                for queue_column, value in enumerate(values):
                    table_item = QTableWidgetItem(value)
                    table_item.setData(Qt.ItemDataRole.UserRole, queue_row)
                    self.offer_review_queue_table.setItem(queue_row, queue_column, table_item)
            self.offer_candidate_combo.blockSignals(True)
            self.offer_candidate_combo.clear()
            for index, candidate in enumerate(result.offers):
                offer = candidate.offer
                label = f"{offer.manufacturer_part_number} / {offer.supplier_part_number}"
                if candidate.requires_review:
                    label += " — review required"
                self.offer_candidate_combo.addItem(label, index)
            self.offer_candidate_combo.blockSignals(False)
            if result.offers:
                self.offer_candidate_combo.setCurrentIndex(0)
                self.show_selected_offer(0)
            else:
                self.offer_details.setPlainText(
                    json.dumps(
                        {
                            "supplier_id": result.supplier_id,
                            "source_file": result.source_file,
                            "review_queue": [item.model_dump() for item in result.review_queue],
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                self.offer_correction.clear()
                self.offer_review_status.setText("No extracted offer candidate is available.")
                if result.review_queue:
                    self.show_review_queue_evidence(0, 0, -1, -1)

        def _show_offer_source_evidence(
            self, source_path: str, source_reference: str | None
        ) -> None:
            if self.current_project_path is None:
                self.offer_source_preview.setHtml("<p>Select a project first.</p>")
                return
            source = _quote_source_path(self.current_project_path, source_path)
            if source is None:
                self.offer_source_preview.setHtml(
                    "<p>Source evidence is not stored inside the project production folder.</p>"
                )
                return
            try:
                self.offer_source_preview.setHtml(
                    quote_source_preview_html(source, source_reference)
                )
            except (OSError, ValueError) as exc:
                self.offer_source_preview.setHtml(
                    f"<p>Could not preview source evidence: {escape(str(exc))}</p>"
                )

        def show_review_queue_evidence(
            self, row: int, column: int, previous_row: int, previous_column: int
        ) -> None:
            del column, previous_row, previous_column
            offer_row = self.offer_table.currentRow()
            results = getattr(self, "offer_results", [])
            if not 0 <= offer_row < len(results):
                return
            _path, result = results[offer_row]
            if not 0 <= row < len(result.review_queue):
                return
            source_ref = result.review_queue[row].source_ref
            self._show_offer_source_evidence(source_ref.path, source_ref.reference)
            self.offer_candidate_views.setCurrentWidget(self.offer_source_preview)

        def open_review_queue_source(self, row: int, column: int) -> None:
            del column
            offer_row = self.offer_table.currentRow()
            results = getattr(self, "offer_results", [])
            if not 0 <= offer_row < len(results):
                return
            _path, result = results[offer_row]
            if not 0 <= row < len(result.review_queue) or self.current_project_path is None:
                return
            source_ref = result.review_queue[row].source_ref
            source = _quote_source_path(self.current_project_path, source_ref.path)
            if source is None:
                QMessageBox.information(
                    self,
                    "Quote source is not stored in the project",
                    f"Source reference: {source_ref.path}#{source_ref.reference or ''}",
                )
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(source)))

        def show_selected_offer(self, index: int) -> None:
            row = self.offer_table.currentRow()
            results = getattr(self, "offer_results", [])
            if not 0 <= row < len(results) or index < 0:
                return
            source_path, result = results[row]
            candidate = result.offers[index]
            self.offer_details.setPlainText(
                f"Supplier: {result.supplier_id}\n"
                f"Imported from: {source_path}\n"
                f"Source: {candidate.offer.source_ref.path}"
                + (
                    f"#{candidate.offer.source_ref.reference}"
                    if candidate.offer.source_ref.reference
                    else ""
                )
                + f"\nConfidence: {candidate.confidence:.2f}; "
                f"requires review: {candidate.requires_review}\n\n"
                + candidate.offer.model_dump_json(indent=2)
            )
            self._show_offer_source_evidence(
                candidate.offer.source_ref.path, candidate.offer.source_ref.reference
            )
            self.offer_candidate_views.setCurrentWidget(self.offer_source_preview)
            self.offer_correction.setPlainText(candidate.offer.model_dump_json(indent=2))
            key = candidate_key(result.supplier_id, result.source_file, index, candidate)
            decision = getattr(self, "offer_decisions", {}).get(key)
            self.offer_review_status.setText(
                f"Latest decision: {decision.disposition} — {decision.comment}"
                if decision
                else "Latest decision: open"
            )

        def decide_selected_offer(self, disposition: str) -> None:
            row = self.offer_table.currentRow()
            index = self.offer_candidate_combo.currentData()
            results = getattr(self, "offer_results", [])
            if self.current_project_path is None or not 0 <= row < len(results) or index is None:
                QMessageBox.information(
                    self, "Select an offer", "Select an imported offer candidate first."
                )
                return
            _path, result = results[row]
            candidate = result.offers[int(index)]
            corrected: Offer | None = None
            try:
                if disposition == "corrected":
                    corrected = Offer.model_validate_json(self.offer_correction.toPlainText())
                decisions = record_offer_decision(
                    self.offer_decision_path,
                    supplier_id=result.supplier_id,
                    source_file=result.source_file,
                    index=int(index),
                    candidate=candidate,
                    disposition=cast(OfferDisposition, disposition),
                    comment=self.offer_review_comment.text(),
                    corrected_offer=corrected,
                )
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Quote review was not saved", str(exc))
                return
            self.offer_decisions = latest_offer_decisions(decisions)
            self.show_selected_offer(int(index))
            self.log.appendPlainText(
                f"Recorded {disposition} quote candidate from {result.source_file}"
            )

        def open_selected_quote_source(self) -> None:
            row = self.offer_table.currentRow()
            index = self.offer_candidate_combo.currentData()
            results = getattr(self, "offer_results", [])
            if self.current_project_path is None or not 0 <= row < len(results) or index is None:
                return
            _path, result = results[row]
            candidate = result.offers[int(index)]
            source = _quote_source_path(self.current_project_path, candidate.offer.source_ref.path)
            if source is None:
                QMessageBox.information(
                    self,
                    "Quote source is not stored in the project",
                    f"Source reference: {candidate.offer.source_ref.path}",
                )
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(source)))

        def on_failed(self, message: str) -> None:
            self.log.appendPlainText("ERROR: " + message)
            self.statusBar().showMessage("Project run failed")
            QMessageBox.critical(self, "KiProd run failed", message)

        def on_finished(self) -> None:
            self.run_button.setEnabled(True)
            self.worker = None
            self.thread = None

        def refresh_reports(self) -> None:
            if self.current_project_path is None:
                return
            output_dir = self.current_project_path / "docs" / "production"
            paths = (
                sorted(
                    path
                    for path in output_dir.rglob("*")
                    if path.is_file()
                    and path.resolve().is_relative_to(output_dir.resolve())
                    and path.suffix.casefold() in {".csv", ".json", ".md", ".xlsx"}
                    and ".kiprod" not in path.relative_to(output_dir).parts
                    and "config" not in path.relative_to(output_dir).parts
                )
                if output_dir.is_dir()
                else []
            )
            self.reports_list.setRowCount(len(paths))
            for row, path in enumerate(paths):
                self.reports_list.setItem(
                    row, 0, QTableWidgetItem(str(path.relative_to(output_dir)))
                )
                self.reports_list.setItem(row, 1, QTableWidgetItem(str(path)))

        def choose_comparison_inputs(self) -> None:
            if (
                self.current_project is None
                or self.current_project_path is None
                or self.current_json_path is None
            ):
                QMessageBox.warning(self, "Project required", "Build a project BOM first.")
                return
            paths, _filter = QFileDialog.getOpenFileNames(
                self,
                "Select saved landed-cost JSON files",
                str(self.current_project_path / "docs" / "production" / "quotes"),
                "JSON files (*.json)",
            )
            if not paths:
                return
            try:
                weights = ComparisonWeights(
                    price=float(self.compare_price_weight.text()),
                    lead_time=float(self.compare_lead_weight.text()),
                )
                weights.normalized()
                comparison, run_dir = _create_comparison(
                    self.current_project,
                    [Path(path) for path in paths],
                    self.current_json_path,
                    weights,
                )
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Comparison failed", str(exc))
                self.log.appendPlainText(f"ERROR: comparison failed: {exc}")
                return
            self.show_comparison(comparison)
            self.log.appendPlainText(f"Saved comparison run: {run_dir}")
            self.refresh_reports()
            self.tabs.setCurrentIndex(self.tabs.indexOf(self.compare_page))
            self.comparison_views.setCurrentWidget(self.comparison_table)

        def show_comparison(self, comparison: Comparison) -> None:
            self.current_comparison = comparison
            self.writeback_button.setEnabled(any(mix.lines for mix in comparison.best_mix))
            self.comparison_chart.setHtml(_comparison_chart_html(comparison))
            self.comparison_table.setRowCount(len(comparison.rows))
            for row, item in enumerate(comparison.rows):
                values = [
                    str(item.rank),
                    item.supplier_id,
                    str(item.board_quantity),
                    item.currency,
                    item.total,
                    item.per_board,
                    item.parts_total,
                    item.shipping,
                    item.nre,
                    item.duty,
                    item.fees,
                    str(item.lead_time_days) if item.lead_time_days is not None else "unknown",
                    f"{item.ranking_score:.3f}",
                    str(item.quoted_lines),
                ]
                for column, value in enumerate(values):
                    self.comparison_table.setItem(row, column, QTableWidgetItem(value))
            gaps = ", ".join(comparison.coverage_gaps) or "none"
            self.coverage_label.setText(f"Coverage gaps: {gaps}")
            mix_rows: list[tuple[Any, Any]] = []
            for mix in comparison.best_mix:
                if mix.lines:
                    mix_rows.extend((mix, line) for line in mix.lines)
                else:
                    mix_rows.append((mix, None))
            self.best_mix_table.setRowCount(max(1, len(mix_rows)))
            for row, (mix, line) in enumerate(mix_rows):
                values = [
                    str(mix.board_quantity),
                    line.manufacturer_part_number if line else "(no offer)",
                    line.supplier_id if line else "",
                    line.supplier_part_number if line else "",
                    line.extended_price if line else "",
                    line.source_ref if line else "",
                    mix.total,
                    mix.per_board,
                    ", ".join(mix.coverage_gaps) or "none",
                ]
                for column, value in enumerate(values):
                    self.best_mix_table.setItem(row, column, QTableWidgetItem(value))
            if not mix_rows:
                self.best_mix_table.setItem(
                    0, 0, QTableWidgetItem("No matching BOM requirements for a best-mix view.")
                )

        def approve_best_mix_writeback(self) -> None:
            if self.current_project_path is None or not hasattr(self, "current_bom"):
                QMessageBox.information(self, "Project required", "Build a project BOM first.")
                return
            updates: dict[tuple[Path, str, str], SchematicFieldUpdate] = {}
            bom_lines = {line.mpn.casefold(): line for line in self.current_bom.lines if line.mpn}
            for mix in getattr(self, "current_comparison", Comparison(rows=[])).best_mix:
                for offer_line in mix.lines:
                    bom_line = bom_lines.get(offer_line.manufacturer_part_number.casefold())
                    if bom_line is None:
                        continue
                    for source in bom_line.sources:
                        try:
                            source_path = _evidence_path(self.current_project_path, source.path)
                        except ValueError:
                            continue
                        if source_path.suffix.casefold() != ".kicad_sch" or not source.reference:
                            continue
                        for field, value in (
                            ("MPN", offer_line.manufacturer_part_number),
                            ("Supplier Part Number", offer_line.supplier_part_number),
                        ):
                            key = (source_path, source.reference, field)
                            updates[key] = SchematicFieldUpdate(
                                path=source_path,
                                reference=source.reference,
                                field=field,
                                value=value,
                            )
            if not updates:
                QMessageBox.information(
                    self,
                    "No schematic targets",
                    "The selected best mix has no matching BOM components sourced from "
                    "project schematics.",
                )
                return
            try:
                plan = prepare_writeback(self.current_project_path, list(updates.values()))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Write-back preview failed", str(exc))
                return
            if not plan.changes:
                QMessageBox.information(self, "No changes", "Schematic fields already match.")
                return
            preview_lines = [
                f"{change.path.relative_to(self.current_project_path)} · {change.reference} · "
                f"{change.field}: {change.before or '(empty)'} → {change.after}"
                for change in plan.changes[:25]
            ]
            if len(plan.changes) > 25:
                preview_lines.append(f"… and {len(plan.changes) - 25} more change(s)")
            approval = QMessageBox.question(
                self,
                "Approve schematic write-back",
                "Apply these best-mix values to the project schematics? Original files will be "
                "backed up before writing.\n\n" + "\n".join(preview_lines),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if approval != QMessageBox.StandardButton.Yes:
                return
            try:
                backups = apply_writeback(self.current_project_path, plan)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Schematic write-back failed", str(exc))
                return
            self.log.appendPlainText(
                f"Approved {len(plan.changes)} schematic field change(s); backups: "
                + ", ".join(str(path) for path in backups)
            )
            self.start_run()

        def regenerate_selected_report(self) -> None:
            if self.current_project_path is None:
                return
            selected = self.reports_list.currentRow()
            path_item = self.reports_list.item(selected, 1) if selected >= 0 else None
            if path_item is None:
                QMessageBox.information(self, "Select a report", "Select a saved run report first.")
                return
            report_path = Path(path_item.text()).resolve()
            run_root = (
                self.current_project_path / "docs" / "production" / "quotes" / "runs"
            ).resolve()
            run_dir = next(
                (
                    parent
                    for parent in (report_path.parent, *report_path.parents)
                    if parent.is_relative_to(run_root) and (parent / "run.json").is_file()
                ),
                None,
            )
            if run_dir is None:
                QMessageBox.information(
                    self, "No saved comparison run", "The selected artifact is not in a saved run."
                )
                return
            try:
                comparison = _regenerate_comparison(run_dir)
            except (OSError, ValueError, KeyError) as exc:
                QMessageBox.critical(self, "Report regeneration failed", str(exc))
                self.log.appendPlainText(f"ERROR: report regeneration failed: {exc}")
                return
            self.log.appendPlainText(f"Regenerated comparison reports in {run_dir}")
            self.show_comparison(comparison)
            self.refresh_reports()
            self.tabs.setCurrentIndex(self.tabs.indexOf(self.compare_page))
            self.comparison_views.setCurrentWidget(self.comparison_table)

        def open_report(self, row: int, column: int) -> None:
            del column
            path_item = self.reports_list.item(row, 1)
            if path_item:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path_item.text()))

        def open_output_folder(self) -> None:
            if self.current_project is not None:
                output_dir = self.current_project.root / "docs" / "production" / "bom"
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir)))

    application = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(project_path)
    window.show()
    return int(application.exec())
