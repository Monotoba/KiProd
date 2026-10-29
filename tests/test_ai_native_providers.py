from __future__ import annotations

import json

import pytest

from kiprod.ai.anthropic import AnthropicProvider
from kiprod.ai.openai_compatible import ProviderError
from kiprod.ai.openai_responses import OpenAIResponsesProvider
from kiprod.ai.provider import Message
from kiprod.net.http import HttpClient, HttpResponse


class RecordingHttpClient(HttpClient):
    def __init__(self, host: str, response: HttpResponse) -> None:
        super().__init__({host})
        self.response = response
        self.request: tuple[str, bytes, dict[str, str]] | None = None

    def post(
        self, url: str, body: bytes, *, headers: dict[str, str] | None = None
    ) -> HttpResponse:
        self.request = (url, body, headers or {})
        return self.response


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "finding": {"type": "string"},
            "details": {"type": "string"},
        },
        "required": ["finding"],
    }


def test_openai_responses_provider_sends_strict_schema_and_extracts_output() -> None:
    client = RecordingHttpClient(
        "api.openai.test",
        HttpResponse(
            200,
            {},
            json.dumps(
                {
                    "status": "completed",
                    "model": "actual-model",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": '{"finding":"ok"}'}],
                        }
                    ],
                    "usage": {"input_tokens": 50, "output_tokens": 10},
                }
            ).encode(),
        ),
    )
    provider = OpenAIResponsesProvider(
        api_key="test-key",
        model="configured-model",
        base_url="https://api.openai.test/v1",
        http=client,
        prompt_cost_per_million=1.0,
        completion_cost_per_million=2.0,
    )

    result = provider.complete(
        [Message(role="system", content="system"), Message(role="user", content="review")],
        schema=_schema(),
        max_tokens=100,
    )

    assert result.content == '{"finding":"ok"}'
    assert result.model == "actual-model"
    assert result.estimated_cost == pytest.approx(0.00007)
    assert client.request is not None
    url, body, headers = client.request
    assert url == "https://api.openai.test/v1/responses"
    assert headers["authorization"] == "Bearer test-key"
    payload = json.loads(body)
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 100
    strict = payload["text"]["format"]
    assert strict["type"] == "json_schema" and strict["strict"] is True
    assert strict["schema"]["required"] == ["details", "finding"]
    assert strict["schema"]["properties"]["details"]["type"] == ["string", "null"]
    assert strict["schema"]["additionalProperties"] is False


def test_anthropic_provider_sends_version_headers_schema_and_system_prompt() -> None:
    client = RecordingHttpClient(
        "api.anthropic.test",
        HttpResponse(
            200,
            {},
            json.dumps(
                {
                    "model": "claude-fixture",
                    "content": [{"type": "text", "text": '{"finding":"ok"}'}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 40, "output_tokens": 12},
                }
            ).encode(),
        ),
    )
    provider = AnthropicProvider(
        api_key="anthropic-test-key",
        model="claude-configured",
        base_url="https://api.anthropic.test/v1",
        http=client,
    )

    result = provider.complete(
        [Message(role="system", content="rules"), Message(role="user", content="review")],
        schema=_schema(),
        max_tokens=100,
    )

    assert result.content == '{"finding":"ok"}'
    assert result.provider == "anthropic"
    assert result.model == "claude-fixture"
    assert client.request is not None
    url, body, headers = client.request
    assert url == "https://api.anthropic.test/v1/messages"
    assert headers["x-api-key"] == "anthropic-test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    payload = json.loads(body)
    assert payload["system"] == "rules"
    assert payload["messages"] == [{"role": "user", "content": "review"}]
    assert payload["output_config"]["format"]["schema"] == _schema()


def test_native_providers_reject_refusal_or_truncated_output() -> None:
    openai_client = RecordingHttpClient(
        "api.openai.test",
        HttpResponse(
            200,
            {},
            b'{"status":"incomplete","output":[],"usage":{"input_tokens":4,"output_tokens":5}}',
        ),
    )
    openai = OpenAIResponsesProvider(
        api_key="key", model="m", base_url="https://api.openai.test/v1", http=openai_client
    )
    with pytest.raises(ProviderError, match="did not complete"):
        openai.complete([Message(role="user", content="x")], max_tokens=16)

    anthropic_client = RecordingHttpClient(
        "api.anthropic.test",
        HttpResponse(
            200,
            {},
            b'{"model":"m","content":[{"type":"text","text":"partial"}],'
            b'"stop_reason":"max_tokens","usage":{"input_tokens":4,"output_tokens":5}}',
        ),
    )
    anthropic = AnthropicProvider(
        api_key="key", model="m", base_url="https://api.anthropic.test", http=anthropic_client
    )
    with pytest.raises(ProviderError, match="max_tokens"):
        anthropic.complete([Message(role="user", content="x")], max_tokens=10)
