from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from kiprod.net.http import HttpClient, HttpError

from .provider import LLMResult, Message, ProviderFeature


class ProviderError(RuntimeError):
    """The configured model provider returned an unusable result."""


class _Usage(BaseModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class _ChoiceMessage(BaseModel):
    content: str | None


class _Choice(BaseModel):
    message: _ChoiceMessage


class _ChatResponse(BaseModel):
    choices: list[_Choice]
    usage: _Usage | None = None


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OpenAICompatibleProvider:
    """OpenAI-style `/chat/completions` adapter, including local Ollama servers.

    JSON mode asks for a JSON object; KiProd validates the returned content against
    its own typed schema before using it. Commercial values are never inferred here.
    """

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        http: HttpClient,
        provider_name: str = "openai_compatible",
        api_key: str | None = None,
        prompt_cost_per_million: float | None = None,
        completion_cost_per_million: float | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model base URL must be an HTTP(S) origin/path without credentials")
        if parsed.scheme == "http" and not _loopback(parsed.hostname):
            raise ValueError("unencrypted model endpoints are allowed only on loopback")
        if not model.strip():
            raise ValueError("model name must not be empty")
        if not provider_name.strip():
            raise ValueError("provider name must not be empty")
        if prompt_cost_per_million is not None and prompt_cost_per_million < 0:
            raise ValueError("prompt token cost must be non-negative")
        if completion_cost_per_million is not None and completion_cost_per_million < 0:
            raise ValueError("completion token cost must be non-negative")
        if parsed.scheme == "http" and not http.allow_local_http:
            raise ValueError("HttpClient must explicitly allow loopback HTTP for local models")
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/chat/completions"
        self.model = model.strip()
        self.name = provider_name.strip()
        self.http = http
        self.api_key = api_key
        self.is_local = _loopback(parsed.hostname)
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
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.http.post(
                self.endpoint,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                headers=headers,
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        if response.status < 200 or response.status >= 300:
            raise ProviderError(f"model provider returned HTTP {response.status}")
        try:
            body = _ChatResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ProviderError("model provider returned an invalid chat completion") from exc
        if not body.choices or not body.choices[0].message.content:
            raise ProviderError("model provider returned no text content")
        prompt_tokens = body.usage.prompt_tokens if body.usage else None
        completion_tokens = body.usage.completion_tokens if body.usage else None
        estimated_cost: float | None = None
        if (
            prompt_tokens is not None
            and completion_tokens is not None
            and self.prompt_cost_per_million is not None
            and self.completion_cost_per_million is not None
        ):
            estimated_cost = (
                prompt_tokens * self.prompt_cost_per_million
                + completion_tokens * self.completion_cost_per_million
            ) / 1_000_000
        return LLMResult(
            content=body.choices[0].message.content,
            provider=self.name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=estimated_cost,
        )

    def supports(self, feature: ProviderFeature) -> bool:
        return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        if self.prompt_cost_per_million is None or self.completion_cost_per_million is None:
            return None
        return (
            prompt_tokens * self.prompt_cost_per_million
            + completion_tokens * self.completion_cost_per_million
        ) / 1_000_000
