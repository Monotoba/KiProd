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
