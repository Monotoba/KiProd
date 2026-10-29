from __future__ import annotations

import json

import pytest

from kiprod.ai.openai_compatible import OpenAICompatibleProvider, ProviderError
from kiprod.ai.provider import Message
from kiprod.net.http import HttpClient, HttpResponse


class RecordingHttpClient(HttpClient):
    def __init__(self, response: HttpResponse, *, allow_local_http: bool = False) -> None:
        super().__init__({"127.0.0.1"}, allow_local_http=allow_local_http)
        self.response = response
        self.request: tuple[str, bytes, dict[str, str]] | None = None

    def post(
        self, url: str, body: bytes, *, headers: dict[str, str] | None = None
    ) -> HttpResponse:
        self.request = (url, body, headers or {})
        return self.response


def test_openai_compatible_provider_posts_json_and_tags_result() -> None:
    client = RecordingHttpClient(
        HttpResponse(
            200,
            {},
            json.dumps(
                {
                    "choices": [{"message": {"content": '{"findings": []}'}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                }
            ).encode(),
        ),
        allow_local_http=True,
    )
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:11434/v1",
        model="fixture-model",
        provider_name="ollama",
        api_key="local-placeholder",
        http=client,
        prompt_cost_per_million=1.0,
        completion_cost_per_million=2.0,
    )

    result = provider.complete(
        [Message(role="user", content="review")], schema={"type": "object"}, max_tokens=80
    )

    assert result.content == '{"findings": []}'
    assert result.provider == "ollama"
    assert result.model == "fixture-model"
    assert result.estimated_cost == pytest.approx(0.00014)
    assert provider.is_local
    assert client.request is not None
    url, body, headers = client.request
    assert url == "http://127.0.0.1:11434/v1/chat/completions"
    assert headers["authorization"] == "Bearer local-placeholder"
    payload = json.loads(body)
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False
    assert payload["max_tokens"] == 80


def test_model_provider_only_allows_http_for_explicit_loopback_client() -> None:
    with pytest.raises(ValueError, match="explicitly allow loopback HTTP"):
        OpenAICompatibleProvider(
            base_url="http://127.0.0.1:11434/v1",
            model="local-model",
            http=HttpClient({"127.0.0.1"}),
        )
    with pytest.raises(ValueError, match="loopback"):
        OpenAICompatibleProvider(
            base_url="http://192.0.2.1/v1",
            model="remote-model",
            http=HttpClient({"192.0.2.1"}, allow_local_http=True),
        )


def test_model_provider_rejects_bad_responses_and_estimates_unknown_cost() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://127.0.0.1/v1",
        model="fixture-model",
        http=RecordingHttpClient(HttpResponse(502, {}, b"")),
    )
    with pytest.raises(ProviderError, match="HTTP 502"):
        provider.complete([Message(role="user", content="test")], max_tokens=10)
    assert provider.estimate_cost(100, 50) is None
