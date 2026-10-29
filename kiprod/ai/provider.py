from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

MessageRole = Literal["system", "user", "assistant"]
ProviderFeature = Literal["tools", "json_schema", "vision", "caching"]


@dataclass(frozen=True)
class Message:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class LLMResult:
    content: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost: float | None = None


class LLMProvider(Protocol):
    """Provider contract; network adapters must use KiProd's HttpClient."""

    name: str
    is_local: bool

    def complete(
        self,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult: ...

    def supports(self, feature: ProviderFeature) -> bool: ...

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None: ...
