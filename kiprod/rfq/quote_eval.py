from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from kiprod.rfq.quote_import import QuoteImportResult, parse_quote_attachment

_FIELDS = ("mpn", "spn", "quantity", "unit_price", "currency")


class FixtureEvaluation(BaseModel):
    fixture: str
    expected_rows: int
    extracted_rows: int
    exact_rows: int
    field_accuracy: float
    precision: float
    recall: float
    review_items: int
    review_policy_passed: bool = True
    skipped: bool = False
    error: str | None = None


class QuoteEvaluation(BaseModel):
    minimum_accuracy: float
    field_accuracy: float
    precision: float
    recall: float
    fixture_count: int
    evaluated_fixture_count: int
    skipped_fixture_count: int
    review_policy_passed: bool
    cases: list[FixtureEvaluation] = Field(default_factory=list)
    passed: bool


def _row_key(row: dict[str, object]) -> tuple[str, str, int, str]:
    return (
        str(row["mpn"]),
        str(row["spn"]),
        int(str(row["quantity"])),
        str(row["currency"]).upper(),
    )


def _same_value(field: str, actual: object, expected: object) -> bool:
    if field == "unit_price":
        return Decimal(str(actual)) == Decimal(str(expected))
    if field == "currency":
        return str(actual).upper() == str(expected).upper()
    if field == "quantity":
        return int(str(actual)) == int(str(expected))
    return str(actual) == str(expected)


