from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from kiprod.ai.review import ReviewReport, review_bom
from kiprod.analysis.assembly import extract as extract_assembly
from kiprod.analysis.panelization import discover_fabrication_notes, extract_boards_per_panel
from kiprod.core.artifacts import write_bom
from kiprod.core.bom import build
from kiprod.core.models import AssemblySpec, BoardSpec, NormalizedBOM, Project
from kiprod.core.project import discover
from kiprod.kicad.board import extract as extract_board
from kiprod.kicad.cli_adapter import export_bom


def _qt() -> tuple[Any, ...]:
    try:
        from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal  # type: ignore[import-not-found]
        from PySide6.QtGui import QDesktopServices  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QApplication,
            QComboBox,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QSplitter,
            QTableWidget,
            QTableWidgetItem,
            QTabWidget,
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
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )


def _load_project(
    project_path: Path, variant: str | None
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
    if variant:
        if variant not in project.variants:
            raise ValueError(f"unknown project variant: {variant}")
        with TemporaryDirectory(prefix="kiprod-gui-variant-") as temporary:
            exported = export_bom(project.main_schematic, Path(temporary) / "variant.csv", variant)
            bom = build(project, exported_bom=exported)
    else:
        bom = build(project)
    output_dir = project.root / "docs" / "production" / "bom"
    json_path, csv_path = write_bom(bom, output_dir)
    report = review_bom(bom)
    review_path = output_dir / "review.deterministic.json"
    review_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    board_spec: BoardSpec | None = None
    assembly_spec: AssemblySpec | None = None
    if project.boards:
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
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    ) = _qt()

    class ProjectWorker(QObject):  # type: ignore[valid-type,misc]
        completed = Signal(object)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, path: Path, variant: str | None) -> None:
            super().__init__()
            self.path = path
            self.variant = variant

        def run(self) -> None:
            try:
                self.completed.emit(_load_project(self.path, self.variant))
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
            self.open_folder_button = QPushButton("Open output folder")
            self.open_folder_button.setEnabled(False)
            run_bar.addWidget(QLabel("Project"))
            run_bar.addWidget(self.project_field, 1)
            run_bar.addWidget(browse_button)
            run_bar.addWidget(self.variant_combo)
            run_bar.addWidget(self.run_button)
            run_bar.addWidget(self.open_folder_button)
            root_layout.addLayout(run_bar)

            splitter = QSplitter(Qt.Orientation.Vertical)
            self.tabs = QTabWidget()
            self.project_page = QPlainTextEdit()
            self.project_page.setReadOnly(True)
            self.board_table = QTableWidget(0, 2)
            self.board_table.setHorizontalHeaderLabels(["Board metric", "Value"])
            self.board_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.assembly_table = QTableWidget(0, 2)
            self.assembly_table.setHorizontalHeaderLabels(["Assembly metric", "Value"])
            self.assembly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.bom_table = QTableWidget(0, 5)
            self.bom_table.setHorizontalHeaderLabels(
                ["References", "Qty", "Value", "Footprint", "MPN"]
            )
            self.bom_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.bom_table.horizontalHeader().setStretchLastSection(True)
            self.review_table = QTableWidget(0, 5)
            self.review_table.setHorizontalHeaderLabels(
                ["Severity", "Code", "References", "Finding", "Suggested action"]
            )
            self.review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.review_table.horizontalHeader().setStretchLastSection(True)
            self.reports_list = QTableWidget(0, 2)
            self.reports_list.setHorizontalHeaderLabels(["Artifact", "Path"])
            self.reports_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.reports_list.cellDoubleClicked.connect(self.open_report)
            settings_page = QPlainTextEdit(
                "Project settings are managed with the CLI today.\n"
                "Use `kiprod config show --project <project>` to inspect effective settings."
            )
            settings_page.setReadOnly(True)
            self.tabs.addTab(self.project_page, "Project")
            self.tabs.addTab(self.bom_table, "BOM & Specs")
            self.tabs.addTab(self.review_table, "Review")
            self.tabs.addTab(self.board_table, "Boards")
            self.tabs.addTab(self.assembly_table, "Assembly")
            self.tabs.addTab(self.reports_list, "Reports")
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
            self.run_button.setEnabled(False)
            self.statusBar().showMessage("Building normalized BOM and deterministic review…")
            self.log.appendPlainText(f"Loading project: {project_path}")
            self.thread = QThread(self)
            self.worker = ProjectWorker(project_path, self.variant_combo.currentData() or None)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.completed.connect(self.on_completed)
            self.worker.failed.connect(self.on_failed)
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
            self.current_json_path = json_path
            self.variant_combo.blockSignals(True)
            self.variant_combo.clear()
            self.variant_combo.addItem("Default variant", "")
            for variant in project.variants:
                self.variant_combo.addItem(variant, variant)
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
                values = [
                    ", ".join(line.references),
                    str(line.quantity),
                    line.value,
                    line.footprint,
                    line.mpn or "",
                ]
                for column, value in enumerate(values):
                    self.bom_table.setItem(row, column, QTableWidgetItem(value))
            self.review_table.setRowCount(len(report.findings))
            for row, finding in enumerate(report.findings):
                values = [
                    finding.severity,
                    finding.code,
                    ", ".join(finding.line_ids),
                    finding.summary,
                    finding.suggested_action or "",
                ]
                for column, value in enumerate(values):
                    self.review_table.setItem(row, column, QTableWidgetItem(value))
            self._fill_metrics(self.board_table, board_spec.model_dump() if board_spec else {})
            self._fill_metrics(
                self.assembly_table,
                assembly_spec.model_dump() if assembly_spec else {},
            )
            self.refresh_reports()
            self.open_folder_button.setEnabled(True)
            self.log.appendPlainText(
                f"Wrote {json_path}; reviewed {len(bom.lines)} BOM lines and found "
                f"{len(report.findings)} deterministic findings."
            )
            self.statusBar().showMessage(f"Ready — {len(bom.lines)} BOM lines")

        @staticmethod
        def _fill_metrics(table: Any, metrics: dict[str, Any]) -> None:
            table.setRowCount(len(metrics))
            for row, (name, value) in enumerate(metrics.items()):
                table.setItem(row, 0, QTableWidgetItem(name.replace("_", " ").title()))
                table.setItem(row, 1, QTableWidgetItem(json.dumps(value, sort_keys=True)))

        def on_failed(self, message: str) -> None:
            self.log.appendPlainText("ERROR: " + message)
            self.statusBar().showMessage("Project run failed")
            QMessageBox.critical(self, "KiProd run failed", message)

        def on_finished(self) -> None:
            self.run_button.setEnabled(True)
            self.worker = None
            self.thread = None

        def refresh_reports(self) -> None:
            if self.current_project is None:
                return
            output_dir = self.current_project.root / "docs" / "production" / "bom"
            paths = sorted(path for path in output_dir.iterdir() if path.is_file())
            self.reports_list.setRowCount(len(paths))
            for row, path in enumerate(paths):
                self.reports_list.setItem(row, 0, QTableWidgetItem(path.name))
                self.reports_list.setItem(row, 1, QTableWidgetItem(str(path)))

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
