from __future__ import annotations

from pathlib import Path

from kiprod.rfq import quote_import
from kiprod.rfq.quote_import import quote_source_preview_html


def test_csv_preview_highlights_cited_logical_rows(tmp_path: Path) -> None:
    source = tmp_path / "quote.csv"
    source.write_text(
        "MPN,SKU,Quantity,Unit Price,Currency\nMPN-A,SKU-A,10,1.00,USD\nMPN-B,SKU-B,10,2.00,USD\n",
        encoding="utf-8",
    )

    preview = quote_source_preview_html(source, "row:3")

    assert "MPN-B" in preview
    assert "bgcolor='#fff2a8'><th>3</th>" in preview
    assert "bgcolor='#fff2a8'><th>2</th>" not in preview


def test_pdf_preview_highlights_cited_extracted_block(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "quote.pdf"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(
        quote_import,
        "_pdf_text",
        lambda _path: (
            "Manufacturer Part Number: MPN-A\nSupplier Part Number: SKU-A\n\n"
            "Manufacturer Part Number: MPN-B\nSupplier Part Number: SKU-B\n",
            False,
        ),
    )

    preview = quote_source_preview_html(source, "blocks:2")

    assert "MPN-B" in preview
    assert "<tr bgcolor='#fff2a8'><td><pre>Manufacturer Part Number: MPN-B" in preview
    assert "<tr bgcolor='#f2f4f7'><td><pre>Manufacturer Part Number: MPN-A" in preview
