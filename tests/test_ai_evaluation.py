from __future__ import annotations

import json
from pathlib import Path

from kiprod.ai.evaluation import evaluate_review_fixtures
from kiprod.ai.provider import LLMResult, Message, ProviderFeature

FIXTURES = Path(__file__).parent / "fixtures" / "ai_review"
EXPECTED = FIXTURES / "expected.json"


class ReviewFixtureProvider:
    name = "fixture-review"
    is_local = True

    def __init__(self, *, code: str = "bom.verify_resistor_rating") -> None:
        self.code = code
        self.calls = 0

    def complete(
        self,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        self.calls += 1
        bom_payload = json.loads(messages[1].content)
        line = next(item for item in bom_payload["lines"] if item["mpn"])
        content = json.dumps(
            {
                "findings": [
                    {
                        "code": self.code,
                        "severity": "info",
                        "area": "electrical",
                        "summary": "Confirm the selected resistor rating.",
                        "suggested_action": None,
                        "confidence": 0.8,
                        "line_ids": [line["line_id"]],
                    }
                ]
            }
        )
        return LLMResult(content, self.name, "fixture-model", 20, 15)

    def supports(self, feature: ProviderFeature) -> bool:
        return feature == "json_schema"

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        return 0.0


def test_review_evaluation_scores_labeled_grounded_output() -> None:
    provider = ReviewFixtureProvider()

    report = evaluate_review_fixtures(FIXTURES, EXPECTED, provider)

    assert report.passed
    assert report.provider == provider.name
    assert report.models == ["fixture-model"]
    assert report.schema_valid_rate == 1.0
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0
    assert report.grounded_finding_rate == 1.0
    assert provider.calls == 1


def test_review_evaluation_detects_model_false_positive() -> None:
    provider = ReviewFixtureProvider(code="unsupported.new_finding")

    report = evaluate_review_fixtures(FIXTURES, EXPECTED, provider)

    assert not report.passed
    assert report.precision == 0.0
    assert report.recall == 0.0
    assert report.cases[0].false_positives == 1
    assert report.cases[0].false_negatives == 1
