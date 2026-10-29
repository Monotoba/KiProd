from __future__ import annotations

from kiprod.ai.provider import LLMResult, Message, ProviderFeature
from kiprod.ai.runtime import AIBudgetExceeded, AIRequestManager, RolePolicy


class FakeProvider:
    name = "fake"
    is_local = True

    def __init__(self, *, priced: bool = True) -> None:
        self.calls = 0
        self.priced = priced

    def complete(
        self,
        messages: list[Message],
        *,
        schema: dict[str, object] | None = None,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        self.calls += 1
        return LLMResult(
            content="{}",
            provider=self.name,
            model="fake-model",
            prompt_tokens=4,
            completion_tokens=2,
            estimated_cost=0.006 if self.priced else None,
        )

    def supports(self, feature: ProviderFeature) -> bool:
        return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        return (prompt_tokens + completion_tokens) * 0.001 if self.priced else None


def test_ai_manager_dry_run_and_content_cache() -> None:
    provider = FakeProvider()
    manager = AIRequestManager(
        {"reasoning": RolePolicy(provider, "fake-model", max_output_tokens=20)},
        max_run_tokens=100,
        max_run_cost=0.1,
    )
    messages = [Message(role="user", content="check this BOM")]
    schema = {"type": "object"}

    plan = manager.complete(
        "reasoning", messages, schema=schema, max_tokens=10, dry_run=True
    )
    assert plan.allowed
    assert plan.prompt_token_upper_bound > len(messages[0].content)
    assert plan.estimated_max_cost is not None and plan.estimated_max_cost > 0
    assert provider.calls == 0

    first = manager.complete("reasoning", messages, schema=schema, max_tokens=10)
    assert isinstance(first, LLMResult)
    assert provider.calls == 1
    assert manager.usage.total_tokens == 6

    cached = manager.complete("reasoning", messages, schema=schema, max_tokens=10)
    assert cached == first
    assert provider.calls == 1
    assert manager.usage.total_tokens == 6


def test_ai_manager_blocks_token_and_cost_overages_before_provider_call() -> None:
    provider = FakeProvider()
    token_limited = AIRequestManager(
        {"extraction": RolePolicy(provider, "fake-model", max_output_tokens=20)},
        max_run_tokens=5,
    )
    plan = token_limited.plan(
        "extraction", [Message(role="user", content="hello")], max_tokens=1
    )
    assert not plan.allowed
    assert "token budget" in (plan.reason or "")

    unpriced = FakeProvider(priced=False)
    cost_limited = AIRequestManager(
        {"writer": RolePolicy(unpriced, "fake-model", max_output_tokens=20)},
        max_run_cost=1.0,
    )
    plan = cost_limited.plan(
        "writer", [Message(role="user", content="write")], max_tokens=5
    )
    assert not plan.allowed
    assert "pricing is unknown" in (plan.reason or "")
    try:
        cost_limited.complete("writer", [Message(role="user", content="write")], max_tokens=5)
    except AIBudgetExceeded as exc:
        assert "pricing is unknown" in str(exc)
    else:
        raise AssertionError("unknown cost should fail closed")
    assert unpriced.calls == 0


def test_ai_manager_enforces_local_only_and_role_output_limit() -> None:
    remote = FakeProvider()
    remote.is_local = False
    manager = AIRequestManager(
        {"local_only": RolePolicy(remote, "remote-model", max_output_tokens=5, local_only=True)}
    )
    messages = [Message(role="user", content="data")]

    local_plan = manager.plan("local_only", messages, max_tokens=1)
    assert not local_plan.allowed
    assert "requires a local" in (local_plan.reason or "")

    remote.is_local = True
    token_plan = manager.plan("local_only", messages, max_tokens=6)
    assert not token_plan.allowed
    assert "role limit" in (token_plan.reason or "")
