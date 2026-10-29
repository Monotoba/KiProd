from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kiprod.core.models import NormalizedBOM

from .provider import LLMProvider
from .review import review_bom


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    line_ids: list[str]


class _ExpectedCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    findings: list[ExpectedFinding] = Field(default_factory=list)


class ReviewFixtureResult(BaseModel):
    fixture: str
    expected_findings: int
    actual_findings: int
    true_positives: int
    false_positives: int
    false_negatives: int
    schema_valid: bool
    grounded_findings: int
    error: str | None = None


class ReviewEvaluation(BaseModel):
    provider: str
    models: list[str] = Field(default_factory=list)
    fixture_count: int
    schema_valid_rate: float
    precision: float
    recall: float
    f1: float
    grounded_finding_rate: float
    minimum_schema_valid_rate: float
    minimum_precision: float
    minimum_recall: float
    cases: list[ReviewFixtureResult]
    passed: bool


def _finding_key(finding: Any) -> tuple[str, str, tuple[str, ...]]:
    return (finding.code, finding.severity, tuple(sorted(finding.line_ids)))


def _run_case(
    fixture_dir: Path,
    case: _ExpectedCase,
    provider: LLMProvider,
    prompt_dirs: list[Path] | None,
) -> tuple[ReviewFixtureResult, str | None]:
    bom_path = (fixture_dir / case.path).resolve()
    if not bom_path.is_relative_to(fixture_dir.resolve()):
        raise ValueError(f"fixture path escapes its directory: {case.path}")
    if not bom_path.is_file():
        return (
            ReviewFixtureResult(
                fixture=case.path,
                expected_findings=len(case.findings),
                actual_findings=0,
                true_positives=0,
                false_positives=0,
                false_negatives=len(case.findings),
                schema_valid=False,
                grounded_findings=0,
                error="fixture file not found",
            ),
            None,
        )
    try:
        bom = NormalizedBOM.model_validate_json(bom_path.read_text(encoding="utf-8"))
        report = review_bom(bom, provider=provider, prompt_dirs=prompt_dirs)
    except (OSError, RuntimeError, ValueError, ValidationError) as exc:
        return (
            ReviewFixtureResult(
                fixture=case.path,
                expected_findings=len(case.findings),
                actual_findings=0,
                true_positives=0,
                false_positives=0,
                false_negatives=len(case.findings),
                schema_valid=False,
                grounded_findings=0,
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )
    actual = [finding for finding in report.findings if finding.source == "ai_guess"]
    expected_counts = Counter(_finding_key(finding) for finding in case.findings)
    actual_counts = Counter(_finding_key(finding) for finding in actual)
    true_positives = sum((expected_counts & actual_counts).values())
    grounded = sum(
        bool(finding.line_ids) and bool(finding.evidence) and all(finding.evidence)
        for finding in actual
    )
    result = ReviewFixtureResult(
        fixture=case.path,
        expected_findings=len(case.findings),
        actual_findings=len(actual),
        true_positives=true_positives,
        false_positives=len(actual) - true_positives,
        false_negatives=len(case.findings) - true_positives,
        schema_valid=True,
        grounded_findings=grounded,
    )
    return result, report.ai_model


def evaluate_review_fixtures(
    fixture_dir: Path,
    expected_file: Path,
    provider: LLMProvider,
    *,
    prompt_dirs: list[Path] | None = None,
    minimum_schema_valid_rate: float = 1.0,
    minimum_precision: float = 0.95,
    minimum_recall: float = 0.95,
) -> ReviewEvaluation:
    """Evaluate typed, grounded BOM review findings against labeled fixtures."""
    thresholds = (minimum_schema_valid_rate, minimum_precision, minimum_recall)
    if any(not 0.0 <= value <= 1.0 for value in thresholds):
        raise ValueError("evaluation thresholds must be between 0 and 1")
    raw: dict[str, Any] = json.loads(expected_file.read_text(encoding="utf-8"))
    cases = [_ExpectedCase.model_validate(item) for item in raw.get("fixtures", [])]
    if not cases:
        raise ValueError("review evaluation requires at least one fixture")
    results: list[ReviewFixtureResult] = []
    models: set[str] = set()
    for case in cases:
        result, model = _run_case(fixture_dir, case, provider, prompt_dirs)
        results.append(result)
        if model:
            models.add(model)
    expected_count = sum(result.expected_findings for result in results)
    actual_count = sum(result.actual_findings for result in results)
    true_positives = sum(result.true_positives for result in results)
    precision = (
        true_positives / actual_count if actual_count else (1.0 if not expected_count else 0.0)
    )
    recall = (
        true_positives / expected_count if expected_count else (1.0 if not actual_count else 0.0)
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total_actual = sum(result.actual_findings for result in results)
    grounded_count = sum(result.grounded_findings for result in results)
    grounded_rate = grounded_count / total_actual if total_actual else 1.0
    schema_valid_rate = sum(result.schema_valid for result in results) / len(results)
    return ReviewEvaluation(
        provider=provider.name,
        models=sorted(models),
        fixture_count=len(results),
        schema_valid_rate=schema_valid_rate,
        precision=precision,
        recall=recall,
        f1=f1,
        grounded_finding_rate=grounded_rate,
        minimum_schema_valid_rate=minimum_schema_valid_rate,
        minimum_precision=minimum_precision,
        minimum_recall=minimum_recall,
        cases=results,
        passed=(
            schema_valid_rate >= minimum_schema_valid_rate
            and precision >= minimum_precision
            and recall >= minimum_recall
            and grounded_rate == 1.0
        ),
    )
