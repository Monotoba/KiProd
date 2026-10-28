from __future__ import annotations

import pytest

from kiprod.core.defaults import Policy, Rule, resolve


@pytest.mark.parametrize(
    ("policy", "value", "expected", "source"),
    [
        (Policy.DEFAULT, "0.10", "0.10", "default"),
        (Policy.INHERIT, None, "parent", "inherited"),
        (Policy.IGNORE, None, None, "ignored"),
    ],
)
def test_resolves_deterministic_policies(
    policy: Policy, value: str | None, expected: str | None, source: str
) -> None:
    result = resolve(Rule(policy=policy, value=value), None, inherited="parent")
    assert result.value == expected
    assert result.source == source


def test_existing_value_is_preserved() -> None:
    result = resolve(Rule(policy=Policy.ERROR), "10V")
    assert result.value == "10V"
    assert result.source == "schematic"


def test_flag_in_noninteractive_mode_is_an_error() -> None:
    result = resolve(Rule(policy=Policy.FLAG), None, interactive=False)
    assert result.error == "attribute requires interactive input"
    assert result.source == "error"


def test_guess_degrades_to_flag_without_ai() -> None:
    result = resolve(Rule(policy=Policy.GUESS), None, interactive=False)
    assert result.requires_input
    assert result.source == "flag"


def test_required_error_is_reported() -> None:
    result = resolve(Rule(policy=Policy.ERROR), None)
    assert result.error == "attribute is required"
