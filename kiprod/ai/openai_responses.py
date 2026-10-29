from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from kiprod.net.http import HttpClient, HttpError

from .openai_compatible import ProviderError
from .provider import LLMResult, Message, ProviderFeature
from .schema import openai_strict_schema


class _Usage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class _OutputContent(BaseModel):
    type: str
    text: str | None = None


class _OutputItem(BaseModel):
    type: str
    content: list[_OutputContent] = Field(default_factory=list)


class _Response(BaseModel):
    status: str
    model: str | None = None
    output: list[_OutputItem] = Field(default_factory=list)
    usage: _Usage | None = None


class OpenAIResponsesProvider:
    """Native OpenAI Responses API adapter using KiProd's allowlisted HTTP client."""

    name = "openai"
    is_local = False

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        http: HttpClient,
        base_url: str = "https://api.openai.com/v1",
        schema_name: str = "kiprod_output",
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
            raise ValueError("OpenAI base URL must be HTTPS without embedded credentials")
        if not api_key.strip() or not model.strip():
            raise ValueError("OpenAI API key and model name are required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", schema_name):
            raise ValueError(
                "schema_name must contain only letters, digits, underscores, or dashes"
            )
        _validate_rates(prompt_cost_per_million, completion_cost_per_million)
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/responses"
        self.api_key = api_key
        self.model = model
        self.http = http
        self.schema_name = schema_name
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
        if max_tokens < 16:
            raise ValueError("OpenAI Responses requires max_tokens of at least 16")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        payload: dict[str, object] = {
            "model": self.model,
            "input": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "store": False,
            "stream": False,
        }
        if schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": self.schema_name,
                    "strict": True,
                    "schema": openai_strict_schema(schema),
                }
            }
        try:
            response = self.http.post(
                self.endpoint,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "authorization": f"Bearer {self.api_key}",
                },
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        if response.status < 200 or response.status >= 300:
            raise ProviderError(f"OpenAI returned HTTP {response.status}")
        try:
            body = _Response.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ProviderError("OpenAI returned an invalid Responses API result") from exc
        if body.status != "completed":
            raise ProviderError(f"OpenAI response did not complete: {body.status}")
        if any(
            content.type == "refusal"
            for item in body.output
            for content in item.content
        ):
            raise ProviderError("OpenAI refused the request")
        text_parts = [
            content.text
            for item in body.output
            if item.type == "message"
            for content in item.content
            if content.type == "output_text" and content.text
        ]
        if not text_parts:
            raise ProviderError("OpenAI response contained no output text")
        prompt_tokens = body.usage.input_tokens if body.usage else None
        completion_tokens = body.usage.output_tokens if body.usage else None
        estimated_cost = _estimate_cost(
            prompt_tokens,
            completion_tokens,
            self.prompt_cost_per_million,
            self.completion_cost_per_million,
        )
        return LLMResult(
            content="".join(text_parts),
            provider=self.name,
            model=body.model or self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
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
