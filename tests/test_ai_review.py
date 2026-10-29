from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kiprod.ai.provider import LLMResult, Message, ProviderFeature
from kiprod.ai.review import review_bom
from kiprod.core.models import NormalizedBOM

FIXTURES = Path(__file__).parent / "golden"


class FixtureProvider:
    name = "fixture"
    is_local = True

    def __init__(self, response: str) -> None:
        self.response = response
        self.messages: list[Message] | None = None
        self.schema: dict[str, object] | None = None

    def complete(
        self,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        self.messages = messages
        self.schema = schema
        assert max_tokens > 0
        assert temperature == 0.0
        return LLMResult(self.response, "fixture", "fixture-model")

    def supports(self, feature: ProviderFeature) -> bool:
        return feature == "json_schema"

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        return 0.0


def _bom() -> NormalizedBOM:
    return NormalizedBOM.model_validate_json(
        (FIXTURES / "basic.normalized.json").read_text(encoding="utf-8")
    )


def test_review_without_provider_runs_rules_and_degrades_to_flag() -> None:
    report = review_bom(_bom())

    assert report.ai_status == "not_configured"
    assert report.ai_provider is None
    assert report.findings
    assert all(finding.source == "rule" for finding in report.findings)
    assert any(finding.code == "bom.missing_mpn" for finding in report.findings)


def test_ai_review_is_typed_grounded_and_data_minimized() -> None:
    bom = _bom()
    response = json.dumps(
        {
            "findings": [
                {
                    "code": "bom.verify_resistor_rating",
                    "severity": "info",
                    "area": "electrical",
                    "summary": "Confirm the resistor rating against the design requirements.",
                    "suggested_action": "Review the selected component rating.",
                    "confidence": 0.76,
                    "line_ids": [bom.lines[1].line_id],
                }
            ]
        }
    )
    provider = FixtureProvider(response)

    report = review_bom(bom, provider=provider, prompt_version="review-v1")

    finding = next(item for item in report.findings if item.source == "ai_guess")
    assert finding.provider == "fixture"
    assert finding.model == "fixture-model"
    assert finding.prompt_version == "review-v1"
    assert finding.evidence == bom.lines[1].sources
    assert report.ai_status == "completed"
    assert provider.schema is not None
    assert provider.messages is not None
    payload = provider.messages[1].content
    assert "fields" not in payload
    assert "resolved_fields" not in payload
    assert "input_hashes" not in payload


def test_ai_review_rejects_unknown_line_ids_and_commercial_fields() -> None:
    bom = _bom()
    common = {
        "code": "bad.finding",
        "severity": "warning",
        "area": "bom",
        "summary": "A test finding.",
        "confidence": 0.5,
    }
    unknown = FixtureProvider(
        json.dumps({"findings": [{**common, "line_ids": ["not-a-bom-line"]}]})
    )
    with pytest.raises(ValueError, match="unknown BOM line"):
        review_bom(bom, provider=unknown)

    commercial = FixtureProvider(
        json.dumps(
            {
                "findings": [
                    {**common, "line_ids": [bom.lines[0].line_id], "price": 0.01}
                ]
            }
        )
    )
    with pytest.raises(ValidationError):
        review_bom(bom, provider=commercial)


def test_confidential_bom_rejects_remote_provider_before_call() -> None:
    class RemoteProvider(FixtureProvider):
        is_local = False

    provider = RemoteProvider('{"findings": []}')
    with pytest.raises(ValueError, match="require a local"):
        review_bom(_bom(), provider=provider, confidential=True)
    assert provider.messages is None
