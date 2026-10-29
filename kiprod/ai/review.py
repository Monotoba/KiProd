from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kiprod.core.models import BOMLine, NormalizedBOM, SourceRef

from .provider import LLMProvider, Message


class ReviewFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    area: Literal["bom", "electrical", "footprint", "manufacturing"]
    summary: str
    suggested_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["rule", "ai_guess"]
    line_ids: list[str] = Field(default_factory=list)
    evidence: list[SourceRef] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None


class ReviewReport(BaseModel):
    schema_version: int = 1
    project: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    ai_provider: str | None = None
    ai_model: str | None = None
    prompt_version: str | None = None
    ai_status: Literal["not_configured", "completed"] = "not_configured"


class _FindingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["info", "warning", "error"]
    area: Literal["bom", "electrical", "footprint", "manufacturing"]
    summary: str
    suggested_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    line_ids: list[str] = Field(min_length=1)


class _ProposalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[_FindingProposal] = Field(default_factory=list)


_REVIEW_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "severity", "area", "summary", "confidence", "line_ids"],
                "properties": {
                    "code": {"type": "string", "minLength": 1},
                    "severity": {"enum": ["info", "warning", "error"]},
                    "area": {
                        "enum": ["bom", "electrical", "footprint", "manufacturing"]
                    },
                    "summary": {"type": "string", "minLength": 1},
                    "suggested_action": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "line_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
            },
        }
    },
}


def _deterministic_findings(lines: list[BOMLine]) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for line in lines:
        if not line.mpn:
            findings.append(
                ReviewFinding(
                    code="bom.missing_mpn",
                    severity="warning",
                    area="bom",
                    summary=f"{', '.join(line.references)} has no manufacturer part number.",
                    suggested_action="Resolve the MPN before requesting supplier quotes.",
                    confidence=1.0,
                    source="rule",
                    line_ids=[line.line_id],
                    evidence=line.sources,
                )
            )
        if not line.footprint:
            findings.append(
                ReviewFinding(
                    code="bom.missing_footprint",
                    severity="warning",
                    area="footprint",
                    summary=f"{', '.join(line.references)} has no footprint assigned.",
                    suggested_action="Assign and verify a footprint before fabrication.",
                    confidence=1.0,
                    source="rule",
                    line_ids=[line.line_id],
                    evidence=line.sources,
                )
            )
    return findings


def _review_payload(bom: NormalizedBOM) -> str:
    """Send only minimal BOM identity fields; omit arbitrary user fields and quotes."""
    lines = [
        {
            "line_id": line.line_id,
            "references": line.references,
            "quantity": line.quantity,
            "value": line.value,
            "footprint": line.footprint,
            "mpn": line.mpn,
        }
        for line in bom.lines
    ]
    return json.dumps({"project": bom.project, "lines": lines}, sort_keys=True)


def review_bom(
    bom: NormalizedBOM,
    *,
    provider: LLMProvider | None = None,
    prompt_version: str = "bom-review-v1",
    max_tokens: int = 2000,
    confidential: bool = False,
) -> ReviewReport:
    """Run deterministic BOM checks, then optionally add grounded typed AI findings."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    findings = _deterministic_findings(bom.lines)
    report = ReviewReport(project=bom.project, findings=findings, prompt_version=prompt_version)
    if provider is None:
        return report
    if confidential and not provider.is_local:
        raise ValueError("confidential projects require a local AI provider")

    result = provider.complete(
        [
            Message(
                role="system",
                content=(
                    "Review the provided BOM for plausible production risks. "
                    "Return only the requested JSON schema. Cite one or more supplied line_ids. "
                    "Do not invent or estimate price, stock, lead time, duty, or other "
                    "commercial values."
                ),
            ),
            Message(role="user", content=_review_payload(bom)),
        ],
        schema=_REVIEW_SCHEMA,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    proposals = _ProposalSet.model_validate_json(result.content)
    known_lines = {line.line_id: line for line in bom.lines}
    for proposal in proposals.findings:
        unknown = sorted(set(proposal.line_ids) - known_lines.keys())
        if unknown:
            raise ValueError("AI finding cites unknown BOM line ID(s): " + ", ".join(unknown))
        evidence = sorted(
            {
                ref.model_dump_json(): ref
                for line_id in proposal.line_ids
                for ref in known_lines[line_id].sources
            }.values(),
            key=lambda ref: (ref.path, ref.reference or ""),
        )
        findings.append(
            ReviewFinding(
                **proposal.model_dump(),
                source="ai_guess",
                evidence=evidence,
                provider=result.provider,
                model=result.model,
                prompt_version=prompt_version,
            )
        )
    return ReviewReport(
        project=bom.project,
        findings=findings,
        ai_provider=result.provider,
        ai_model=result.model,
        prompt_version=prompt_version,
        ai_status="completed",
    )
