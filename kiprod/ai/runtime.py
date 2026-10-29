from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from .provider import LLMProvider, LLMResult, Message

AIRole = Literal["reasoning", "extraction", "writer", "local_only"]


class AIBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class RolePolicy:
    provider: LLMProvider
    model: str
    max_output_tokens: int
    local_only: bool = False

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("configured model name must not be empty")
        if self.max_output_tokens < 1:
            raise ValueError("role max_output_tokens must be positive")


class RequestPlan(BaseModel):
    role: AIRole
    allowed: bool
    reason: str | None = None
    cache_hit: bool = False
    prompt_token_upper_bound: int
    max_output_tokens: int
    estimated_max_cost: float | None = None


@dataclass
class RunUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class AIRequestManager:
    """Enforce role, local-only, token, and cost policies around provider calls.

    Prompt budgeting uses UTF-8 byte length as a conservative token upper bound;
    provider-reported token usage replaces that bound after a completed call.
    Response caching is in-memory and scoped to this manager's lifetime.
    """

    roles: dict[AIRole, RolePolicy]
    max_run_tokens: int | None = None
    max_run_cost: float | None = None
    usage: RunUsage = field(default_factory=RunUsage)
    _cache: dict[str, LLMResult] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_run_tokens is not None and self.max_run_tokens < 1:
            raise ValueError("max_run_tokens must be positive")
        if self.max_run_cost is not None and (
            not math.isfinite(self.max_run_cost) or self.max_run_cost < 0
        ):
            raise ValueError("max_run_cost must be a finite non-negative amount")

    def plan(
        self,
        role: AIRole,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
        confidential: bool = False,
    ) -> RequestPlan:
        policy = self._policy(role)
        prompt_size = 8 + sum(len(message.content.encode("utf-8")) + 8 for message in messages)
        if schema is not None:
            prompt_size += len(json.dumps(schema, sort_keys=True).encode("utf-8")) + 8
        cache_key = self._cache_key(role, policy, messages, schema, max_tokens, temperature)
        cached = cache_key in self._cache
        estimate = self._estimated_cost(policy, prompt_size, max_tokens)
        plan = RequestPlan(
            role=role,
            allowed=True,
            cache_hit=cached,
            prompt_token_upper_bound=prompt_size,
            max_output_tokens=max_tokens,
            estimated_max_cost=estimate,
        )
        reason: str | None = None
        if confidential and not policy.provider.is_local:
            reason = "confidential projects require a local provider"
        elif policy.local_only and not policy.provider.is_local:
            reason = f"the {role} role requires a local provider"
        elif max_tokens < 1:
            reason = "max_tokens must be positive"
        elif max_tokens > policy.max_output_tokens:
            reason = (
                f"requested {max_tokens} output tokens exceeds role limit "
                f"{policy.max_output_tokens}"
            )
        elif cached:
            return plan
        elif (
            self.max_run_tokens is not None
            and self.usage.total_tokens + prompt_size + max_tokens > self.max_run_tokens
        ):
            reason = "request exceeds the remaining run token budget"
        elif self.max_run_cost is not None and estimate is None:
            reason = "provider pricing is unknown; cannot enforce the configured cost budget"
        elif (
            self.max_run_cost is not None
            and estimate is not None
            and self.usage.cost + estimate > self.max_run_cost
        ):
            reason = "request exceeds the remaining run cost budget"
        if reason:
            plan.allowed = False
            plan.reason = reason
        return plan

    def complete(
        self,
        role: AIRole,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
        confidential: bool = False,
        dry_run: bool = False,
    ) -> LLMResult | RequestPlan:
        policy = self._policy(role)
        plan = self.plan(
            role,
            messages,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
            confidential=confidential,
        )
        if dry_run:
            return plan
        if not plan.allowed:
            raise AIBudgetExceeded(plan.reason or "AI request is not allowed")
        cache_key = self._cache_key(role, policy, messages, schema, max_tokens, temperature)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = policy.provider.complete(
            messages,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        prompt_tokens = result.prompt_tokens or plan.prompt_token_upper_bound
        completion_tokens = result.completion_tokens or max_tokens
        if prompt_tokens < 0 or completion_tokens < 0:
            raise AIBudgetExceeded("provider returned invalid token usage")
        cost = result.estimated_cost
        if cost is None:
            cost = policy.provider.estimate_cost(prompt_tokens, completion_tokens)
        if cost is not None and (not math.isfinite(cost) or cost < 0):
            raise AIBudgetExceeded("provider returned an invalid cost estimate")
        if cost is None and self.max_run_cost is not None:
            raise AIBudgetExceeded(
                "provider returned no cost; configured cost budget cannot be verified"
            )
        actual_cost = cost or 0.0
        if self.max_run_tokens is not None and (
            self.usage.total_tokens + prompt_tokens + completion_tokens > self.max_run_tokens
        ):
            raise AIBudgetExceeded("provider usage exceeded the run token budget")
        if self.max_run_cost is not None and self.usage.cost + actual_cost > self.max_run_cost:
            raise AIBudgetExceeded("provider usage exceeded the run cost budget")
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens
        self.usage.cost += actual_cost
        self._cache[cache_key] = result
        return result

    def _policy(self, role: AIRole) -> RolePolicy:
        try:
            return self.roles[role]
        except KeyError as exc:
            raise ValueError(f"no AI provider configured for role: {role}") from exc

    def _estimated_cost(
        self, policy: RolePolicy, prompt_tokens: int, completion_tokens: int
    ) -> float | None:
        estimate = policy.provider.estimate_cost(prompt_tokens, completion_tokens)
        if estimate is not None and (not math.isfinite(estimate) or estimate < 0):
            return None
        return estimate

    @staticmethod
    def _cache_key(
        role: AIRole,
        policy: RolePolicy,
        messages: list[Message],
        schema: dict[str, object] | None,
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload = {
            "role": role,
            "provider": policy.provider.name,
            "model": policy.model,
            "messages": [message.__dict__ for message in messages],
            "schema": schema,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
