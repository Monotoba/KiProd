from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from kiprod.net.http import HttpClient, HttpError

from .openai_compatible import ProviderError
from .provider import LLMResult, Message, ProviderFeature


class _ContentBlock(BaseModel):
    type: str
    text: str | None = None


class _Usage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class _MessageResponse(BaseModel):
    model: str
    content: list[_ContentBlock]
    stop_reason: str | None = None
    usage: _Usage


class AnthropicProvider:
    """Anthropic Messages API adapter using KiProd's allowlisted HTTP client."""

    name = "anthropic"
    is_local = False

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        http: HttpClient,
        base_url: str = "https://api.anthropic.com",
        api_version: str = "2023-06-01",
        prompt_cost_per_million: float | None = None,
        completion_cost_per_million: float | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Anthropic base URL must be HTTPS without embedded credentials")
        if not api_key.strip() or not model.strip():
            raise ValueError("Anthropic API key and model name are required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", api_version):
            raise ValueError("Anthropic API version must use YYYY-MM-DD format")
        _validate_rates(prompt_cost_per_million, completion_cost_per_million)
        self.base_url = base_url.rstrip("/")
        self.endpoint = (
            f"{self.base_url}/messages"
            if parsed.path.rstrip("/").endswith("/v1")
            else f"{self.base_url}/v1/messages"
        )
        self.api_key = api_key
        self.model = model
        self.http = http
        self.api_version = api_version
        self.prompt_cost_per_million = prompt_cost_per_million
        self.completion_cost_per_million = completion_cost_per_million

    def complete(
        self,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if temperature != 0.0:
            raise ValueError("Anthropic adapter currently uses provider-default temperature")
        system = "\n\n".join(message.content for message in messages if message.role == "system")
        conversation = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role in {"user", "assistant"}
        ]
        if not conversation or not any(message["role"] == "user" for message in conversation):
            raise ValueError("Anthropic Messages requires at least one user message")
        payload: dict[str, object] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": conversation,
        }
        if system:
            payload["system"] = system
        if schema is not None:
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }
        try:
            response = self.http.post(
                self.endpoint,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": self.api_version,
                },
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        if response.status < 200 or response.status >= 300:
            raise ProviderError(f"Anthropic returned HTTP {response.status}")
        try:
            body = _MessageResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ProviderError("Anthropic returned an invalid Messages API result") from exc
        if body.stop_reason == "max_tokens":
            raise ProviderError("Anthropic response reached max_tokens before completion")
        if body.stop_reason == "refusal":
            raise ProviderError("Anthropic refused the request")
        text_parts = [block.text for block in body.content if block.type == "text" and block.text]
        if not text_parts:
            raise ProviderError("Anthropic response contained no text content")
        estimated_cost = _estimate_cost(
            body.usage.input_tokens,
            body.usage.output_tokens,
            self.prompt_cost_per_million,
            self.completion_cost_per_million,
        )
        return LLMResult(
            content="".join(text_parts),
            provider=self.name,
            model=body.model,
            prompt_tokens=body.usage.input_tokens,
            completion_tokens=body.usage.output_tokens,
            estimated_cost=estimated_cost,
        )

    def supports(self, feature: ProviderFeature) -> bool:
        return feature == "json_schema"

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        return _estimate_cost(
            prompt_tokens,
            completion_tokens,
            self.prompt_cost_per_million,
            self.completion_cost_per_million,
        )


def _validate_rates(prompt: float | None, completion: float | None) -> None:
    for rate in (prompt, completion):
        if rate is not None and (not math.isfinite(rate) or rate < 0):
            raise ValueError("token cost rates must be finite and non-negative")


def _estimate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    prompt_rate: float | None,
    completion_rate: float | None,
) -> float | None:
    if (
        prompt_tokens is None
        or completion_tokens is None
        or prompt_rate is None
        or completion_rate is None
    ):
        return None
    return (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000
