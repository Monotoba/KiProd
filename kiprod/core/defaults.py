"""Deterministic resolution of missing production attributes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class Policy(StrEnum):
    DEFAULT = "default"
    FLAG = "flag"
    ERROR = "error"
    GUESS = "guess"
    INHERIT = "inherit"
    IGNORE = "ignore"


class Rule(BaseModel):
    policy: Policy
    value: Any | None = None


class Resolution(BaseModel):
    value: Any | None = None
    source: str
    requires_input: bool = False
    error: str | None = None


def resolve(
    rule: Rule,
    current: Any | None,
    *,
    inherited: Any | None = None,
    interactive: bool = True,
) -> Resolution:
    """Resolve one attribute without invoking AI or prompting the user.

    A caller owns any GUI/CLI prompt.  This preserves a complete audit trail and
    makes non-interactive runs deterministic.
    """
    if current is not None:
        return Resolution(value=current, source="schematic")
    if rule.policy is Policy.IGNORE:
        return Resolution(source="ignored")
    if rule.policy is Policy.DEFAULT:
        if rule.value is None:
            return Resolution(source="error", error="default policy requires a value")
        return Resolution(value=rule.value, source="default")
    if rule.policy is Policy.INHERIT:
        if inherited is None:
            return Resolution(source="error", error="inherit policy has no parent value")
        return Resolution(value=inherited, source="inherited")
    if rule.policy is Policy.ERROR:
        return Resolution(source="error", error="attribute is required")
    if rule.policy is Policy.GUESS:
        return Resolution(
            source="flag",
            requires_input=True,
            error="AI guessing is unavailable; attribute requires review",
        )
    if rule.policy is Policy.FLAG:
        if interactive:
            return Resolution(source="flag", requires_input=True)
        return Resolution(
            source="error",
            error="attribute requires interactive input",
        )
    raise AssertionError(f"unhandled policy: {rule.policy}")
