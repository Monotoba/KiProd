from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .review import ReviewFinding

Disposition = Literal["accept", "dismiss", "defer"]


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: str
    line_ids: list[str]
    disposition: Disposition
    comment: str
    decided_at: datetime


class ReviewDecisionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    decisions: list[ReviewDecision] = Field(default_factory=list)


def finding_key(finding: ReviewFinding) -> str:
    payload = json.dumps(finding.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_decisions(path: Path) -> ReviewDecisionLog:
    if not path.is_file():
        return ReviewDecisionLog()
    return ReviewDecisionLog.model_validate_json(path.read_text(encoding="utf-8"))


def record_decision(
    path: Path,
    finding: ReviewFinding,
    disposition: Disposition,
    comment: str,
) -> ReviewDecisionLog:
    cleaned_comment = comment.strip()
    if disposition != "accept" and not cleaned_comment:
        raise ValueError(f"a comment is required to {disposition} a finding")
    if len(cleaned_comment) > 2000:
        raise ValueError("review comments must not exceed 2000 characters")
    decisions = load_decisions(path)
    updated = ReviewDecision(
        finding_key=finding_key(finding),
        code=finding.code,
        line_ids=finding.line_ids,
        disposition=disposition,
        comment=cleaned_comment,
        decided_at=datetime.now(UTC),
    )
    result = decisions.model_copy(update={"decisions": [*decisions.decisions, updated]})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(result.model_dump_json(indent=2) + "\n")
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return result


def latest_dispositions(log: ReviewDecisionLog) -> dict[str, Disposition]:
    latest: dict[str, Disposition] = {}
    for decision in log.decisions:
        latest[decision.finding_key] = decision.disposition
    return latest
