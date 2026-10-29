from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from kiprod.rfq.quote_import import parse_quote_attachment

_HEADER = (
    "Manufacturer Part Number,Supplier Part Number,Qty Break,Unit Price,"
    "Currency,Stock,Lead Time Days\n"
)


def test_csv_quote_import_groups_price_breaks_and_preserves_row_sources(tmp_path: Path) -> None:
    quote = tmp_path / "supplier-quote.csv"
    quote.write_text(
        _HEADER
        + "MPN-1,SKU-1,10,0.50,USD,100,5\n"
        + "MPN-1,SKU-1,100,0.25,USD,100,5\n"
        + "MPN-2,SKU-2,10,not-a-price,USD,,\n",
        encoding="utf-8",
    )

    result = parse_quote_attachment(quote, "supplier-a")

    assert len(result.offers) == 1
    extracted = result.offers[0]
    assert extracted.offer.manufacturer_part_number == "MPN-1"
    assert [item.quantity for item in extracted.offer.price_breaks] == [10, 100]
    assert extracted.offer.source_ref.path == quote.name
    assert extracted.offer.source_ref.reference == "rows:2,3"
    assert extracted.confidence == 0.97
    assert not extracted.requires_review
    assert len(result.review_queue) == 1
    assert result.review_queue[0].source_ref.reference == "row:4"
    assert result.review_queue[0].confidence < 0.85


def test_currency_can_be_supplied_explicitly_when_missing_from_csv(tmp_path: Path) -> None:
    quote = tmp_path / "quote.csv"
    quote.write_text(
        "MPN,SKU,Quantity,Unit Price\nMPN-1,SKU-1,25,1.25\n",
        encoding="utf-8",
    )

    result = parse_quote_attachment(quote, "supplier-a", currency="usd")

    assert result.offers[0].offer.price_breaks[0].currency == "USD"
    assert not result.review_queue


def test_conflicting_duplicate_break_is_held_for_review(tmp_path: Path) -> None:
    quote = tmp_path / "quote.csv"
    quote.write_text(
        _HEADER + "MPN-1,SKU-1,10,0.50,USD,,\nMPN-1,SKU-1,10,0.45,USD,,\n",
        encoding="utf-8",
    )

    result = parse_quote_attachment(quote, "supplier-a")

    assert result.offers == []
    assert len(result.review_queue) == 1
    assert "conflicting prices" in result.review_queue[0].issue


def test_xlsx_rows_are_parsed_through_openpyxl_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workbook_path = tmp_path / "quote.xlsx"
    workbook_path.write_bytes(b"fixture workbook placeholder")

    class FakeSheet:
        def iter_rows(self, *, values_only: bool) -> list[tuple[object, ...]]:
            assert values_only
            return [
                ("MPN", "SKU", "Quantity", "Unit Price", "Currency"),
                ("MPN-1", "SKU-1", 20, 0.75, "USD"),
            ]

    class FakeWorkbook:
        active = FakeSheet()

        def close(self) -> None:
            pass

    fake_openpyxl = ModuleType("openpyxl")
    fake_openpyxl.load_workbook = lambda *args, **kwargs: FakeWorkbook()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)

    result = parse_quote_attachment(workbook_path, "supplier-a")

    assert len(result.offers) == 1
    assert result.offers[0].offer.price_breaks[0].unit_price == 0.75
    assert result.offers[0].confidence == 0.95


def test_xlsx_without_optional_dependency_has_actionable_error(tmp_path: Path) -> None:
    workbook = tmp_path / "quote.xlsx"
    workbook.write_bytes(b"placeholder")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    try:
        with pytest.raises(ValueError, match=r"kiprod\[reports\]"):
            parse_quote_attachment(workbook, "supplier-a")
    finally:
        monkeypatch.undo()
