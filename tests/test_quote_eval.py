from __future__ import annotations

import json
from pathlib import Path

from kiprod.rfq.quote_eval import evaluate_quote_fixtures

FIXTURES = Path(__file__).parent / "fixtures"


def test_quote_fixture_evaluation_reports_field_accuracy(tmp_path: Path) -> None:
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "path": "rfq_quote.csv",
                        "rows": [
                            {
                                "mpn": "MPN-CSV-1",
                                "spn": "SKU-CSV-1",
                                "quantity": 10,
                                "unit_price": 0.5,
                                "currency": "USD",
                            },
                            {
                                "mpn": "MPN-CSV-1",
                                "spn": "SKU-CSV-1",
                                "quantity": 100,
                                "unit_price": 0.25,
                                "currency": "USD",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_quote_fixtures(FIXTURES, expected)

    assert report.passed
    assert report.field_accuracy == 1.0
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.cases[0].exact_rows == 2


def test_quote_fixture_accuracy_fails_when_expected_price_is_wrong(tmp_path: Path) -> None:
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "path": "rfq_quote.csv",
                        "rows": [
                            {
                                "mpn": "MPN-CSV-1",
                                "spn": "SKU-CSV-1",
                                "quantity": 10,
                                "unit_price": 0.75,
                                "currency": "USD",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_quote_fixtures(FIXTURES, expected, minimum_accuracy=0.95)

    assert not report.passed
    assert report.field_accuracy == 0.8
    assert report.precision == 0.0


def test_quote_fixture_evaluation_fails_when_review_policy_changes(tmp_path: Path) -> None:
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "path": "rfq_quote.csv",
                        "review_required": True,
                        "rows": [
                            {
                                "mpn": "MPN-CSV-1",
                                "spn": "SKU-CSV-1",
                                "quantity": 10,
                                "unit_price": 0.5,
                                "currency": "USD",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_quote_fixtures(FIXTURES, expected)

    assert not report.passed
    assert not report.review_policy_passed
    assert not report.cases[0].review_policy_passed
    assert "review policy" in (report.cases[0].error or "")


def test_quote_fixture_evaluation_accepts_currency_from_case_metadata(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "samples"
    fixture_dir.mkdir()
    (fixture_dir / "supplier.csv").write_text(
        "MPN,SKU,Quantity,Unit Price\nMPN-1,SKU-1,10,$0.25\n",
        encoding="utf-8",
    )
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "path": "supplier.csv",
                        "currency": "USD",
                        "rows": [
                            {
                                "mpn": "MPN-1",
                                "spn": "SKU-1",
                                "quantity": 10,
                                "unit_price": 0.25,
                                "currency": "USD",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_quote_fixtures(fixture_dir, expected)

    assert report.passed
    assert report.field_accuracy == 1.0
    assert report.precision == 1.0
    assert report.recall == 1.0


def test_quote_fixture_evaluation_checks_expected_review_queue_count(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "samples"
    fixture_dir.mkdir()
    (fixture_dir / "rfq_quote.csv").write_bytes((FIXTURES / "rfq_quote.csv").read_bytes())
    (fixture_dir / "no-match.csv").write_text(
        "DigiKey Part Number,Manufacturer Part Number,Quantity 1,Unit Price 1\n,,10,\n",
        encoding="utf-8",
    )
    expected = tmp_path / "expected.json"
    spec = json.loads((FIXTURES / "rfq_quote_expected.json").read_text(encoding="utf-8"))
    spec["fixtures"] = [
        {"path": "rfq_quote.csv", "rows": spec["fixtures"][0]["rows"]},
        {
            "path": "no-match.csv",
            "currency": "USD",
            "review_required": False,
            "review_item_count": 1,
            "rows": [],
        },
    ]
    expected.write_text(json.dumps(spec), encoding="utf-8")

    report = evaluate_quote_fixtures(fixture_dir, expected)

    assert report.passed
    assert report.cases[1].review_items == 1
    assert report.cases[1].review_policy_passed

    spec["fixtures"][1]["review_item_count"] = 0
    expected.write_text(json.dumps(spec), encoding="utf-8")
    failed_report = evaluate_quote_fixtures(fixture_dir, expected)
    assert not failed_report.passed
    assert not failed_report.cases[1].review_policy_passed
