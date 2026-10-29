from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kiprod.core.models import Offer
from kiprod.rfq.quote_import import ExtractedOffer

OfferDisposition = Literal["confirmed", "corrected", "rejected"]


class OfferDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    supplier_id: str
    source_file: str
    source_ref: str
    original: ExtractedOffer
    disposition: OfferDisposition
    corrected_offer: Offer | None = None
    comment: str = ""
    decided_at: datetime


class OfferDecisionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    decisions: list[OfferDecision] = Field(default_factory=list)


def candidate_key(supplier_id: str, source_file: str, index: int, candidate: ExtractedOffer) -> str:
    payload = json.dumps(
        {
            "supplier_id": supplier_id,
            "source_file": source_file,
            "index": index,
            "candidate": candidate.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_offer_decisions(path: Path) -> OfferDecisionLog:
    if not path.is_file():
        return OfferDecisionLog()
    return OfferDecisionLog.model_validate_json(path.read_text(encoding="utf-8"))


def latest_offer_decisions(log: OfferDecisionLog) -> dict[str, OfferDecision]:
    latest: dict[str, OfferDecision] = {}
    for decision in log.decisions:
        latest[decision.candidate_key] = decision
    return latest


def record_offer_decision(
    path: Path,
    *,
    supplier_id: str,
    source_file: str,
    index: int,
    candidate: ExtractedOffer,
    disposition: OfferDisposition,
    comment: str = "",
    corrected_offer: Offer | None = None,
) -> OfferDecisionLog:
    if index < 0:
        raise ValueError("offer candidate index must be non-negative")
    cleaned_comment = comment.strip()
    if disposition in {"corrected", "rejected"} and not cleaned_comment:
        raise ValueError(f"a comment is required to mark a candidate {disposition}")
    if len(cleaned_comment) > 2000:
        raise ValueError("quote review comments must not exceed 2000 characters")
    if disposition == "corrected":
        if corrected_offer is None:
            raise ValueError("a corrected offer is required")
        if corrected_offer.source_ref != candidate.offer.source_ref:
            raise ValueError("corrections must retain the original source reference")
        if corrected_offer.supplier_id != supplier_id:
            raise ValueError("correction must retain the imported supplier ID")
    elif corrected_offer is not None:
        raise ValueError("corrected_offer is only valid for a corrected disposition")

    existing = load_offer_decisions(path)
    decision = OfferDecision(
        candidate_key=candidate_key(supplier_id, source_file, index, candidate),
        supplier_id=supplier_id,
        source_file=source_file,
        source_ref=(
            f"{candidate.offer.source_ref.path}"
            + (
                f"#{candidate.offer.source_ref.reference}"
                if candidate.offer.source_ref.reference
                else ""
            )
        ),
        original=candidate,
        disposition=disposition,
        corrected_offer=corrected_offer,
        comment=cleaned_comment,
        decided_at=datetime.now(UTC),
    )
    result = existing.model_copy(update={"decisions": [*existing.decisions, decision]})
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
