from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from kiprod.analysis.landed import LandedCost, LandedLine
from kiprod.core.models import Offer, PriceBreak, SourceRef
from kiprod.core.project import discover
from kiprod.gui import (
    _comparison_chart_html,
    _create_comparison,
    _evidence_path,
    _load_project,
    _quote_results,
    _regenerate_comparison,
)
from kiprod.rfq.quote_import import ExtractedOffer, QuoteImportResult


def test_review_evidence_path_is_confined_to_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "design.kicad_sch"
    source.write_text("(kicad_sch)", encoding="utf-8")

    assert _evidence_path(project, "design.kicad_sch") == source.resolve()
    with pytest.raises(ValueError, match="escapes"):
        _evidence_path(project, "../../outside.txt")


def test_gui_workflow_writes_bom_review_and_board_outputs(tmp_path: Path) -> None:
    project_path = tmp_path / "native_counter"
    shutil.copytree(Path(__file__).parent / "projects" / "native_counter", project_path)
    shutil.copy(
        Path(__file__).parent / "fixtures" / "board_minimal.kicad_pcb",
        project_path / "native_counter.kicad_pcb",
    )
    progress: list[tuple[int, str]] = []

    project, bom, review, board, assembly, bom_json, bom_csv = _load_project(
        project_path, None, progress=lambda value, message: progress.append((value, message))
    )

    output_dir = project.root / "docs" / "production" / "bom"
    assert bom.lines
    assert review.project == project.pro_file.stem
    assert board is not None and assembly is not None
    assert bom_json.is_file() and bom_csv.is_file()
    assert (output_dir / "review.deterministic.json").is_file()
    assert (output_dir / "board_assembly.json").is_file()
    assert [value for value, _message in progress] == sorted(value for value, _ in progress)
    assert progress[-1][0] == 95


def test_gui_quote_views_find_captured_mail_and_typed_offer_files(tmp_path: Path) -> None:
    project_path = tmp_path / "native_counter"
    shutil.copytree(Path(__file__).parent / "projects" / "native_counter", project_path)
    project = discover(project_path)
    reply = project_path / "docs" / "production" / ".kiprod" / "replies" / "rfq-1.eml"
    reply.parent.mkdir(parents=True)
    reply.write_text("Subject: RFQ KP-1\n\nA reply", encoding="utf-8")
    offer_file = project_path / "docs" / "production" / "quotes" / "offers.json"
    offer_file.parent.mkdir(parents=True)
    imported = QuoteImportResult(
        supplier_id="example-supplier",
        source_file="reply.csv",
        offers=[
            ExtractedOffer(
                offer=Offer(
                    supplier_id="example-supplier",
                    supplier_part_number="SKU-1",
                    manufacturer_part_number="MPN-1",
                    price_breaks=[PriceBreak(quantity=10, unit_price=0.5, currency="USD")],
                    source_ref=SourceRef(path="reply.csv", reference="row 2"),
                ),
                confidence=0.95,
                requires_review=False,
            )
        ],
    )
    offer_file.write_text(imported.model_dump_json(), encoding="utf-8")
    invalid_json = offer_file.parent / "unrelated.json"
    invalid_json.write_text("{}", encoding="utf-8")

    replies, offers = _quote_results(project)

    assert replies == [reply.resolve()]
    assert len(offers) == 1
    assert offers[0][0] == offer_file.resolve()
    assert offers[0][1].offers[0].offer.manufacturer_part_number == "MPN-1"


def test_gui_comparison_archives_inputs_and_regenerates_only_after_hash_check(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "native_counter"
    shutil.copytree(Path(__file__).parent / "projects" / "native_counter", project_path)
    _project, _bom, _review, _board, _assembly, bom_json, _csv = _load_project(project_path, None)
    project = discover(project_path)
    landed = LandedCost(
        supplier_id="supplier-a",
        board_quantity=10,
        currency="USD",
        parts_total=Decimal("5.00"),
        total=Decimal("6.00"),
        per_board=Decimal("0.60"),
        lines=[
            LandedLine(
                manufacturer_part_number="MPN-1",
                supplier_part_number="SKU-1",
                required_quantity=10,
                buy_quantity=10,
                unit_price=Decimal("0.50"),
                extended_price=Decimal("5.00"),
                currency="USD",
                source_ref=SourceRef(path="quote.csv", reference="row 2"),
            )
        ],
    )
    input_file = tmp_path / "landed.json"
    input_file.write_text(landed.model_dump_json(), encoding="utf-8")

    comparison, run_dir = _create_comparison(project, [input_file], bom_json)

    assert comparison.rows[0].supplier_id == "supplier-a"
    chart_html = _comparison_chart_html(comparison)
    assert "Supplier comparison charts" in chart_html
    assert "10 boards" in chart_html
    assert "supplier-a" in chart_html
    assert (run_dir / "comparison.md").is_file()
    assert (run_dir / "comparison.json").is_file()
    (run_dir / "comparison.md").unlink()
    regenerated = _regenerate_comparison(run_dir)
    assert regenerated == comparison
    assert (run_dir / "comparison.md").is_file()
    archived_input = next((run_dir / "inputs").glob("landed-*.json"))
    archived_input.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        _regenerate_comparison(run_dir)