def _actual_rows(result: QuoteImportResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for extracted in result.offers:
        offer = extracted.offer
        for price in offer.price_breaks:
            rows.append(
                {
                    "mpn": offer.manufacturer_part_number,
                    "spn": offer.supplier_part_number,
                    "quantity": price.quantity,
                    "unit_price": price.unit_price,
                    "currency": price.currency,
                }
            )
    return rows


def _evaluate_case(
    fixture: Path,
    expected_rows: list[dict[str, object]],
    *,
    supplier_id: str,
    expected_review: bool | None,
    expected_review_items: int | None,
    currency: str | None,
) -> FixtureEvaluation:
    try:
        result = parse_quote_attachment(fixture, supplier_id, currency=currency)
    except ValueError as exc:
        if fixture.suffix.casefold() in {".xlsx", ".xlsm"} and "kiprod[reports]" in str(exc):
            return FixtureEvaluation(
                fixture=fixture.name,
                expected_rows=len(expected_rows),
                extracted_rows=0,
                exact_rows=0,
                field_accuracy=0.0,
                precision=0.0,
                recall=0.0,
                review_items=0,
                review_policy_passed=True,
                skipped=True,
                error=str(exc),
            )
        return FixtureEvaluation(
            fixture=fixture.name,
            expected_rows=len(expected_rows),
            extracted_rows=0,
            exact_rows=0,
            field_accuracy=0.0,
            precision=0.0,
            recall=0.0,
            review_items=0,
            review_policy_passed=expected_review is None and expected_review_items is None,
            error=str(exc),
        )
    actual_rows = _actual_rows(result)

    def exact_key(row: dict[str, object]) -> tuple[str, ...]:
        return tuple(
            str(row[field]).upper() if field == "currency" else str(row[field]) for field in _FIELDS
        )

    expected_counts = Counter(exact_key(row) for row in expected_rows)
    actual_counts = Counter(exact_key(row) for row in actual_rows)
    exact_rows = sum((expected_counts & actual_counts).values())
    correct_fields = 0
    for expected in expected_rows:
        candidates = [row for row in actual_rows if _row_key(row) == _row_key(expected)]
        if candidates:
            candidate = candidates[0]
            correct_fields += sum(
                _same_value(field, candidate[field], expected[field]) for field in _FIELDS
            )
    expected_fields = len(expected_rows) * len(_FIELDS)
    field_accuracy = correct_fields / expected_fields if expected_fields else 1.0
    precision = (
        exact_rows / len(actual_rows) if actual_rows else (1.0 if not expected_rows else 0.0)
    )
    recall = exact_rows / len(expected_rows) if expected_rows else (1.0 if not actual_rows else 0.0)
    actual_review = any(offer.requires_review for offer in result.offers)
    review_policy_passed = (expected_review is None or actual_review == expected_review) and (
        expected_review_items is None or len(result.review_queue) == expected_review_items
    )
    return FixtureEvaluation(
        fixture=fixture.name,
        expected_rows=len(expected_rows),
        extracted_rows=len(actual_rows),
        exact_rows=exact_rows,
        field_accuracy=field_accuracy,
        precision=precision,
        recall=recall,
        review_items=len(result.review_queue),
        review_policy_passed=review_policy_passed,
        error=(
            "human-review policy did not match expected fixture policy"
            if not review_policy_passed
            else None
        ),
    )


def evaluate_quote_fixtures(
    fixture_dir: Path,
    expected_file: Path,
    *,
    supplier_id: str = "evaluation-fixture",
    minimum_accuracy: float = 0.95,
) -> QuoteEvaluation:
    if not 0.0 <= minimum_accuracy <= 1.0:
        raise ValueError("minimum accuracy must be between 0 and 1")
    spec = json.loads(expected_file.read_text(encoding="utf-8"))
    cases: list[FixtureEvaluation] = []
    for case in spec.get("fixtures", []):
        fixture = fixture_dir / str(case["path"])
        rows = case.get("rows", [])
        expected_review = case.get("review_required")
        if expected_review is not None and not isinstance(expected_review, bool):
            raise ValueError(f"review_required must be a boolean for fixture {fixture.name}")
        expected_review_items = case.get("review_item_count")
        if expected_review_items is not None and (
            isinstance(expected_review_items, bool)
            or not isinstance(expected_review_items, int)
            or expected_review_items < 0
        ):
            raise ValueError(f"review_item_count must be a non-negative integer for {fixture.name}")
        if not fixture.is_file():
            cases.append(
                FixtureEvaluation(
                    fixture=fixture.name,
                    expected_rows=len(rows),
                    extracted_rows=0,
                    exact_rows=0,
                    field_accuracy=0.0,
                    precision=0.0,
                    recall=0.0,
                    review_items=0,
                    review_policy_passed=expected_review is None and expected_review_items is None,
                    error=f"fixture not found: {fixture}",
                )
            )
        else:
            cases.append(
                _evaluate_case(
                    fixture,
                    rows,
                    supplier_id=supplier_id,
                    expected_review=expected_review,
                    expected_review_items=expected_review_items,
                    currency=(str(case["currency"]) if case.get("currency") is not None else None),
                )
            )
    evaluated = [case for case in cases if not case.skipped]
    expected_rows = sum(case.expected_rows for case in evaluated)
    extracted_rows = sum(case.extracted_rows for case in evaluated)
    exact_rows = sum(case.exact_rows for case in evaluated)
    expected_fields = sum(case.expected_rows * len(_FIELDS) for case in evaluated)
    weighted_correct_fields = sum(
        case.field_accuracy * case.expected_rows * len(_FIELDS) for case in evaluated
    )
    accuracy = weighted_correct_fields / expected_fields if expected_fields else 0.0
    precision = exact_rows / extracted_rows if extracted_rows else 0.0
    recall = exact_rows / expected_rows if expected_rows else 0.0
    errors = any(case.error is not None for case in evaluated)
    review_policy_passed = all(case.review_policy_passed for case in evaluated)
    return QuoteEvaluation(
        minimum_accuracy=minimum_accuracy,
        field_accuracy=accuracy,
        precision=precision,
        recall=recall,
        fixture_count=len(cases),
        evaluated_fixture_count=len(evaluated),
        skipped_fixture_count=sum(case.skipped for case in cases),
        review_policy_passed=review_policy_passed,
        cases=cases,
        passed=accuracy >= minimum_accuracy and not errors and review_policy_passed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RFQ quote extraction fixtures.")
    parser.add_argument("--fixture-dir", type=Path, default=Path("tests/fixtures"))
    parser.add_argument(
        "--expected", type=Path, default=Path("tests/fixtures/rfq_quote_expected.json")
    )
    parser.add_argument("--minimum-accuracy", type=float, default=0.95)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_quote_fixtures(
        args.fixture_dir,
        args.expected,
        minimum_accuracy=args.minimum_accuracy,
    )
    serialized = result.model_dump_json(indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
